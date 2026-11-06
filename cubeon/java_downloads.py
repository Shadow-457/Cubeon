"""Choose a verified JRE route using transfer samples from this connection."""
import logging
import hashlib
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urlparse

from . import local_cache, net

log = logging.getLogger(__name__)
AZUL_API = "https://api.azul.com/metadata/v1/zulu/packages"
LOOKUP_TIMEOUT = (3, 5)
SAMPLE_BYTES = 128 * 1024
SAMPLE_SECONDS = 5
RANGE_CHUNK_BYTES = 4 * 1024 * 1024
RANGE_MIN_BYTES = 8 * 1024 * 1024
TRUSTED_HOSTS = {
    "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
    "cdn.azul.com", "mirrors.nju.edu.cn", "mirror.nju.edu.cn",
    "mirrors.tuna.tsinghua.edu.cn",
}


def trusted_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname in TRUSTED_HOSTS
            and parsed.port in (None, 443) and not parsed.username and not parsed.password)


def validate_asset(asset):
    name = asset.get("name") or ""
    digest = asset.get("sha256") or ""
    if not trusted_url(asset.get("link") or "") \
            or not re.fullmatch(r"[a-fA-F0-9]{64}", digest) \
            or name != os.path.basename(name) or "\\" in name \
            or not name.endswith((".zip", ".tar.gz")):
        raise ValueError("Java source did not supply a trusted archive and SHA-256")
    size = int(asset.get("size") or 0)
    if not 0 < size <= 512 * 1024 * 1024:
        raise ValueError("Java source supplied an invalid archive size")
    return dict(asset, sha256=digest.lower(), size=size)


def _azul_asset(major, platform):
    params = dict(java_version=major, os={"mac": "macos"}.get(platform["os"], platform["os"]),
                  arch="arm" if platform["architecture"] == "aarch64" else "x86",
                  hw_bitness=32 if platform["architecture"] == "x86" else 64,
                  archive_type="zip" if platform["os"] == "windows" else "tar.gz",
                  java_package_type="jre", release_status="ga", availability_types="CA",
                  javafx_bundled="false", crac_supported="false", certifications="tck",
                  latest="true", page_size=100)
    rows = net.get_json(AZUL_API + "/", params=params, timeout=LOOKUP_TIMEOUT, attempts=1)
    rows = [row for row in rows if (row.get("java_version") or (None,))[0] == major
            and "-ca-jre" in row.get("name", "") and "musl" not in row.get("name", "")]
    rows.sort(key=lambda row: row.get("java_version") or [], reverse=True)
    if not rows:
        raise ValueError("Azul has no compatible JRE")
    row = rows[0]
    identity = row.get("package_uuid") or ""
    if not re.fullmatch(r"[a-fA-F0-9-]{36}", identity):
        raise ValueError("Azul supplied an invalid package identity")
    detail = net.get_json(AZUL_API + "/" + identity + "/", timeout=LOOKUP_TIMEOUT, attempts=1)
    if detail.get("java_package_type") != "jre" or (detail.get("java_version") or (None,))[0] != major \
            or detail.get("javafx_bundled") or detail.get("crac_supported") \
            or detail.get("crs_supported") or detail.get("os") != params["os"] \
            or detail.get("arch") != params["arch"] or detail.get("hw_bitness") != params["hw_bitness"] \
            or (platform["os"] == "linux" and detail.get("lib_c_type") != "glibc"):
        raise ValueError("Azul package does not match this system")
    return validate_asset(dict(name=detail.get("name"), link=detail.get("download_url"),
                               sha256=detail.get("sha256_hash"), size=detail.get("size"),
                               provider="Azul Zulu CDN"))


