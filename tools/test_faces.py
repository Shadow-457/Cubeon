"""Guard for the Cubeon face-avatar pipeline (cubeon/faces.py).

The bug this locks down: no profile picture showed in chat - not on friend
rows, not on the ID card, not on your own card - because the launcher never
consumed the skins Worker's /faces/<name>.png endpoint and its self-avatar
fallback (crafatar) only resolves Mojang accounts, 404ing for Cubeon's
offline/cracked users. The chat tab now paints cubeon.faces bytes over the
color-initial chips, and the self fallback uses the Cubeon endpoint.

Runs headless (no flet, no network) like the rest of tools/.
"""
import base64
import os
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Isolate the face cache BEFORE cubeon imports compute CUBEON_HOME from
# Path.home() - the same pattern test_skins_net.py uses. Never touches the
# real ~/.cubeon_launcher.
_tmp = tempfile.mkdtemp(prefix="cubeon-faces-test-")
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp  # Windows equivalent, for Path.home()

from cubeon import faces  # noqa: E402

_CHECKS = []


def check(label, ok, detail=""):
    _CHECKS.append(bool(ok))
    print(f"  {'ok ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))


def main():
    print("faces module")
    faces_dir = faces.FACE_DIR
    os.makedirs(faces_dir, exist_ok=True)

    # --- url(): validation + endpoint shape -----------------------------
    u = faces.url("Shadoww_457")
    check("valid name maps to the Worker faces endpoint",
          u is not None and u.endswith("/faces/Shadoww_457.png"), str(u))
    check("blank name is rejected", faces.url("") is None)
    check("path-hostile name is rejected", faces.url("../etc/passwd") is None)
    check("over-long name is rejected", faces.url("a" * 17) is None)

    # --- cache miss -> None, one background download scheduled ----------
    dl = {"n": 0}

    class _Resp:
        status_code = 200
        content = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
            "h6FO1AAAAABJRU5ErkJggg==")  # 1x1 PNG

    def _fake_get(url, headers=None, timeout=None):
        dl["n"] += 1
        return _Resp()

    faces.requests = type("R", (), {"get": staticmethod(_fake_get)})

    name = "Testface"
    check("cache miss returns None (chip shows until fetch lands)",
          faces.get_face_b64(name) is None)
    for _ in range(200):
        if dl["n"]:
            break
        time.sleep(0.01)
    check("miss scheduled exactly one background download", dl["n"] == 1, str(dl["n"]))

    # Simulate the download landing on disk (the thread may still be running).
    dest = faces._dest(name)
    with open(dest, "wb") as f:
        f.write(_Resp().content)
    got = faces.get_face_b64(name)
    check("cached face is served as base64",
          bool(got) and base64.b64decode(got) == _Resp().content)

    # --- negative cache: a non-Cubeon name never re-requests -------------
    def _failing_get(url, headers=None, timeout=None):
        dl["n"] += 1
        return type("R2", (), {"status_code": 404, "content": b""})()

    faces.requests = type("R", (), {"get": staticmethod(_failing_get)})
    ghost = "NotOnCubeon"
    check("unknown player still returns None", faces.get_face_b64(ghost) is None)
    for _ in range(200):
        if dl["n"] > 1:
            break
        time.sleep(0.01)
    after_first = dl["n"]
    check("404 recorded as a miss", after_first >= 2, str(dl["n"]))
    for _ in range(20):
        faces.get_face_b64(ghost)  # roster polls every 1.5s - these are the repaints
        time.sleep(0.005)
    check("negative cache: repeated misses do NOT re-request",
          dl["n"] == after_first, f"{dl['n']} vs {after_first}")

    # --- in-flight dedupe -------------------------------------------------
    class _Slow:
        status_code = 200
        content = _Resp().content

    started = threading.Event()
    release = threading.Event()

    def _slow_get(url, headers=None, timeout=None):
        dl["n"] += 1
        started.set()
        release.wait(2)
        return _Slow()

    faces.requests = type("R", (), {"get": staticmethod(_slow_get)})
    fresh = "Slowface"
    faces._missed.pop(fresh.lower(), None)
    faces.get_face_b64(fresh)  # schedules download #1 (blocks in-flight)
    started.wait(2)
    faces.get_face_b64(fresh)  # must NOT schedule a second concurrent fetch
    release.set()
    time.sleep(0.2)
    check("in-flight download is deduped (one request)", dl["n"] == after_first + 1,
          f"{dl['n']} vs {after_first + 1}")

    print()
    total, failed = len(_CHECKS), _CHECKS.count(False)
    print(f"{total - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
