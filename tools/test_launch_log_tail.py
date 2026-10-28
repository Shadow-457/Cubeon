"""Game-exit handling cannot die silently and does not split log lines (11.4).

Two failures in `launch_game`:

1. `_watch` called `_call_on_exit(...)` unguarded. A UI callback that raised
   killed the daemon thread with the traceback only on stderr - the launcher
   carried on as if the game had never exited.
2. `_drain` used `readline()` on the log the game is still writing. A
   half-written line is returned at EOF and the rest arrives later as a second
   "line", which breaks crash detection matching whole lines.

This runs `launch_game` for real against a tiny Python child that writes a
partial line, pauses, then finishes it (exit code 3). The game command,
mods sync, watchdogs and friends/doctor side-effects are stubbed.

Run: python tools/test_launch_log_tail.py
"""
import contextlib
import os
import sys
import threading
import time
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import launch  # noqa: E402

passed = failed = 0

CHILD = (
    "import sys, time\n"
    "sys.stdout.write('CRASH line one')\n"
    "sys.stdout.flush()\n"
    "time.sleep(0.4)\n"
    "sys.stdout.write(' continued\\nOK line\\n')\n"
    "sys.stdout.flush()\n"
    "sys.exit(3)\n"
)


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def stub_launch(exit_cb):
    """Run launch_game with a real child process and no side effects."""
    import cubeon.content as content
    import cubeon.cubeonfriends as friends
    import cubeon.features as features
    import cubeon.perf_mods as perf_mods
    import cubeon.watchdog as watchdog
    import cubeon.milestones as milestones
    import cubeon.doctor as doctor
    import cubeon.friends_service as friends_service

    stack = contextlib.ExitStack()
    stack.enter_context(patch.object(
        launch, "build_launch_command",
        lambda *a, **k: [sys.executable, "-c", CHILD]))
    stack.enter_context(patch.object(launch, "sync_mods_to_game", lambda *a, **k: None))
    stack.enter_context(patch.object(content, "sync_content_to_game", lambda *a, **k: None))
    stack.enter_context(patch.object(friends, "ensure_installed", lambda *a, **k: False))
    stack.enter_context(patch.object(friends, "remove_installed", lambda *a, **k: None))
    stack.enter_context(patch.object(features, "friends_enabled", lambda: False))
    stack.enter_context(patch.object(perf_mods, "sanitize_entityculling_config",
                                     lambda *a, **k: {"removed": 0, "detail": ""}))
    stack.enter_context(patch.object(watchdog, "register", lambda *a, **k: None))
    stack.enter_context(patch.object(watchdog, "clear", lambda *a, **k: None))
    stack.enter_context(patch.object(milestones, "begin_play_session",
                                     lambda *a, **k: None))
    stack.enter_context(patch.object(milestones, "end_play_session",
                                     lambda *a, **k: None))
    stack.enter_context(patch.object(doctor, "run_doctor",
                                     lambda *a, **k: {"fixed": []}))
    stack.enter_context(patch.object(
        friends_service.FriendsService, "reconcile_username_active",
        staticmethod(lambda *a, **k: None)))
    return stack


def run_once(on_exit):
    done = threading.Event()

    def wrapped(code, lines, session_id=None):
        try:
            on_exit(code, lines, session_id)
        finally:
            done.set()

    with stub_launch(wrapped):
        proc = launch.launch_game(
            "1.20.1", "tester", 1024, 854, 480, None,
            mc_version="1.20.1", loader="fabric", on_exit=wrapped)
        proc.wait(timeout=30)
    if not done.wait(timeout=10):
        raise RuntimeError("on_exit was never called")
    return proc.returncode


def main():
    # --- 1. a partial line is joined, not split ----------------------------
    seen = {}

    def capture(code, lines, session_id=None):
        seen["code"] = code
        seen["lines"] = list(lines)

    code = run_once(capture)
    check("the exit code reaches on_exit", code == 3 or seen.get("code") == 3,
          str(seen))
    check("a line split by the writer is delivered whole",
          seen.get("lines") == ["CRASH line one continued", "OK line"],
          str(seen.get("lines")))

    # --- 2. a raising on_exit is logged, not an uncaught dead thread -------
    records = []

    class Capture(launch.logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    logger = launch.logging.getLogger("cubeon.launch")
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(launch.logging.WARNING)
    try:
        def boom(code, lines, session_id=None):
            raise RuntimeError("UI callback exploded")

        run_once(boom)
        deadline = time.time() + 5
        while time.time() < deadline and not any(
                "game-exit callback failed" in msg for msg in records):
            time.sleep(0.05)
        check("a failing exit callback is logged as a warning",
              any("game-exit callback failed" in msg for msg in records),
              str(records))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