def _sample(asset):
    start = time.monotonic()
    count = 0
    prefix = b""
    try:
        response = net.get_with_retry(
            asset["link"], headers={"Range": f"bytes=0-{SAMPLE_BYTES - 1}", "Accept-Encoding": "identity"},
            timeout=(3, 3), attempts=1, url_validator=trusted_url)
        try:
            if response.status_code == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith("bytes 0-"):
                    raise ValueError("Java sample returned an unrelated byte range")
            connected = time.monotonic()
            # Separate connection latency from transfer speed: charging every
            # 128 KiB for the TLS/redirect cost badly overestimates large files.
            # read1 avoids waiting for a full chunk on a trickling connection.
            while count < SAMPLE_BYTES and time.monotonic() - connected < SAMPLE_SECONDS:
                block = response.raw.read1(min(8192, SAMPLE_BYTES - count), decode_content=True)
                if not block:
                    break
                prefix = (prefix + block)[:4]
                count += len(block)
        finally:
            response.close()
        if count and prefix.startswith((b"\x1f\x8b", b"PK\x03\x04")):
            return connected - start + asset["size"] * (time.monotonic() - connected) / count
    except Exception as error:
        log.info("Java route sample failed for %s: %s", asset["provider"], type(error).__name__)
    return None


def _route_key(assets):
    return sorted((a["link"], a["sha256"]) for a in assets)


def candidates(major, platform, adoptium_lookup):
    """Resolve vendors in parallel, then rank routes; no location/IP lookup."""
    def lookup(provider):
        try:
            fetch = adoptium_lookup if provider == "temurin" else lambda: _azul_asset(major, platform)
            asset = local_cache.cached_call(
                "java_assets", dict(major=major, platform=platform, provider=provider),
                lambda: validate_asset(fetch()), max_age=24 * 3600, background_refresh=False)
            return validate_asset(asset)
        except Exception as error:
            log.info("Java metadata unavailable for %s: %s", provider, type(error).__name__)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assets = [asset for asset in pool.map(lookup, ("temurin", "azul")) if asset]
    if not assets:
        raise RuntimeError("No verified Java download is reachable; check the connection and retry")
    temurin = next((a for a in assets if a.get("provider") == "Eclipse Temurin"), None)
    if temurin:
        suffix = f"{major}/jre/{platform['architecture']}/{platform['os']}/{quote(temurin['name'])}"
        for label, base in (("NJU mirror", "https://mirrors.nju.edu.cn/adoptium/"),
                            ("Tsinghua mirror", "https://mirrors.tuna.tsinghua.edu.cn/Adoptium/")):
            assets.append(dict(temurin, link=base + suffix, provider=label))
    if len(assets) == 1:
        return assets
    key = _route_key(assets)
    order = local_cache.get("java_routes", key, max_age=1800)
    if order:
        return sorted(assets, key=lambda a: order.index(a["link"]) if a["link"] in order else len(order))
    with ThreadPoolExecutor(max_workers=min(4, len(assets))) as pool:
        scores = list(pool.map(_sample, assets))
    ranked = sorted(zip(assets, scores), key=lambda pair: pair[1] if pair[1] is not None else float("inf"))
    if any(score is not None for score in scores):
        local_cache.set("java_routes", key, [a["link"] for a, score in ranked])
    # A short probe can time out while a normal download succeeds. Keep those
    # sources as fallbacks, including when the first measured route slows down.
    return [a for a, score in ranked]


class SlowSource(net.DownloadError):
    pass


class RangeUnsupported(net.DownloadError):
    pass


def _range_response(asset, start, end):
    response = net.get_with_retry(
        asset["link"], headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
        timeout=(4, 6), attempts=1, url_validator=trusted_url)
    expected = f"bytes {start}-{end}/{asset['size']}"
    if response.status_code != 206 or response.headers.get("Content-Range") != expected \
            or response.headers.get("Content-Encoding", "identity").lower() != "identity":
        response.close()
        raise RangeUnsupported("Java source does not support verified byte ranges")
    return response


