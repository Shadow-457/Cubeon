"""The progress-bar ticker must block while the bar is hidden, and still start.

The ticker used to `time.sleep(0.1)` forever while the bar was hidden - 10
wakeups/second for the entire life of the launcher (measured). It now blocks on
an Event that `set_bar()` sets, so the idle cost is zero - but the animation
must still start, resume after the bar is hidden and shown again (the case a
lost wakeup would freeze), and keep easing toward the target.

Locked-in behaviour:
  1. with the bar visible, set_bar() starts the easing tick
  2. hiding the bar runs one cleanup pass (percent hidden) and then blocks
  3. showing the bar again + set_bar() resumes the tick (no lost wakeup)
  4. instant=True still paints the exact value immediately

Run: python tools/test_bar_idle_wake.py
"""
import inspect
import os
import sys
import time

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
        for attr in ("on_click", "on_change", "on_submit", "on_select"):
            found = visit(getattr(control, attr, None))
            if found:
                return found
    raise AssertionError(f"Missing helper {name}")


stubs = fz.install_safe_stubs()
stubs.core.get_installed_versions = lambda: [{"id": "1.20.1", "type": "release"}]
page = app_driver.DriverPage()
stubs.app.run_sync(page)

controls = list(fz.every_control(page))
set_bar = function_from_controls(controls, "set_bar")
scope = inspect.getclosurevars(set_bar).nonlocals
bar = scope["progress_bar"]
percent = scope["progress_percent"]
wake = scope.get("_bar_wake")

# --- 1. a visible bar animates ---------------------------------------------
bar.visible = True
percent.visible = True
set_bar(0.6)
check("set_bar signals the ticker (no idle polling)",
      wake is not None and wake.is_set(),
      "no wake event - the ticker still polls at 10 Hz" if wake is None
      else "wake event not set")
time.sleep(0.35)
check("the bar eased toward the target", 0 < (bar.value or 0) <= 0.6,
      f"value={bar.value!r}")
check("it does not jump past the target", (bar.value or 0) <= 0.6,
      f"value={bar.value!r}")

# --- 2. hiding the bar cleans up, then blocks ------------------------------
bar.visible = False
time.sleep(0.25)          # one tick is enough to notice
check("the percentage hides with the bar", percent.visible is False,
      repr(percent.visible))
before = bar.value
time.sleep(0.3)
check("a hidden bar is not repainted", bar.value == before,
      f"{before!r} -> {bar.value!r}")

# --- 3. showing it again resumes (a lost wakeup would freeze here) ---------
bar.visible = True
set_bar(0.95)
check("showing the bar re-signals the ticker",
      wake is not None and wake.is_set(),
      "no wake event" if wake is None else "not set - the ticker would stay blocked")
time.sleep(0.35)
check("the ticker resumed after the idle block", (bar.value or 0) > (before or 0),
      f"{before!r} -> {bar.value!r}")

# --- 4. instant paints the exact value -------------------------------------
set_bar(1.0, instant=True)
check("instant=True paints the exact value", bar.value == 1.0, repr(bar.value))
check("the percentage reads 100%", percent.value == "100%", repr(percent.value))

# Leave the bar hidden like a finished install does, so this test does not
# leave the ticker spinning at 30 fps for the rest of the run.
bar.visible = False
time.sleep(0.2)

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
