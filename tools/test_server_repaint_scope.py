"""The Server tab's refresh helpers must repaint their own region, not the tree.

Opening the Servers tab used to cost NINE full ``page.update()`` calls - each
one diffs every mounted control in every tab - for one tab switch. The build
helpers (``set_running_ui``, ``refresh_whitelist_list``, ``refresh_orphan_notice``,
``refresh_plugins_visibility``, the per-dropdown colour sync) each changed a
handful of controls and then diffed the whole window.

Locked-in behaviour:
  1. none of those helpers performs a full page.update()
  2. each one refreshes the controls it actually mutated
  3. set_running_ui repaints the console + settings columns (everything it
     touches lives in those two)

Run: python tools/test_server_repaint_scope.py
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
    """Find a function reachable from the controls (same walk as the other
    headless suites; all tab helpers live in the builder's closure)."""
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
        for attr in ("on_click", "on_select", "on_change"):
            found = visit(getattr(control, attr, None))
            if found:
                return found
    raise AssertionError(f"Missing function {name}")


def scope(fn):
    return inspect.getclosurevars(fn).nonlocals


def repainted(control, refreshed):
    """Does any refreshed region contain this control?"""
    for region in refreshed:
        if control in list(fz.walk(region)):
            return True
    return False


stubs = fz.install_safe_stubs()
stubs.core.get_installed_versions = lambda: [
    {"id": "1.20.1", "type": "release"}]
page = app_driver.DriverPage()
stubs.app.run_sync(page)
driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)

# Each sub-view mounts its own controls, and the helpers live in the builder's
# closure - so open all three, then take one snapshot of the tree (switching a
# sub-view only toggles visibility, it does not unmount the others).
driver.open_tab("server")
driver.open_tab("server_settings")
driver.open_tab("server_plugins")
controls = list(fz.every_control(page))


def run(fn):
    """Call fn with refresh/page.update recorded, return (refreshes, updates)."""
    refreshed, updates = [], []
    with patch.object(thread_safe_ui, "refresh",
                      side_effect=lambda c: refreshed.append(c)), \
            patch.object(page, "update", side_effect=lambda *a: updates.append(a)):
        fn()
    return refreshed, updates


# --- 1. set_running_ui -------------------------------------------------------
set_running_ui = function_from_controls(controls, "set_running_ui")
sscope = scope(set_running_ui)
status_text = sscope["status_text"]
status_dot = sscope["status_dot"]
start_stop_button = sscope["start_stop_button"]
restart_button = sscope["restart_button"]
command_field = sscope["command_field"]
send_command_button = sscope["send_command_button"]
address_text = sscope["address_text"]
eula_checkbox = scope(function_from_controls(
    controls, "refresh_controls_enabled"))["eula_checkbox"]

refreshed, updates = run(lambda: set_running_ui(True))
check("set_running_ui updates the status label", status_text.value == "Running",
      repr(status_text.value))
check("set_running_ui does not diff the whole page", len(updates) == 0,
      f"{len(updates)} page.update() calls")
# Everything it mutates must end up inside a repainted region - this is what a
# page.update() used to guarantee, so it is what the scoped refresh must keep.
for label, control in (
        ("status dot", status_dot), ("status label", status_text),
        ("start/stop button", start_stop_button), ("restart button", restart_button),
        ("console command field", command_field),
        ("send-command button", send_command_button),
        ("LAN address line", address_text),
        ("EULA checkbox (settings column)", eula_checkbox)):
    check(f"set_running_ui repaints the {label}", repainted(control, refreshed),
          f"{len(refreshed)} region(s) refreshed")

# --- 2. refresh_orphan_notice -----------------------------------------------
refresh_orphan_notice = function_from_controls(controls, "refresh_orphan_notice")
oscope = scope(refresh_orphan_notice)
orphan_notice = oscope["orphan_notice"]
stop_orphan_button = oscope["stop_orphan_button"]
stubs.core.is_server_orphaned = lambda version_id: 4242
try:
    refreshed, updates = run(refresh_orphan_notice)
    check("the orphan notice is shown", orphan_notice.visible is True)
    check("refresh_orphan_notice does not diff the whole page", len(updates) == 0,
          f"{len(updates)} page.update() calls")
    check("refresh_orphan_notice repaints the notice", orphan_notice in refreshed)
    check("refresh_orphan_notice repaints its Stop button",
          stop_orphan_button in refreshed)
finally:
    stubs.core.is_server_orphaned = lambda version_id: None

refreshed, updates = run(refresh_orphan_notice)
check("the orphan notice is hidden again when nothing is orphaned",
      orphan_notice.visible is False)

# --- 3. refresh_whitelist_list ----------------------------------------------
driver.open_tab("server_settings")
controls = list(fz.every_control(page))
refresh_whitelist_list = function_from_controls(controls, "refresh_whitelist_list")
wscope = scope(refresh_whitelist_list)
whitelist_list = wscope["whitelist_list"]
stubs.core.get_whitelist = lambda version_id: ["Steve"]
try:
    refreshed, updates = run(refresh_whitelist_list)
    check("the whitelist got a row", len(whitelist_list.controls) == 1,
          f"{len(whitelist_list.controls)} rows")
    check("refresh_whitelist_list does not diff the whole page",
          len(updates) == 0, f"{len(updates)} page.update() calls")
    check("refresh_whitelist_list repaints the list", whitelist_list in refreshed)
finally:
    stubs.core.get_whitelist = lambda version_id: []

# --- 4. refresh_plugins_visibility ------------------------------------------
driver.open_tab("server_plugins")
controls = list(fz.every_control(page))
refresh_plugins_visibility = function_from_controls(
    controls, "refresh_plugins_visibility")
pscope = scope(refresh_plugins_visibility)
plugins_notice = pscope["plugins_not_paper_notice"]
plugins_content = pscope["plugins_content"]
refreshed, updates = run(refresh_plugins_visibility)
check("refresh_plugins_visibility does not diff the whole page",
      len(updates) == 0, f"{len(updates)} page.update() calls")
check("refresh_plugins_visibility repaints the notice", plugins_notice in refreshed)
check("refresh_plugins_visibility repaints the content", plugins_content in refreshed)

# --- 5. the dropdown colour sync -------------------------------------------
sync_owner = next(c for c in controls if callable(getattr(c, "_sync_color", None)))
dd = sync_owner
refreshed, updates = run(lambda: dd._sync_color())
check("the dropdown colour sync does not diff the whole page",
      len(updates) == 0, f"{len(updates)} page.update() calls")
check("the dropdown colour sync repaints the dropdown itself", dd in refreshed)

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
