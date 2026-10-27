"""Tab loads must repaint their own region, not the whole tree.

Report (2026-10-27): clicking Mods / Modpacks felt like the whole window
stalled for a moment, and switching the content type (Mods -> Resource Packs)
was the worst. Cause: the browse/loading/result paths called ``page.update()``,
which diffs EVERY mounted tab - while the same moment already paints a new
section and starts a network fetch. The tab builders only need to repaint the
handful of controls they changed.

Locked-in behaviour:
  1. switching the Mods tab's content type performs ZERO full page.update()
     calls and refreshes the browse region (loading placeholder + pager)
  2. the browse loading placeholder is a scoped repaint
  3. rendering a cached Modpacks page performs ZERO full page.update() calls
     and refreshes results/status/pager instead

Run: python tools/test_tab_repaint_scope.py
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
    """Find a callback or a function reachable from one (same walk the other
    headless suites use; all tab helpers live in the builder's closure)."""
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
driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)

# --- 1. Mods: switching content type -----------------------------------------
driver.open_tab("mods")
controls = list(fz.every_control(page))
segment = next(
    c for c in controls
    if isinstance(getattr(getattr(c, "on_click", None), "__defaults__", None), tuple)
    and getattr(c.on_click, "__defaults__")[0] == "resourcepack")
show_loading = function_from_controls(controls, "_show_browse_loading")
loading_scope = inspect.getclosurevars(show_loading).nonlocals
browse_results_view = loading_scope["browse_results_view"]
browse_pager_row = loading_scope["browse_pager_row"]
header_title = inspect.getclosurevars(
    function_from_controls(controls, "_apply_type_labels")).nonlocals["header_title"]

refreshed, updates = [], []
with patch.object(thread_safe_ui, "refresh",
                  side_effect=lambda c: refreshed.append(c)), \
     patch.object(page, "update", side_effect=lambda *a: updates.append(a)):
    segment.on_click(None)

check("the content-type switch actually ran", header_title.value == "Resource Packs",
      f"header={header_title.value!r}")
check("it does not diff the whole page", len(updates) == 0,
      f"{len(updates)} page.update() calls")
check("it still repaints something", bool(refreshed),
      f"{len(refreshed)} control refreshes")
check("the browse results region is repainted", browse_results_view in refreshed)
check("the pager/loading state is repainted", browse_pager_row in refreshed)

# --- 2. Mods: the loading placeholder ---------------------------------------
refreshed.clear()
updates.clear()
with patch.object(thread_safe_ui, "refresh",
                  side_effect=lambda c: refreshed.append(c)), \
     patch.object(page, "update", side_effect=lambda *a: updates.append(a)):
    show_loading()
check("the loading placeholder is a scoped repaint", len(updates) == 0,
      f"{len(updates)} page.update() calls")
check("it repaints the results view it just rewrote",
      browse_results_view in refreshed)

# --- 3. Modpacks: rendering a cached page -----------------------------------
driver.open_tab("modpacks")
controls = list(fz.every_control(page))
render_page = function_from_controls(controls, "_render_page")
rscope = inspect.getclosurevars(render_page).nonlocals
browse_state = rscope["browse_state"]
results_view = rscope["results_view"]
browse_status = rscope["browse_status"]
pager_row = rscope["pager_row"]
# A page that is already cached: no fetch, pure render. gen=-1 can never match
# a live search generation, so background work from opening the tab can't
# republish over this state mid-test.
browse_state.update({"gen": -1, "page": 0, "total_pages": 1,
                     "empty_msg": "No modpacks found.", "results": [],
                     "pages": {0: [{
                         "title": "Scope Test Pack",
                         "slug": "scope-test-pack",
                         "project_id": "scopetest",
                         "provider": "modrinth",
                         "description": "a pack for the repaint test",
                         "downloads": 12,
                     }]}})

refreshed.clear()
updates.clear()
with patch.object(thread_safe_ui, "refresh",
                  side_effect=lambda c: refreshed.append(c)), \
     patch.object(page, "update", side_effect=lambda *a: updates.append(a)):
    render_page()

check("a cached Modpacks page renders a row", len(results_view.controls) == 1,
      f"{len(results_view.controls)} rows")
check("it does not diff the whole page", len(updates) == 0,
      f"{len(updates)} page.update() calls")
check("it repaints the results view", results_view in refreshed)
check("it repaints the result count line", browse_status in refreshed)
check("it repaints the pager row", pager_row in refreshed)

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
