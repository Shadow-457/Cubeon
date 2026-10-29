"""Quit always leaves ENDING, including recovered games without a watcher."""
import inspect
import os
import sys
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
import app_driver
from cubeon import watchdog


def find_function(controls, name):
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
    raise AssertionError("Missing " + name)


def check(label, value):
    assert value, label
    print("  ok  " + label)


driver = app_driver.build_headless()
controls = list(fz.every_control(driver.page))
quit_game = find_function(controls, "_quit_running_game")
main_action = find_function(controls, "_main_action_click")
scope = inspect.getclosurevars(quit_game).nonlocals
state = scope["state"]
button = next(c for c in controls if getattr(c, "on_click", None) is main_action)
button_text = next(c for c in fz.walk(button) if type(c).__name__ == "Text")
jobs = []


class DeferredThread:
    def __init__(self, target, args=(), name=None, **kwargs):
        self.run = lambda: target(*args)
        self.name = name
    def start(self):
        if self.name == "quit-game":
            jobs.append(self.run)


record = {"pid": 987654, "session_id": "recovered-game", "version": "1.20.1"}
live = {"record": record}
def finish(*args):
    live["record"] = None
    return True


with (patch("main.threading.Thread", DeferredThread),
      patch.object(watchdog, "stale_session", side_effect=lambda: live["record"]),
      patch.object(watchdog, "terminate", side_effect=finish) as terminate):
    state["running_version"] = "1.20.1"
    quit_game()
    check("Quit immediately shows disabled ENDING", button.disabled and button_text.value == "ENDING...")
    scope["set_button_mode"]("play")
    main_action()
    check("repaint and duplicate click cannot start a second quit", len(jobs) == 1 and button.disabled)
    jobs.pop()()
    check("successful quit without on_exit clears the running claim", state["running_version"] is None)
    check("successful recovered quit leaves ENDING and enables Play", not button.disabled and button_text.value != "ENDING...")
    check("termination uses the exact session identity", terminate.call_args.args == (987654, "recovered-game"))

    for outcome in (False, RuntimeError("permission denied")):
        live["record"] = record
        state["running_version"] = "1.20.1"
        terminate.side_effect = outcome if isinstance(outcome, Exception) else None
        terminate.return_value = False
        quit_game()
        jobs.pop()()
        check("failed termination leaves an honest retryable Quit button",
              state["running_version"] == "1.20.1" and not button.disabled
              and button_text.value == "QUIT GAME")

    live["record"] = None
    quit_game()
    check("a game already gone also leaves ENDING", state["running_version"] is None and not button.disabled)
print("Quit game checks passed")
