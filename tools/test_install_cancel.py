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


class _CancelProbe:
    """Signal from another thread once the stream is already writing bytes."""

    def __init__(self):
        self.event = threading.Event()
        self.signalled_at = None
        self._thread = None

    def arm(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._signal, daemon=True)
            self._thread.start()

    def _signal(self):
        self.signalled_at = time.monotonic()
        self.event.set()

    def elapsed(self, finished_at):
        if self._thread is not None:
            self._thread.join(timeout=1)
        return (finished_at - self.signalled_at
                if self.signalled_at is not None else None)


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

    def __init__(self, chunks=100, delay=0.05, cancel_probe=None):
        self._left = chunks
        self._delay = delay
        self._cancel_probe = cancel_probe
        self.reads = 0
        self.eof = False
        self.raw = types.SimpleNamespace(decode_content=False, read=self._read)
        self.closed = False

    def _read(self, n):
        if self._left <= 0:
            self.eof = True
            return b""
        self._left -= 1
        self.reads += 1
        # Two chunks are already on disk; cancel while the next read is in
        # flight. Only the production downloader checks the resulting flag.
        if self.reads == 3 and self._cancel_probe is not None:
            self._cancel_probe.arm()
        time.sleep(self._delay)  # 5s if a cancel never lands
        return b"x" * n

    def close(self):
        self.closed = True


class _FakeTransport:
    """Stands in for versions._install_session() - no socket, no DNS."""

    def __init__(self, chunks=100, cancel_probe=None):
        self.requests = 0
        self.responses = []
        self._chunks = chunks
        self._cancel_probe = cancel_probe

    def get(self, url, stream=True, timeout=None, headers=None):
        self.requests += 1
        body = _SlowBody(chunks=self._chunks, cancel_probe=self._cancel_probe)
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
        "http://x", os.path.join(mcdir, "versions", version,
                                  _fake_target["name"]), callback or {})


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
    probe = _CancelProbe()
    transport = _FakeTransport(cancel_probe=probe)
    V._install_session = lambda: transport
    raised = None
    try:
        # Java verification has its own cancellation coverage. This probe
        # begins at the download rather than a real local Java subprocess.
        V.install_version("1.20.1", lambda v: None, lambda s: None,
                          lambda m: None, cancel_event=probe.event,
                          explicit_java=True)
    except RuntimeError as ex:
        raised = ex
    dt = probe.elapsed(time.monotonic())
    check("cancel aborts mid-file within 1s of the actual flag",
          raised is not None and "cancelled" in str(raised)
          and dt is not None and 0 <= dt < 1,
          f"cancel-to-abort={dt!r}s raised={raised!r}")
    check("cancel reaches an active response without waiting for EOF",
          transport.requests == 1 and len(transport.responses) == 1
          and 3 <= transport.responses[0].reads < 100
          and transport.responses[0].closed and not transport.responses[0].eof)
    check("mll's download_file is restored after the install",
          _fake_install_mod.download_file is _fake_download_file)
    jar_path = os.path.join(V.version_folder("1.20.1"), "a.jar")
    check("a cancelled install leaves no half-written jar in the version",
          not os.path.isfile(jar_path) and not os.path.isfile(jar_path + ".part"))

    # The same downloader must be in place WITHOUT a cancel_event: the
    # timeouts, retries and resume are what make downloads work on a flaky
    # network, and they used to be installed only for a cancellable install.
    _fake_target["name"] = "b.jar"
    transport2 = _FakeTransport(chunks=3)
    V._install_session = lambda: transport2
    raised_missing = None
    try:
        V.install_version("1.20.1", lambda v: None, lambda s: None,
                          lambda m: None, explicit_java=True)
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
        for chunk in range(100):
            if chunk == 2:
                seed_probe.arm()
            time.sleep(0.05)  # 5s if a cancel never lands
            fh.write(b"x")
            seed_chunks.append(fh.tell())
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
    seed_probe = _CancelProbe()
    seed_chunks = []
    raised2 = None
    try:
        V.install_version("1.20.1", lambda v: None, lambda s: None,
                          lambda m: None, cancel_event=seed_probe.event,
                          explicit_java=True)
    except RuntimeError as ex:
        raised2 = ex
    dt2 = seed_probe.elapsed(time.monotonic())
    check("cancel during the json seed aborts within 1s of the actual flag",
          raised2 is not None and "cancelled" in str(raised2)
          and dt2 is not None and 0 <= dt2 < 1,
          f"cancel-to-abort={dt2!r}s raised={raised2!r}")
    check("seed cancellation happens after bytes arrive and before EOF",
          3 <= len(seed_chunks) < 100)
    _json_path = os.path.join(V.version_folder("1.20.1"), "1.20.1.json")
    check("the abandoned seed leaves no .part behind",
          not os.path.isfile(_json_path + ".part"))
    check("the abandoned seed leaves no half-written version json",
          not os.path.isfile(_json_path))
finally:
    V._manifest = _real_manifest2
    net_mod.download_to = _real_download_to

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
