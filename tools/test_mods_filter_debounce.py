"""The installed-mods filter must not rebuild the list on every keystroke.

Reported as stutter while typing in "Search installed mods...". The field
re-filtered and rebuilt every row on each `on_change`, so typing six characters
with 300 mods installed cost six full rebuilds (~120 ms each, measured).

Locked-in behaviour:
  1. a burst of keystrokes performs ZERO rebuilds (they only restart a timer)
  2. exactly one rebuild happens once typing settles, and it applies the final
     query
  3. Enter (on_submit) filters immediately and cancels the pending timer
  4. clearing the field restores the unfiltered list, debounced like typing

A "rebuild" is counted by the tab-label refresh at the end of
`refresh_mods_list()` (only `_build_view_segment` repaints that row).

Run: python tools/test_mods_filter_debounce.py
"""
import inspect
import os
import sys
import time
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz  # noqa: E402
import app_driver  # noqa: E402
from cubeon import thread_safe_ui  # noqa: E402

passed = failed = 0

DEBOUNCE_WAIT = 0.6      # comfortably past the 0.15 s timer


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def function_from_controls(controls, name):
    """Find a helper reachable from the controls (all tab helpers live in the
    builder's closure; same walk the other headless suites use)."""
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


NAMES = ["Sodium", "Sodium Extra", "Iris Shaders", "JEI", "Mod Menu",
         "Fabric API", "Lithium", "Starlight", "AppleSkin", "Cloth Config",
         "Roughly Enough Items", "Your Options Shall Be Respected"]


def fake_mods():
    out = []
    for i, name in enumerate(NAMES):
        out.append({
            "display_name": name,
            "filename": f"mod{i}.jar",
            "stem": name.lower().replace(" ", "-"),
            "slug": name.lower().replace(" ", "-"),
            "project_id": f"pid{i}",
            "enabled": True,
            "size_kb": 12.0,
            "description": "a fake mod",
        })
    return out


stubs = fz.install_safe_stubs()
stubs.core.get_installed_versions = lambda: [{"id": "1.20.1", "type": "release"}]
stubs.core.list_mods = lambda *a, **k: fake_mods()
page = app_driver.DriverPage()
stubs.app.run_sync(page)
driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)
driver.open_tab("mods")
time.sleep(0.3)          # let the tab's own refresh settle

controls = list(fz.every_control(page))
field = next(c for c in controls
             if (getattr(c, "hint_text", "") or "") == "Search installed mods...")
scope = inspect.getclosurevars(
    function_from_controls(controls, "refresh_mods_list")).nonlocals
list_view = scope["mods_list_view"]
tab_label_row = inspect.getclosurevars(
    scope["_build_view_segment"]).nonlocals["view_segment_row"]

refreshed = []


def record(fn):
    """Run fn with refresh recorded; return how many rebuilds it caused."""
    refreshed.clear()
    with patch.object(thread_safe_ui, "refresh",
                      side_effect=lambda c: refreshed.append(c)):
        fn()
    return refreshed.count(tab_label_row)


check("the field is debounced (no immediate rebuild handler)",
      getattr(field.on_change, "__name__", "") == "_schedule_mods_filter",
      repr(field.on_change))
rows_before = len(list_view.controls)

# --- 1. a burst of keystrokes ------------------------------------------------
refreshed.clear()
with patch.object(thread_safe_ui, "refresh",
                  side_effect=lambda c: refreshed.append(c)):
    for text in ("s", "so", "sod", "sodi", "sodiu", "sodium"):
        field.value = text
        field.on_change(None)
    during_burst = refreshed.count(tab_label_row)
    rows_during_burst = len(list_view.controls)
    time.sleep(DEBOUNCE_WAIT)
    after_settle = refreshed.count(tab_label_row)

check("typing does not rebuild the list", during_burst == 0,
      f"{during_burst} rebuild(s) during the burst")
check("the rows are untouched while typing",
      rows_during_burst == rows_before,
      f"{rows_during_burst} rows (was {rows_before})")

# --- 2. the debounce fires once --------------------------------------------
check("the settled query rebuilds exactly once", after_settle == 1,
      f"{after_settle} rebuild(s)")
check("the rows now show only the matches", len(list_view.controls) == 2,
      f"{len(list_view.controls)} rows")

# --- 3. Enter filters immediately ------------------------------------------
refreshed.clear()
with patch.object(thread_safe_ui, "refresh",
                  side_effect=lambda c: refreshed.append(c)):
    field.value = "iris"
    field.on_submit(None)
    immediate = refreshed.count(tab_label_row)
    rows_after_enter = len(list_view.controls)
    time.sleep(DEBOUNCE_WAIT)
    after_window = refreshed.count(tab_label_row)

check("Enter filters without waiting", immediate == 1,
      f"{immediate} rebuild(s)")
check("Enter's query was applied", rows_after_enter == 1,
      f"{rows_after_enter} rows")
check("Enter cancels the pending debounce", after_window == 1,
      f"{after_window} rebuild(s) after the timer window")

# --- 4. clearing the field is debounced too --------------------------------
refreshed.clear()
with patch.object(thread_safe_ui, "refresh",
                  side_effect=lambda c: refreshed.append(c)):
    field.value = ""
    field.on_change(None)
    immediate = refreshed.count(tab_label_row)
    time.sleep(DEBOUNCE_WAIT)
    after_window = refreshed.count(tab_label_row)

check("clearing does not rebuild instantly", immediate == 0,
      f"{immediate} rebuild(s)")
check("clearing repaints the unfiltered list once", after_window == 1,
      f"{after_window} rebuild(s)")
check("the whole list is back (5 rows + Show all)", len(list_view.controls) == 6,
      f"{len(list_view.controls)} rows")

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
