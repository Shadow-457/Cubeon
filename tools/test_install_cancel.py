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
  4. without cancel_event, the install path is untouched (bridge is None)
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


# A fake mll whose download_file sleeps in small chunks - the shape of a big
# body copy. It must resolve download_file through the MODULE GLOBAL (like
# the real minecraft_launcher_lib.install does via `from ._helper import
# download_file`), or the probe would bypass the patch and prove nothing.
def _fake_download_file(url, path, callback={}, **k):
    for _ in range(100):
        time.sleep(0.05)  # 5s if a cancel never lands
        callback.get("setStatus", lambda *_: None)("x")


_fake_install_mod = types.SimpleNamespace(download_file=_fake_download_file)


def _fake_install(version, mcdir, callback=None):
    _fake_install_mod.download_file("http://x", os.path.join(mcdir, "a.jar"),
                                    callback or {})


_fake_install_mod.install_minecraft_version = _fake_install
_real_mll = V.mll
V.mll = types.SimpleNamespace(install=_fake_install_mod)

try:
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
finally:
    V.mll = _real_mll

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
