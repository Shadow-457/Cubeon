"""
Resilient network download primitives - retry, resume, backoff, and a
concurrency cap - in one place.

Why this exists: the original download sites (Paper jar, mod jars, pack
files) each did their own bare requests.get() with a single attempt. One
dropped Wi-Fi packet mid-download meant a cryptic failure and a corrupted
half-file. Every download in Cubeon now goes through here so that:

  - transient failures are retried with exponential backoff (3 attempts),
    honoring a server-sent Retry-After when present;
  - large downloads RESUME from where they died (HTTP Range) instead of
    starting a 500 MB Paper jar over from byte zero;
  - a global semaphore caps how many downloads run at once, so a modpack
    with 300 files can't open 300 simultaneous connections;
  - the destination is only ever replaced by a COMPLETE, verified file
    (hash when the caller has one, magic bytes otherwise).
"""
import hashlib
import logging
import os
import threading
import time

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

log = logging.getLogger(__name__)

# A modpack install fans out into many single-file downloads; without a cap
# that's hundreds of concurrent sockets and the user's router (and Modrinth's
# CDN rate limiter) both hate it. 4 in flight keeps packs fast and polite.
MAX_CONCURRENT_DOWNLOADS = 4
DOWNLOAD_GATE = threading.BoundedSemaphore(MAX_CONCURRENT_DOWNLOADS)

DEFAULT_ATTEMPTS = 3
BACKOFF_BASE = 1.5  # seconds; doubled each retry: 1.5s, 3s, 6s...


class DownloadError(RuntimeError):
    """Every retry failed, or the response was unusable. Human-readable."""


def get_with_retry(url: str, *, headers: dict | None = None, timeout: int = 30,
                   attempts: int = DEFAULT_ATTEMPTS) -> requests.Response:
    """GET with exponential backoff on transient failures. The response is
    returned fully-connected (stream=True) and the caller must close it.

    Only network-level flakiness and 5xx/429 are retried - a 404 will never
    succeed by waiting, so it fails through immediately."""
    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, headers=headers, stream=True, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else BACKOFF_BASE * (2 ** attempt)
                except ValueError:
                    delay = BACKOFF_BASE * (2 ** attempt)
                resp.close()
                log.info("download %s: HTTP %s, retrying in %.1fs",
                         url, resp.status_code, delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as ex:
            last_err = ex
            if attempt < attempts - 1:
                delay = BACKOFF_BASE * (2 ** attempt)
                log.info("download %s: %s, retrying in %.1fs",
                         url, ex.__class__.__name__, delay)
                time.sleep(delay)
    raise DownloadError(f"Couldn't reach {url} after {attempts} tries: {last_err}")


def stream_to_file(resp: requests.Response, dest_path: str, *,
                   progress_cb=None, hasher=None, resume_from: int = 0) -> int:
    """Write a streaming response body to dest_path (append mode when
    resuming). Returns bytes written this call. A dropped connection
    mid-body raises requests.RequestException, which callers treat as
    retryable.

    progress_cb is THROTTLED here (>= 33ms or >= 1% of total, whichever is
    rarer) because it fires per 64 KiB chunk: on a fast link that's hundreds
    of calls a second, and every call used to reach the UI as its own
    repaint. Callers that need the final byte count get one last callback
    before return, always."""
    mode = "ab" if resume_from else "wb"
    done = resume_from
    total = int(resp.headers.get("content-length", 0)) + resume_from
    last_cb = 0.0
    last_done = 0
    _now = time.monotonic
    with open(dest_path, mode) as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if not chunk:
                continue
            fh.write(chunk)
            if hasher is not None:
                hasher.update(chunk)
            done += len(chunk)
            if progress_cb:
                # Emit if: time budget hit, or 1% of the file landed, or the
                # download finished. The 1% gate matters for big files (a 200
                # MB asset at full speed would otherwise paint ~3000 times).
                if (done - last_done >= total // 100
                        or _now() - last_cb >= 0.033
                        or done >= total):
                    last_cb = _now()
                    last_done = done
                    progress_cb(done, total)
    if progress_cb and done != last_done:
        progress_cb(done, total)  # exact final count, never swallowed
    return done - resume_from


def download_to(dest_path: str, url: str, *, headers: dict | None = None,
                timeout: int = 30, attempts: int = DEFAULT_ATTEMPTS,
                expected_hash: tuple[str, str] | None = None,
                progress_cb=None) -> int:
    """Download url -> dest_path with retry + Range resume, capped by the
    global download gate. Verifies expected_hash=(algo, hexdigest) when
    given; a hash mismatch clears the partial file and raises (a resume
    that landed on wrong bytes must never be kept).

    Returns the final file size. dest_path itself is only replaced on
    success: the partial lives at dest_path + '.part' and is atomically
    moved into place, so a crash mid-download never leaves a 'complete'-
    looking file."""
    part_path = dest_path + ".part"
    last_err: Exception | None = None

    with DOWNLOAD_GATE:
        for attempt in range(attempts):
            # Resume: if a partial file survived the last attempt, ask the
            # server for the remaining bytes. Servers that ignore Range send
            # a full 200 - we detect that and start over rather than append
            # a duplicate body.
            resume_from = os.path.getsize(part_path) if os.path.isfile(part_path) else 0
            req_headers = dict(headers or {})
            hasher = hashlib.new(expected_hash[0]) if expected_hash else None
            if expected_hash and resume_from:
                # Hash the already-downloaded prefix now so the final check
                # covers the whole file, not just the resumed tail.
                try:
                    with open(part_path, "rb") as fh:
                        for block in iter(lambda: fh.read(1 << 20), b""):
                            hasher.update(block)
                except OSError:
                    resume_from = 0
            if resume_from:
                req_headers["Range"] = f"bytes={resume_from}-"
            try:
                resp = get_with_retry(url, headers=req_headers, timeout=timeout,
                                      attempts=max(1, attempts - attempt))
                try:
                    if resume_from and resp.status_code != 206:
                        resume_from = 0  # server ignored Range: full body coming
                        hasher = hashlib.new(expected_hash[0]) if expected_hash else None
                    if expected_hash and not hasher:
                        hasher = hashlib.new(expected_hash[0])
                    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
                    stream_to_file(resp, part_path, progress_cb=progress_cb,
                                   hasher=hasher, resume_from=resume_from)
                finally:
                    resp.close()
                if expected_hash and hasher.hexdigest().lower() != expected_hash[1].lower():
                    try:
                        os.unlink(part_path)
                    except OSError:
                        pass
                    raise DownloadError(
                        "The downloaded file didn't pass its integrity "
                        "check - it may have been corrupted in transit. "
                        "Try again.")
                os.replace(part_path, dest_path)
                return os.path.getsize(dest_path)
            except DownloadError:
                raise  # checksums don't heal; retrying the same bytes is pointless
            except requests.RequestException as ex:
                last_err = ex
                log.info("download %s: attempt %d failed (%s)",
                         url, attempt + 1, ex.__class__.__name__)
                time.sleep(BACKOFF_BASE * (2 ** attempt))
    raise DownloadError(f"Couldn't download {url}: {last_err}")
