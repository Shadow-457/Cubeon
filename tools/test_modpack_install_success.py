"""A finished modpack install must not be reported as a failure (8.3).

Report/code review: ``_end_install_ok`` paints "Installed <pack> ✓" and then
calls ``refresh_installed_packs()`` and ``_render_page()`` with no protection.
``run_install``'s worker wraps those calls in one broad ``except Exception``, so
a UI refresh failure (stale control, unreadable pack meta) turned the line into
"Install failed: RuntimeError: ..." - while the pack really is installed.

Locked-in behaviour:
  1. a failing installed-packs refresh does not make ``_end_install_ok`` raise
  2. the success line stays "Installed <name> ✓"
  3. the browse refresh still gets its own attempt
  4. busy/preparing are released

Run: python tools/test_modpack_install_success.py
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


def find_functions(start_controls, name):
    """Every function called `name` reachable through control handlers and
    their closure nonlocals (the builders keep their helpers in closures)."""
    seen, found = set(), []

    def visit(fn):
        if not inspect.isfunction(fn) or id(fn) in seen:
            return
        seen.add(id(fn))
        if fn.__name__ == name:
            found.append(fn)
        try:
            nonlocals = inspect.getclosurevars(fn).nonlocals
        except Exception:
            return
        for value in nonlocals.values():
            visit(value)

    for control in start_controls:
        if inspect.isfunction(control):
            visit(control)
            continue
        for attr in ("on_click", "on_result", "on_change", "on_files"):
            visit(getattr(control, attr, None))
    return found


stubs = fz.install_safe_stubs()
page = app_driver.DriverPage()
stubs.app.run_sync(page)
driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)
driver.open_tab("modpacks")

found = find_functions(list(page.overlay), "_end_install_ok")
check("found the install-finished handler", bool(found))
end_ok = found[0]
scope = inspect.getclosurevars(end_ok).nonlocals
install_status = scope["install_status"]
busy = scope["busy"]
preparing = scope["preparing"]
refresh_packs = scope["refresh_installed_packs"]
render_page = scope["_render_page"]
render_rows = inspect.getclosurevars(refresh_packs).nonlocals["_render_installed_rows"]
installed_view = inspect.getclosurevars(render_rows).nonlocals["installed_view"]
active_view = inspect.getclosurevars(refresh_packs).nonlocals["active_view"]
results_view = inspect.getclosurevars(render_page).nonlocals["results_view"]

# The Installed rows are built lazily (only while that pane is shown), so put
# the tab on the Installed view to exercise that repaint too.
active_view["value"] = "installed"

# Simulate the two refreshes failing the way a stale control / bad meta does.
# Record the attempts so we can prove both paths were exercised.
refreshed = []


def flaky_refresh(control):
    refreshed.append(control)
    if control is installed_view:
        raise RuntimeError("stale installed list")
    if control is results_view:
        raise RuntimeError("stale browse list")


install_status.value = "Starting..."
raised = None
with patch.object(thread_safe_ui, "refresh", side_effect=flaky_refresh):
    try:
        end_ok({"name": "Test Pack"})
    except Exception as ex:  # the pre-fix behaviour: worker turns this into "failed"
        raised = ex

check("a failing refresh does not escape the success handler", raised is None,
      repr(raised))
check("the install still reads as successful",
      install_status.value == "Installed Test Pack ✓",
      repr(install_status.value))
check("the installed-packs refresh was attempted", installed_view in refreshed)
check("the browse refresh got its own attempt", results_view in refreshed)
check("busy is released", busy["value"] is False)
check("preparing is released", preparing["value"] is False)

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
