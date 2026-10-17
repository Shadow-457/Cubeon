"""Mid-download install cancellation - the 2026-10-15 report: "the cancel
button stops like after 5 min".

mll 8.0 downloads every file with requests but NO timeout and copies the
body with shutil.copyfileobj; its progress callbacks only fire at file
boundaries. So a cancel was only honored at the next file boundary, and one
big file (client jar, Java runtime, asset index) or a stalled connection
could hold a cancelled install for minutes.

Locked-in behaviors (versions.install_version with cancel_event):
  1. a cancel lands MID-FILE within ~a second, not at the file boundary
  2. the abort surfaces as a RuntimeError (install_version's generic wrap;
     callers decide "cancelled vs failed" from the event, never the type)
  3. mll's download_file module global is RESTORED after the install -
     an unpatched mll would poison every later install in the process
  4. the resilient downloader (timeouts, retries, resume, checksum) is
     installed with or without a cancel_event - not a cancel-only feature
"""
import os
import sys
import tempfile
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_home = tempfile.mkdtemp(prefix="cubeon-cancel-test-")
os.environ["HOME"] = _home
os.environ["USERPROFILE"] = _home
os.environ["CUBEON_GAME_DIR"] = os.path.join(_home, "game")

from cubeon import versions as V  # noqa: E402  (after the env isolation)

passed = failed = 0


def check(label, ok, extra=""):
    global passed, failed
    passed += ok
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' - ' + extra) if extra and not ok else ''}")


# A fake transport: response-shaped objects whose bodies arrive slowly, in
# chunks, streamed by the patched downloader exactly like a real socket - so
# what aborts the install is the downloader's own per-chunk cancel check. (It
# used to point the installer at "http://x" and rely on the connection failing
# within milliseconds, which proved nothing about cancelling - and, since the
# retry work made a dropped connection retry instead of abort, would now just
# sleep through the backoff.)
class _SlowBody:
    status_code = 200
    headers = {}

    def __init__(self, chunks=100, delay=0.05):
        self._left = chunks
        self._delay = delay
        self.raw = types.SimpleNamespace(decode_content=False, read=self._read)
        self.closed = False

    def _read(self, n):
        if self._left <= 0:
            return b""
        self._left -= 1
        time.sleep(self._delay)  # 5s if a cancel never lands
        return b"x" * n

    def close(self):
        self.closed = True


class _FakeTransport:
    """Stands in for versions._install_session() - no socket, no DNS."""

    def __init__(self, chunks=100):
        self.requests = 0
        self.responses = []
        self._chunks = chunks

    def get(self, url, stream=True, timeout=None, headers=None):
        self.requests += 1
        body = _SlowBody(chunks=self._chunks)
        self.responses.append(body)
        return body


# A fake mll whose install resolves download_file through the MODULE GLOBAL
# (like the real minecraft_launcher_lib.install does via
# `from ._helper import download_file`), or the probe would bypass the patch
# and prove nothing.
def _fake_download_file(url, path, callback=None, **k):
    if callback is None:
        callback = {}
    for _ in range(100):
        time.sleep(0.05)  # 5s if a cancel never lands
        callback.get("setStatus", lambda *_: None)("x")


_fake_target = {"name": "a.jar"}
_fake_install_mod = types.SimpleNamespace(download_file=_fake_download_file)


def _fake_install(version, mcdir, callback=None):
    _fake_install_mod.download_file(
        "http://x", os.path.join(mcdir, _fake_target["name"]), callback or {})


_fake_install_mod.install_minecraft_version = _fake_install
_real_mll = V.mll
_real_session = V._install_session
V.mll = types.SimpleNamespace(install=_fake_install_mod)
# install_version now seeds versions/<id>/<id>.json from Cubeon's cached
# manifest before mll runs (see test_install_prepare.py) - that lookup is a
# real, cached, network-capable call and has no business in a timing test.
# An empty manifest makes the seed a no-op: "not ours to guess", mll's job.
_real_manifest = V._manifest
V._manifest = lambda: {"versions": []}

try:
    transport = _FakeTransport()
    V._install_session = lambda: transport
    ev = threading.Event()
    threading.Timer(0.6, ev.set).start()
    t0 = time.time()
    raised = None
    try:
        V.install_version("1.20.1", lambda v: None, lambda s: None,
                          lambda m: None, cancel_event=ev)
    except RuntimeError as ex:
        raised = ex
    dt = time.time() - t0
    check("cancel aborts mid-file within ~1s of the flag",
          raised is not None and dt < 1.6, f"dt={dt:.2f}s raised={raised!r}")
    check("mll's download_file is restored after the install",
          _fake_install_mod.download_file is _fake_download_file)
    check("a cancelled install leaves no half-written jar in the version",
          not os.path.isfile(os.path.join(V.MINECRAFT_DIR, "versions",
                                          "1.20.1", "a.jar")))

    # The same downloader must be in place WITHOUT a cancel_event: the
    # timeouts, retries and resume are what make downloads work on a flaky
    # network, and they used to be installed only for a cancellable install.
    _fake_target["name"] = "b.jar"
    transport2 = _FakeTransport(chunks=3)
    V._install_session = lambda: transport2
    raised_missing = None
    try:
        V.install_version("1.20.1", lambda v: None, lambda s: None,
                          lambda m: None)
    except RuntimeError as ex:
        raised_missing = ex
    check("the resilient downloader runs without a cancel_event too",
          transport2.requests == 1, f"requests={transport2.requests}")
    check("and that install still ends instead of hanging",
          raised_missing is not None, f"raised={raised_missing!r}")
finally:
    V.mll = _real_mll
    V._manifest = _real_manifest
    V._install_session = _real_session

# ---------------------------------------------------------------------------
print("\n2. a cancel during the version-json seed aborts just as fast")
# ---------------------------------------------------------------------------
from cubeon import net as net_mod  # noqa: E402


def _slow_download(dest_path, url, **kw):
    """Stands in for net.download_to with the shape of a real fetch: bytes in
    chunks, progress reported as it goes - so what aborts it is the seed's own
    per-chunk cancel check, not the fake simply returning."""
    with open(dest_path + ".part", "wb") as fh:
        for _ in range(100):
            time.sleep(0.05)  # 5s if a cancel never lands
            fh.write(b"x")
            cb = kw.get("progress_cb")
            if cb:
                cb(fh.tell(), 100)
    return 100


_real_manifest2 = V._manifest
_real_download_to = net_mod.download_to
# A manifest entry makes the seed actually fetch (an empty one short-circuits).
V._manifest = lambda: {"versions": [{"id": "1.20.1", "url": "http://x/v.json",
                                     "sha1": "0" * 40}]}
net_mod.download_to = _slow_download
try:
    ev2 = threading.Event()
    threading.Timer(0.6, ev2.set).start()
    t0 = time.time()
    raised2 = None
    try:
        V.install_version("1.20.1", lambda v: None, lambda s: None,
                          lambda m: None, cancel_event=ev2)
    except RuntimeError as ex:
        raised2 = ex
    dt2 = time.time() - t0
    check("cancel during the json seed aborts within ~1s",
          raised2 is not None and dt2 < 1.6,
          f"dt={dt2:.2f}s raised={raised2!r}")
    _json_path = os.path.join(V.MINECRAFT_DIR, "versions", "1.20.1",
                              "1.20.1.json")
    check("the abandoned seed leaves no .part behind",
          not os.path.isfile(_json_path + ".part"))
    check("the abandoned seed leaves no half-written version json",
          not os.path.isfile(_json_path))
finally:
    V._manifest = _real_manifest2
    net_mod.download_to = _real_download_to

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
