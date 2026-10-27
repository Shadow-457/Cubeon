"""The install-done -> game-spawning window must hold a launch claim (7.1).

Report: pressing PLAY again while Cubeon was still preparing the launch (doctor
verify, mod repair, spawning the game) started a SECOND game. Between
``installing_version`` being cleared and ``running_version`` being set the
button had no claim to honour, so any repaint showed an enabled PLAY, and both
click paths (_main_action_click -> on_play_click and the Java prompt ->
_begin_install_and_launch) saw nothing in flight either.

These checks drive the real handlers against the headless UI:
  1. set the claim; set_button_mode("play") must paint disabled LAUNCHING...
  2. a second on_play_click() must be refused and start no worker
  3. the hero click and the direct install path must also refuse
  4. the worker must claim the launch slot when the install phase ends (and
     keep the button disabled until "running" takes over), then release it in
     its finally when the launch fails

Run: python tools/test_launch_claim.py
"""
import inspect
import os
import sys
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
import app_driver
from cubeon import thread_safe_ui

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
installed = [{"id": "1.20.1", "type": "release"}]
stubs.core.get_installed_versions = lambda: list(installed)
page = app_driver.DriverPage()
stubs.app.run_sync(page)
controls = list(fz.every_control(page))

begin = function_from_controls(controls, "_begin_install_and_launch")
main_action = function_from_controls(controls, "_main_action_click")
on_play = function_from_controls(controls, "on_play_click")
scope = inspect.getclosurevars(begin).nonlocals
play_scope = inspect.getclosurevars(on_play).nonlocals
state = scope["state"]
set_button_mode = scope["set_button_mode"]
version_dropdown = play_scope["version_dropdown"]
username_field = play_scope["username_field"]
play_button = next(c for c in controls
                   if getattr(c, "on_click", None) is main_action)
play_text = next(c for c in fz.walk(play_button)
                 if type(c).__name__ == "Text"
                 and getattr(c, "value", None) == "PLAY")

version_dropdown.value = "1.20.1"
username_field.value = "SmokePilot"
state["mod_loader"] = "vanilla"

jobs = []


class DeferredThread:
    def __init__(self, target, args=(), **kwargs):
        self.target = target
        self.run = lambda: target(*args)

    def start(self):
        target = self.target
        # Snackbars and loader-support notices also start short workers; only
        # defer the install/launch worker (the one that owns the claim).
        if inspect.isfunction(target) and "do_install_and_launch" in \
                inspect.getclosurevars(target).nonlocals:
            jobs.append(self.run)


with patch("main.threading.Thread", DeferredThread):
    # --- the window between "install done" and "game running" --------------
    state["installing_version"] = None
    state["launching_version"] = "1.20.1"
    set_button_mode("play")
    check("a launch claim turns a repainted play into LAUNCHING...",
          play_button.disabled and play_text.value == "LAUNCHING...",
          f"disabled={play_button.disabled} text={play_text.value!r}")

    check("a second on_play_click() is refused", on_play() is False)
    check("...and starts no worker", jobs == [],
          f"jobs={len(jobs)}")

    main_action(None)
    check("the hero click does nothing while launching", jobs == [],
          f"jobs={len(jobs)}")

    check("the direct install path refuses too",
          begin("1.20.1", "tester") is False and jobs == [],
          f"jobs={len(jobs)}")

    # --- the claim is released when the window closes ----------------------
    state["launching_version"] = None
    set_button_mode("play")
    check("clearing the claim restores a clickable PLAY",
          play_text.value == "PLAY" and not play_button.disabled,
          f"disabled={play_button.disabled} text={play_text.value!r}")

    check("a free claim starts exactly one worker",
          begin("1.20.1", "tester") is True and len(jobs) == 1,
          f"jobs={len(jobs)}")

    observed = {}
    real_refresh = thread_safe_ui.refresh

    def flaky_refresh(control):
        # The worker's first progress_card repaint happens right after it
        # clears installing_version and claims the launch slot, before the
        # "running" handover. That is exactly the window this claim covers.
        if control is scope["progress_card"]:
            observed["text"] = play_text.value
            observed["disabled"] = play_button.disabled
            observed["launching"] = state.get("launching_version")
            observed["installing"] = state.get("installing_version")
            raise RuntimeError("fixture: repaint failed")
        return real_refresh(control)

    try:
        with patch.object(thread_safe_ui, "refresh", flaky_refresh):
            jobs.pop(0)()
    except RuntimeError as ex:
        observed["error"] = str(ex)

    check("the worker claims the launch slot when the install phase ends",
          observed.get("launching") == "1.20.1"
          and observed.get("installing") is None,
          f"observed={observed}")
    check("the button is disabled LAUNCHING... in that window",
          observed.get("disabled") is True
          and observed.get("text") == "LAUNCHING...",
          f"observed={observed}")
    check("a failure in that window releases the claim in the finally",
          state.get("launching_version") is None
          and state.get("installing_version") is None,
          f"launching={state.get('launching_version')!r} "
          f"installing={state.get('installing_version')!r}")
    check("the button is usable again after the failure",
          play_text.value == "PLAY" and not play_button.disabled,
          f"disabled={play_button.disabled} text={play_text.value!r}")

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
