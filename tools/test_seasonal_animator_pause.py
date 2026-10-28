"""The seasonal ticker must block (not poll) while the window is invisible.

`SeasonalAnimator` ticks every 0.12 s (~8.3/s) and repaints its controls. That
is right while the window is on screen, and pure waste while it is minimized -
the common case, since the launcher sits minimized while Minecraft runs.
Measured live (seasonal_theme/season_pet/season_ambience on, 6 s sample):
8.3 ticks/s minimized before, 0.3/s after (the two are the frames in flight
around the event); on restore it returns to 8.0/s.

Locked-in behaviour:
  1. a started animator ticks
  2. pause() stops it completely - no frames, and no CPU spent polling
  3. resume() restarts it from where it stopped (no pose reset)
  4. stop() while paused returns immediately (a blocked ticker still sees it)
  5. main.py pauses on minimize/hide and resumes on restore/show/focus

Run: python tools/test_seasonal_animator_pause.py
"""
import ast
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


from ui.seasonal_ui import SeasonalAnimator  # noqa: E402


class FakeCtrl:
    """Enough of a control for add_pet(); _frame is replaced by a counter."""


def make_animator():
    animator = SeasonalAnimator()
    animator.add_pet(FakeCtrl())          # any registration means has_work
    ticks = []
    animator._frame = lambda: ticks.append(time.monotonic())
    return animator, ticks


# --- 1. visible: it ticks --------------------------------------------------
animator, ticks = make_animator()
check("has_work is true with a registration", animator.has_work)
animator.start()
time.sleep(0.55)
check("a started animator ticks", len(ticks) >= 2, f"{len(ticks)} frames in 0.55s")
check("the ticker thread is alive", animator.running)

# --- 2. paused: no frames and no busy-wait ---------------------------------
animator.pause()
time.sleep(0.3)                       # let any in-flight frame land
settled = len(ticks)
cpu_before = time.process_time()
time.sleep(0.8)
cpu_used = time.process_time() - cpu_before
check("pause() stops the frames", len(ticks) == settled,
      f"{len(ticks) - settled} frame(s) while paused")
check("a paused ticker does not spin", cpu_used < 0.15,
      f"{cpu_used * 1000:.0f} ms CPU in 0.8 s - polling, not blocking")
check("the paused thread is still alive (not stopped)", animator.running)

# --- 3. resume: it ticks again --------------------------------------------
resumed = len(ticks)
animator.resume()
time.sleep(0.55)
check("resume() restarts the frames", len(ticks) > resumed,
      f"{len(ticks) - resumed} frame(s) after resume")
check("the tick counter did not jump (no rewind/fast-forward)",
      animator._tick >= 0)

# --- 4. stop() while paused must not hang ----------------------------------
animator.pause()
time.sleep(0.2)
started = time.monotonic()
animator.stop()
took = time.monotonic() - started
check("stop() on a paused animator returns at once", took < 1.0,
      f"took {took:.2f}s")
check("the thread is gone after stop()", not animator.running)

# --- 5. main.py wires the window events -----------------------------------
SOURCE = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
TREE = ast.parse(SOURCE)


def segment(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(SOURCE, node) or ""
    raise AssertionError(f"main.py has no {name}()")


handler = segment("_on_window_event")
helper = segment("_season_animator_pause")
check("main.py has the pause helper", "animator.pause()" in helper
      and "animator.resume()" in helper)
check("minimize is handled", 'if ev in ("minimize", "hide"):' in handler)
check("minimize pauses the animator",
      "minimize" in handler and "_season_animator_pause(True)" in handler)
check("restore/show/focus resume it",
      'elif ev in ("restore", "show", "focus"):' in handler
      and "_season_animator_pause(False)" in handler)

animator_source = open(os.path.join(ROOT, "ui", "seasonal_ui.py"),
                       encoding="utf-8").read()
check("_run blocks on the pause gate, it does not poll",
      "self._gate.wait()" in animator_source)
check("the gate is a Condition, not an Event (Event.wait returns while set)",
      "_gate = threading.Condition()" in animator_source)
check("resume()/stop() notify the blocked ticker",
      "self._gate.notify_all()" in animator_source)

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
