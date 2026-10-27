"""The pack-install Play guard must fail CLOSED, not open (7.2).

Report/code review: both entry points to a launch wrapped the in-flight pack
check in ``except Exception: pass``. That turned an unreadable registry into
"no pack is writing this instance" - the exact half-written launch the guard
exists to prevent (2026-10-18: "it said installed while it was still installing
mods, and that broke everything").

Locked-in behaviour:
  1. on_play_click refuses (returns False) when the registry check raises
  2. _begin_install_and_launch (the Java-prompt entry point) refuses too
  3. nothing is installed or launched in that state
  4. no install claim is left behind

Run: python tools/test_pack_guard_fail_closed.py
"""
import inspect
import os
import sys
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz  # noqa: E402
import app_driver  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def function_from_controls(controls, name):
    seen = set()

    def visit(fn):
        if not inspect.isfunction(fn) or id(fn) in seen:
            return None
        seen.add(id(fn))
        if fn.__name__ == name:
            return fn
        for value in inspect.getclosurevars(fn).nonlocals.values():
            found = visit(value)
            if found:
                return found

    for control in controls:
        found = visit(getattr(control, "on_click", None))
        if found:
            return found
    raise AssertionError(f"Missing callback {name}")


stubs = fz.install_safe_stubs()
stubs.core.get_installed_versions = lambda: [
    {"id": "1.20.1", "type": "release"}]
page = app_driver.DriverPage()
stubs.app.run_sync(page)
controls = list(fz.every_control(page))
play = function_from_controls(controls, "on_play_click")
begin = function_from_controls(controls, "_begin_install_and_launch")
scope = inspect.getclosurevars(play).nonlocals
state = scope["state"]
scope["username_field"].value = "Tester"
scope["version_dropdown"].value = "1.20.1"
for key in ("installing_version", "launching_version", "running_version"):
    state[key] = None

calls = []
with patch.object(stubs.core, "pack_install_for_instance",
                  side_effect=RuntimeError("registry unavailable")), \
     patch.object(stubs.core, "launch_game",
                  side_effect=lambda *a, **k: calls.append("launch")), \
     patch.object(stubs.core, "install_version",
                  side_effect=lambda *a, **k: calls.append("install")):
    play_result = play()
    begin_result = begin("1.20.1", "Tester")

check("the Play click refuses when the guard cannot be read",
      play_result is False, f"returned={play_result!r}")
check("the Java-prompt entry point refuses too",
      begin_result is False, f"returned={begin_result!r}")
check("nothing was installed or launched", calls == [], f"calls={calls}")
check("no install claim is left behind",
      state.get("installing_version") is None,
      f"installing={state.get('installing_version')!r}")

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
