"""Tests for the production-pass modules: cubeon/watchdog.py (orphaned-game
tracking) and cubeon/crashreport.py (opt-in reporting). Hermetic: network
calls are faked, the watchdog uses a real short-lived subprocess."""
import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import crashreport, watchdog  # noqa: E402

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


# --------------------------------------------------------------- watchdog ---
watchdog.clear()
check(watchdog.stale_session() is None, "no record -> no stale session")

# A live process (python sleeping) counts as a stale leftover.
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
watchdog.register(p.pid, "1.20.1")
stale = watchdog.stale_session()
check(stale is not None and stale["pid"] == p.pid and stale["version"] == "1.20.1",
      "live recorded pid is reported as a stale session")

# Terminate ends it and the record can be cleared.
check(watchdog.terminate(p.pid) in (True, False), "terminate returns a bool")
p.wait(timeout=5)
watchdog.clear()

# A dead pid is cleaned up silently, not reported.
p2 = subprocess.Popen([sys.executable, "-c", "pass"])
p2.wait(timeout=5)
watchdog.register(p2.pid, "1.20.1")
check(watchdog.stale_session() is None, "dead pid is not a stale session")
check(not os.path.exists(watchdog.RECORD_PATH), "dead-pid record is cleaned up")

# Corrupt record never raises.
with open(watchdog.RECORD_PATH, "w") as fh:
    fh.write("{not json")
check(watchdog.stale_session() is None, "corrupt record is ignored, not fatal")

# ----------------------------------------------------------- crashreport ---
check(crashreport.endpoint({}) is None, "crash reporting OFF without opt-in")
check(crashreport.endpoint({"crash_reports": True}) is None,
      "opt-in without an endpoint is still OFF (nowhere to send)")
check(crashreport.endpoint({"crash_reports": True,
                            "crash_endpoint": "https://x"}) == "https://x",
      "opt-in + endpoint = enabled")
os.environ["CUBEON_CRASH_ENDPOINT"] = "https://env-endpoint"
check(crashreport.endpoint({"crash_reports": True}) == "https://env-endpoint",
      "env endpoint wins over config")
del os.environ["CUBEON_CRASH_ENDPOINT"]

posted = []


def fake_post(url, **kwargs):
    posted.append((url, kwargs.get("data")))
    class R:
        status_code = 200
    return R()


real_post = crashreport.requests.post
try:
    crashreport.requests.post = fake_post
    crashreport.report({"crash_reports": True,
                        "crash_endpoint": "https://x"}, "TRACEBACK TEXT")
    deadline = time.time() + 2
    while not posted and time.time() < deadline:
        time.sleep(0.01)
    check(len(posted) == 1 and posted[0][0] == "https://x"
          and b"TRACEBACK TEXT" in posted[0][1],
          "enabled crash report is POSTed with the diagnostics payload")

    posted.clear()
    crashreport.report({}, "SHOULD NOT SEND")
    time.sleep(0.05)
    check(not posted, "opted-out crash report is never sent")

    # A failing endpoint must not raise out of report().
    def boom(*a, **k):
        raise RuntimeError("network down")
    crashreport.requests.post = boom
    crashreport.report({"crash_reports": True,
                        "crash_endpoint": "https://x"}, "text")
    time.sleep(0.05)
    check(True, "failed delivery never raises")
finally:
    crashreport.requests.post = real_post

print(f"{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
