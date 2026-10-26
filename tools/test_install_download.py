"""The install downloader: retries, resume, checksums and a hard failure.

The 2026-10-17 report: "download on instances isn't working on some users".
mll's own downloader has no timeout, no retry, no resume and no integrity
check on a body that stopped early, and it reports a bad status by RETURNING
False - which every one of its callers ignores. So a CDN that rate-limited a
burst of asset requests (429), or a proxy that dropped a connection mid-jar,
produced an install that "completed" with holes in it and nothing in the UI to
say which file was missing.

Locked-in behaviors of versions._make_resilient_download_file():
  1. a transient failure (429/5xx, a dropped connection) is retried and the
     file still arrives, honouring Retry-After
  2. a retry RESUMES: the bytes already on disk are requested with a Range
     header and a 206 continues the file instead of starting it over
  3. a body that fails its sha1 is thrown away and fetched whole again
  4. a permanent answer (404) raises a message naming the file - never a
     silent skip that leaves an install the launcher calls complete
  5. a file that is already correct is not fetched again, and one that changed
     on disk is not trusted either
  6. install_minecraft_version runs once per version per install (a loader
     install used to walk the whole base version two or three times)
  7. install_jvm_runtime is skipped only when the caller passes explicit_java
  8. the patch reaches every mll module that imports the name itself
"""
import hashlib
import os
import sys
import tempfile
import types
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_home = tempfile.mkdtemp(prefix="cubeon-download-test-")
os.environ["HOME"] = _home
os.environ["USERPROFILE"] = _home
os.environ["CUBEON_GAME_DIR"] = os.path.join(_home, "game")

from cubeon import versions as V  # noqa: E402  (after the env isolation)

passed = failed = 0


def check(label, ok, extra=""):
    global passed, failed
    passed += ok
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not ok else ''}")


# The retry backoff is a real 1.5s/3s so a slow link is not thrashed; the
# tests only care THAT a retry happened, so shrink it instead of sleeping.
V._DOWNLOAD_BACKOFF = 0.01
_real_session = V._install_session
_tmp = tempfile.mkdtemp(prefix="cubeon-download-files-")
URL = "https://example.invalid/f.jar"


def _path(name):
    return os.path.join(_tmp, name)