def _download_ranges(archive, asset, progress_cb, deadline, cancel_check=None):
    """Four bounded transfers; only a complete vendor-verified archive is promoted.

    Parts belong to one checksum and absolute byte range. Matching mirrors can
    reuse them; serial fallback still resumes the contiguous .part prefix.
    """
    from urllib3.exceptions import HTTPError
    part = archive + ".part"
    directory = archive + ".parts"
    os.makedirs(directory, exist_ok=True)
    initial = os.path.getsize(part) if os.path.isfile(part) else 0
    if initial > asset["size"]:
        os.remove(part)
        initial = 0
    segments = []
    start = initial
    while start < asset["size"]:
        end = min(asset["size"], (start // RANGE_CHUNK_BYTES + 1) * RANGE_CHUNK_BYTES) - 1
        path = os.path.join(directory, f"{start}-{end}")
        downloaded = os.path.getsize(path) if os.path.isfile(path) else 0
        if downloaded > end - start + 1:
            os.remove(path)
            downloaded = 0
        segments.append((start, end, path, downloaded))
        start = end + 1

    pending = [segment for segment in segments if segment[3] < segment[1] - segment[0] + 1]
    if pending:
        # Check support before opening four requests: some CDNs ignore Range
        # and would otherwise send four complete archives.
        begin, end, _, downloaded = pending[0]
        while True:
            if cancel_check:
                cancel_check()
            if time.monotonic() >= deadline:
                raise net.DownloadError("Java download time limit reached")
            if net.DOWNLOAD_GATE.acquire(timeout=.25):
                break
        try:
            _range_response(asset, begin + downloaded, end).close()
        finally:
            net.DOWNLOAD_GATE.release()

    stopped = threading.Event()
    progress_lock = threading.Lock()
    done = initial + sum(segment[3] for segment in segments)
    last_progress = 0.0
    errors = []

    def progress(count=0, *, final=False):
        nonlocal done, last_progress
        with progress_lock:
            done += count
            now = time.monotonic()
            if progress_cb and (final or now - last_progress >= .05):
                last_progress = now
                progress_cb(done, asset["size"])

    def transfer(segment):
        begin, end, path, downloaded = segment
        acquired = False
        response = None
        try:
            while not acquired:
                if cancel_check:
                    cancel_check()
                if stopped.is_set():
                    return
                if time.monotonic() >= deadline:
                    raise net.DownloadError("Java download time limit reached")
                acquired = net.DOWNLOAD_GATE.acquire(timeout=.25)
            response = _range_response(asset, begin + downloaded, end)
            remaining = end - begin + 1 - downloaded
            with open(path, "ab") as output:
                while remaining:
                    if cancel_check:
                        cancel_check()
                    if stopped.is_set():
                        return
                    if time.monotonic() >= deadline:
                        raise net.DownloadError("Java download time limit reached")
                    block = response.raw.read1(min(65536, remaining), decode_content=False)
                    if not block:
                        raise net.DownloadError("Java source ended an incomplete byte range")
                    if len(block) > remaining:
                        raise net.DownloadError("Java source returned an invalid byte range")
                    output.write(block)
                    remaining -= len(block)
                    progress(len(block))
        except (HTTPError, net.requests.RequestException) as error:
            stopped.set()
            raise net.DownloadError("Couldn't read the Java download") from error
        except Exception:
            stopped.set()
            raise
        finally:
            if response is not None:
                response.close()
            if acquired:
                net.DOWNLOAD_GATE.release()

    progress(final=True)
    with ThreadPoolExecutor(max_workers=net.MAX_CONCURRENT_DOWNLOADS) as pool:
        futures = [pool.submit(transfer, segment) for segment in pending]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                errors.append(error)
                stopped.set()
    if errors:
        # Cancellation/callback failures must not become route retries.
        raise next((error for error in errors if not isinstance(error, net.DownloadError)), errors[0])
    progress(final=True)

    # Keep each segment until its append succeeds. A failed append restores
    # the previous contiguous prefix, which a later retry can safely resume.
    with open(part, "ab") as output:
        for begin, end, path, _ in segments:
            if os.path.getsize(path) != end - begin + 1:
                raise net.DownloadError("Java download has an incomplete byte range")
            try:
                with open(path, "rb") as source:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                output.flush()
            except Exception:
                output.seek(begin)
                output.truncate()
                raise
            os.remove(path)
    digest = hashlib.sha256()
    with open(part, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != asset["sha256"]:
        os.remove(part)
        shutil.rmtree(directory, ignore_errors=True)
        raise net.DownloadError("Java download failed its integrity check; retry the download")
    os.replace(part, archive)
    shutil.rmtree(directory, ignore_errors=True)
    return os.path.getsize(archive)


def download(assets, directory, major, progress_cb=None, status_cb=None, *, cancel_check=None):
    """Retain partial archives by hash; switching vendors never mixes bytes."""
    os.makedirs(directory, exist_ok=True)
    errors = []
    speeds = {}
    if not assets:
        raise RuntimeError("No verified Java download route is available")
    # Try every source, then resume the best measured transfer rather than
    # repeating an unreachable mirror merely because it was last in the list.
    routes = list(assets) + [assets[0]]
    for index, asset in enumerate(routes):
        if cancel_check:
            cancel_check()
        if index == len(assets):
            asset = max(assets, key=lambda a: speeds.get(a["link"], 0))
        archive = os.path.join(directory, asset["sha256"] + "-" + asset["name"])
        if os.path.isfile(archive):
            from .global_mod_cache import _matches_hashes
            if _matches_hashes(archive, {"sha256": asset["sha256"]}):
                return archive
            os.remove(archive)
        if status_cb:
            status_cb(f"Downloading Java {major} ({asset['size'] // (1024 * 1024)} MB) · {asset['provider']}")
        started = time.monotonic()
        partial = archive + ".part"
        initial = os.path.getsize(partial) if os.path.isfile(partial) else 0
        range_initial = {"pending": False}

        def progress(done, total):
            nonlocal initial
            if range_initial["pending"]:
                initial = done  # Include cached segments, without charging them as new traffic.
                range_initial["pending"] = False
            if done < initial:
                initial = 0  # This route ignored Range and restarted the archive.
            if progress_cb:
                progress_cb(done, total or asset["size"])
            elapsed = time.monotonic() - started
            rate = max(0, done - initial) / max(elapsed, .001)
            if elapsed >= 2 and done > initial:
                speeds[asset["link"]] = rate
            if index < len(assets) - 1 and elapsed >= 12 and done < asset["size"] \
                    and (asset["size"] - done) / max(rate, 1) > 120:
                raise SlowSource("Java source became too slow")

        try:
            deadline = time.monotonic() + 1800
            ranged = False
            if asset["size"] >= RANGE_MIN_BYTES:
                try:
                    range_initial["pending"] = True
                    _download_ranges(archive, asset, progress, deadline, cancel_check)
                    ranged = True
                except RangeUnsupported:
                    range_initial["pending"] = False
            if not ranged:
                net.download_to(archive, asset["link"], timeout=(4, 6), attempts=1,
                                headers={"Accept-Encoding": "identity"},
                                expected_hash=("sha256", asset["sha256"]), progress_cb=progress,
                                deadline=deadline, url_validator=trusted_url,
                                cancel_check=cancel_check)
                shutil.rmtree(archive + ".parts", ignore_errors=True)
            # Remember the source that actually completed, so later installs
            # do not repeat a misleading sample or a blocked first choice.
            local_cache.set("java_routes", _route_key(assets),
                            [asset["link"]] + [a["link"] for a in assets if a["link"] != asset["link"]])
            return archive
        except net.DownloadError as error:
            errors.append(f"{asset['provider']}: {error}")
            log.info("Java route failed: %s", errors[-1])
            if index < len(routes) - 1 and status_cb:
                status_cb(f"Trying another Java {major} download route")
    raise RuntimeError("Java download routes failed. Partial downloads are kept for retry. " + "; ".join(errors))
