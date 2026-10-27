"""Switching instance must repaint the Play card's name immediately.

Report (2026-10-27): the instance name on the Play tab kept showing the
PREVIOUS instance after picking another one, and only fixed itself after
visiting a second tab and coming back. Cause: ``update_hero()`` mutated plain
``ft.Text`` values but the selection path deliberately does not call
``page.update()`` (a whole-tree diff is exactly the lag the UI is being
optimised away from). Nothing repainted the hero controls, so the new value sat
in memory until an unrelated full repaint - a tab switch - flushed it.

Locked-in behaviour:
  1. selecting another instance changes hero_title.value
  2. hero_title (and the version/loader/issue line) are explicitly refreshed
  3. the same holds for a rename repaint (update_hero is the single source)

Run: python tools/test_hero_repaint.py
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
from cubeon import thread_safe_ui  # noqa: E402

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
    {"id": "1.20.1", "type": "release"},
    {"id": "1.21.11", "type": "release"},
]
page = app_driver.DriverPage()
stubs.app.run_sync(page)
controls = list(fz.every_control(page))
pick = function_from_controls(controls, "_pick_version")
update_hero = function_from_controls(controls, "update_hero")
scope = inspect.getclosurevars(update_hero).nonlocals
hero_title = scope["hero_title"]
hero_version_text = scope["hero_version_text"]
version_issue_text = scope["version_issue_text"]

refreshed = []
real_refresh = thread_safe_ui.refresh

with patch.object(thread_safe_ui, "refresh",
                  side_effect=lambda c: refreshed.append(c)):
    pick("1.20.1")
    first_title = hero_title.value
    refreshed.clear()
    pick("1.21.11")
    second_title = hero_title.value

check("picking another instance changes the hero title",
      first_title == "Minecraft 1.20.1"
      and second_title == "Minecraft 1.21.11",
      f"first={first_title!r} second={second_title!r}")
check("the hero title is repainted, not just mutated",
      hero_title in refreshed,
      f"refreshed={[type(c).__name__ for c in refreshed]}")
check("the version line is repainted too", hero_version_text in refreshed,
      f"value={hero_version_text.value!r}")
check("the issue line is repainted with the same selection",
      version_issue_text in refreshed)

# A rename goes through the same update_hero(); its repaint must not depend on
# the tab the user happens to be on.
refreshed.clear()
with patch.object(thread_safe_ui, "refresh",
                  side_effect=lambda c: refreshed.append(c)):
    update_hero()
check("a bare hero repaint refreshes the name", hero_title in refreshed,
      f"refreshed={[type(c).__name__ for c in refreshed]}")

check("the real refresh was restored at the end",
      thread_safe_ui.refresh is real_refresh)

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