class Body:
    """A response-shaped body, streamed in small chunks like a real socket."""

    def __init__(self, status=200, payload=b"", headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = [payload[i:i + 8] for i in range(0, len(payload), 8)]
        self.raw = types.SimpleNamespace(decode_content=False, read=self._read)
        self.closed = False

    def _read(self, n):
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        self.closed = True


class DyingBody(Body):
    """A body that dies mid-transfer, like a proxy dropping the connection."""

    def _read(self, n):
        if not self._chunks:
            raise ConnectionError("connection dropped mid-body")
        return self._chunks.pop(0)


class Transport:
    """Stands in for versions._install_session(). No socket, no DNS."""

    def __init__(self, script):
        self.script = list(script)  # bodies (or exceptions) in call order
        self.requests = []          # (url, headers) per call

    def get(self, url, stream=True, timeout=None, headers=None):
        self.requests.append((url, dict(headers or {})))
        item = self.script.pop(0) if self.script else Body()
        if isinstance(item, Exception):
            raise item
        return item


def _downloader(transport):
    V._install_session = lambda: transport
    return V._make_resilient_download_file()


try:
    # -----------------------------------------------------------------------
    print("\n1. a transient failure is retried, and the file still arrives")
    # -----------------------------------------------------------------------
    payload = b"a-whole-library-jar" * 40
    sha1 = hashlib.sha1(payload).hexdigest()
    path = _path("f.jar")
    transport = Transport([Body(503), Body(429, headers={"Retry-After": "0"}),
                           Body(200, payload)])
    ok = _downloader(transport)(URL, path, sha1=sha1)
    check("the download succeeds after a 503 and a 429", ok is True,
          f"ok={ok!r}")
    check("it took exactly three requests", len(transport.requests) == 3,
          f"n={len(transport.requests)}")
    with open(path, "rb") as fh:
        check("the whole body landed on disk", fh.read() == payload)

    # -----------------------------------------------------------------------
    print("\n2. a retry resumes instead of starting the file over")
    # -----------------------------------------------------------------------
    payload = b"abcdefgh" * 200
    sha1 = hashlib.sha1(payload).hexdigest()
    path = _path("resume.jar")
    transport = Transport([DyingBody(payload=payload[:400]),
                           Body(206, payload[400:], headers={
                               "Content-Range": f"bytes 400-{len(payload)-1}/{len(payload)}",
                               "Content-Length": str(len(payload)-400)})])
    ok = _downloader(transport)(URL, path, sha1=sha1)
    check("the resumed download completes", ok is True, f"ok={ok!r}")
    resumed = transport.requests[1][1]
    check("the retry asked for the rest of the file, not all of it",
          resumed.get("Range") == "bytes=400-", f"headers={resumed}")
    with open(path, "rb") as fh:
        check("the resumed file is byte-identical", fh.read() == payload)

    # -----------------------------------------------------------------------
    print("\n3. a body that fails its checksum is fetched again from scratch")
    # -----------------------------------------------------------------------
    good = b"the-real-jar" * 60
    sha1 = hashlib.sha1(good).hexdigest()
    path = _path("checksum.jar")
    transport = Transport([Body(200, b"corrupt!" * 60), Body(200, good)])
    ok = _downloader(transport)(URL, path, sha1=sha1)
    check("the good body is accepted", ok is True, f"ok={ok!r}")
    check("the corrupt attempt was discarded, not appended to",
          "Range" not in transport.requests[1][1],
          f"headers={transport.requests[1][1]}")
    with open(path, "rb") as fh:
        check("the file on disk is the good body", fh.read() == good)

    print("\n3c. an interrupted checksum-free file is never published")
    path = _path("no-checksum.bin")
    transport = Transport([DyingBody(payload=b"partial!"), Body(404)])
    try:
        _downloader(transport)(URL, path)
    except V._MllDownloadError:
        pass
    check("partial bytes stay outside the final filename",
          not os.path.exists(path) and os.path.exists(path + ".part"))
    good = b"partial!complete"
    transport = Transport([Body(206, good[8:], headers={
        "Content-Range": f"bytes 8-{len(good)-1}/{len(good)}",
        "Content-Length": str(len(good)-8)})])
    check("retry without a checksum still fetches the missing bytes",
          _downloader(transport)(URL, path) is True)
    check("the completed file replaces its staging file",
          open(path, "rb").read() == good and not os.path.exists(path + ".part"))

    print("\n3d. a failed overwrite preserves the previous working file")
    path = _path("working.jar")
    with open(path, "wb") as fh:
        fh.write(b"working")
    transport = Transport([DyingBody(payload=b"broken!!"), Body(404)])
    try:
        _downloader(transport)(URL, path, overwrite=True)
    except V._MllDownloadError:
        pass
    check("the old file survives the failed replacement",
          open(path, "rb").read() == b"working")

    print("\n3e. wrong ranges and short responses are rejected")
    path = _path("wrong-range.jar")
    transport = Transport([DyingBody(payload=b"abcdefgh"),
                           Body(206, b"wrong", headers={"Content-Range": "bytes 0-4/5"}),
                           Body(200, b"correct")])
    check("a mismatched range restarts the file safely",
          _downloader(transport)(URL, path) is True
          and open(path, "rb").read() == b"correct"
          and "Range" not in transport.requests[-1][1])
    path = _path("short.bin")
    transport = Transport([Body(200, b"short", headers={"Content-Length": "20"}),
                           Body(404)])
    raised = None
    try:
        _downloader(transport)(URL, path)
    except V._MllDownloadError as ex:
        raised = ex
    check("a short checksum-free body never becomes a complete file",
          raised is not None and not os.path.exists(path))

    # -----------------------------------------------------------------------
    print("\n3b. a stale partial file the server refuses restarts cleanly")
    # -----------------------------------------------------------------------
    good = b"replacement-jar" * 40
    sha1 = hashlib.sha1(good).hexdigest()
    path = _path("stale.jar")
    with open(path + ".part", "wb") as fh:
        fh.write(b"x" * (len(good) + 512))  # longer than the real body
    transport = Transport([Body(416), Body(200, good)])
    ok = _downloader(transport)(URL, path, sha1=sha1)
    check("the install recovers instead of failing on it", ok is True,
          f"ok={ok!r}")
    check("the stale bytes are dropped before refetching",
          "Range" not in transport.requests[1][1],
          f"headers={transport.requests[1][1]}")
    with open(path, "rb") as fh:
        check("the file on disk is the good body", fh.read() == good)

    # -----------------------------------------------------------------------
    print("\n4. a permanent 404 names the file instead of failing silently")
    # -----------------------------------------------------------------------
    transport = Transport([Body(404)])
    raised = None
    try:
        _downloader(transport)(URL, _path("gone.jar"))
    except V._MllDownloadError as ex:
        raised = ex
    check("a 404 raises for the user to read", raised is not None,
          f"raised={raised!r}")
    check("the message names the file and the status",
          raised is not None and "gone.jar" in str(raised)
          and "404" in str(raised), f"message={raised}")
    check("and it is not retried, because the answer will not change",
          len(transport.requests) == 1, f"n={len(transport.requests)}")

    # -----------------------------------------------------------------------
    print("\n5. a verified file is not fetched again, but tampering is caught")
    # -----------------------------------------------------------------------
    payload = b"already-here" * 50
    sha1 = hashlib.sha1(payload).hexdigest()
    path = _path("verified.jar")
    transport = Transport([Body(200, payload)])
    downloader = _downloader(transport)
    check("the first fetch happens", downloader(URL, path, sha1=sha1) is True)
    check("and it is remembered as verified", str(path) in V._VERIFIED_FILES)
    check("a second call is an immediate no-op",
          downloader(URL, path, sha1=sha1) is False
          and len(transport.requests) == 1,
          f"n={len(transport.requests)}")
    with open(path, "ab") as fh:
        fh.write(b"tampered")
    transport2 = Transport([Body(200, payload)])
    check("a file that changed on disk is fetched again",
          _downloader(transport2)(URL, path, sha1=sha1) is True
          and len(transport2.requests) == 1,
          f"n={len(transport2.requests)}")
    replacement = b"different-checksum" * 30
    replacement_sha = hashlib.sha1(replacement).hexdigest()
    transport = Transport([Body(200, replacement)])
    check("a cached checksum cannot vouch for a different requested checksum",
          _downloader(transport)(URL, path, sha1=replacement_sha) is True
          and open(path, "rb").read() == replacement)

    print("\n5b. cancellation interrupts server retry waits")
    event = threading.Event()
    bridge = V._InstallCancelBridge(event)
    bridge.note_thread()
    transport = Transport([Body(429, headers={"Retry-After": "10"})])
    timer = threading.Timer(0.15, event.set)
    with V._PatchedMllDownloads(bridge):
        timer.start()
        started = time.monotonic()
        cancelled = False
        try:
            _downloader(transport)(URL, _path("backoff.jar"))
        except V._DownloadCancelled:
            cancelled = True
        check("cancel stops a ten-second Retry-After wait within one second",
              cancelled and time.monotonic() - started < 1)
    timer.join()

    # -----------------------------------------------------------------------
    print("\n6. one install installs each version once")
    # -----------------------------------------------------------------------
    calls = []
    real_mll = V.mll

    def _install_minecraft_version(version, mcdir, callback=None):
        calls.append(version)

    fake = types.SimpleNamespace(install=types.SimpleNamespace(
        download_file=lambda *a, **k: None,
        install_minecraft_version=_install_minecraft_version,
        install_jvm_runtime=lambda *a, **k: calls.append("jvm")))
    V.mll = fake
    try:
        with V._PatchedMllDownloads():
            fake.install.install_minecraft_version("1.20.1", "x")
            fake.install.install_minecraft_version("1.20.1", "x")
            fake.install.install_minecraft_version("fabric-1.20.1", "x")
            seen = list(calls)
        restored = fake.install.install_minecraft_version \
            is _install_minecraft_version
    finally:
        V.mll = real_mll
    check("a repeat of a finished version is skipped, a new one is not",
          seen == ["1.20.1", "fabric-1.20.1"], f"calls={seen}")
    check("the original is put back on exit", restored)

    # -----------------------------------------------------------------------
    print("\n7. mll's own Java runtime is skipped only when Java is explicit")
    # -----------------------------------------------------------------------
    results = {}
    for explicit in (False, True):
        calls = []
        fake = types.SimpleNamespace(install=types.SimpleNamespace(
            download_file=lambda *a, **k: None,
            install_minecraft_version=_install_minecraft_version,
            install_jvm_runtime=lambda *a, **k: calls.append("jvm")))
        V.mll = fake
        try:
            with V._PatchedMllDownloads(explicit_java=explicit):
                fake.install.install_jvm_runtime("java-runtime-delta", "x")
        finally:
            V.mll = real_mll
        results[explicit] = len(calls)
    check("without explicit_java mll still installs its runtime",
          results[False] == 1, f"calls={results}")
    check("with explicit_java the second JDK is skipped",
          results[True] == 0, f"calls={results}")

    # -----------------------------------------------------------------------
    print("\n8. the patch reaches every mll module that imports the name")
    # -----------------------------------------------------------------------
    originals = {}
    for name in ("install", "fabric", "forge", "quilt", "mrpack", "runtime"):
        mod = getattr(real_mll, name, None)
        if mod is not None and hasattr(mod, "download_file"):
            originals[name] = mod.download_file
    with V._PatchedMllDownloads():
        patched = {name: getattr(real_mll, name).download_file
                   for name in originals}
    check("at least four modules are covered", len(originals) >= 4,
          f"modules={sorted(originals)}")
    check("all of them got the one resilient downloader",
          bool(patched) and len(set(map(id, patched.values()))) == 1,
          f"distinct={len(set(map(id, patched.values())))}")
    check("and every one was put back on exit",
          all(getattr(real_mll, n).download_file is originals[n]
              for n in originals))
finally:
    V._install_session = _real_session

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
