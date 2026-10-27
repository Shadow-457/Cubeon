"""Entering the Modpacks tab must not build every Installed-packs row (lag).

The tab opens on Browse. `switch_tab` calls `refresh_installed_packs()` on every
visit, and that used to build a complete row per installed pack - icon read or
prefetch, delete dialog, hover wiring - for a pane nobody was looking at.
Measured with 40 installed packs: 42.6 ms and 441 controls before the first
frame of the browse list. Rows are now built when the Installed pane is shown.

Also pins the scan count: one `list_installed_modpacks()` per refresh (shared
with the "Installed (N)" count and the browse "Installed" badges) instead of
three separate directory walks.

Run: python tools/test_modpacks_lazy_installed.py
"""
import inspect
import os
import sys

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz  # noqa: E402
import app_driver  # noqa: E402
import launcher_core as core  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def find_functions(start_controls, name):
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
        for attr in ("on_click", "on_result", "on_change", "on_files", "on_select"):
            visit(getattr(control, attr, None))
    return found


PACKS = [
    {"name": f"Pack {i}", "mc_version": "1.20.1", "loader": "fabric",
     "version_id": f"pack-{i}", "profile": f"pack-profile-{i}", "mod_count": 30}
    for i in range(40)
]
scans = {"n": 0}


def fake_list_installed():
    scans["n"] += 1
    return list(PACKS)


stubs = fz.install_safe_stubs()
stubs.core.list_installed_modpacks = fake_list_installed
core.list_installed_modpacks = fake_list_installed

page = app_driver.DriverPage()
stubs.app.run_sync(page)
driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)
driver.open_tab("modpacks")

found = find_functions(list(page.controls) + list(page.overlay),
                       "refresh_installed_packs")
check("found refresh_installed_packs", bool(found))
refresh = found[0]
scope = inspect.getclosurevars(refresh).nonlocals
installed_count = scope["installed_count"]
active_view = scope["active_view"]
build_segment = scope["_build_view_segment"]

render_rows = find_functions(list(page.controls) + list(page.overlay),
                             "_render_installed_rows")
check("found _render_installed_rows", bool(render_rows))
installed_view = inspect.getclosurevars(render_rows[0]).nonlocals["installed_view"]
segment_row = inspect.getclosurevars(build_segment).nonlocals["view_segment_row"]

on_view_change = find_functions(list(page.controls) + list(page.overlay),
                                "on_view_change")
check("found on_view_change", bool(on_view_change))
switch_view = on_view_change[0]

# --- entry while Browse is showing ---------------------------------------
check("the tab really opens on Browse", active_view["value"] == "browse",
      active_view["value"])
scans["n"] = 0
refresh()
check("no installed rows are built while the pane is hidden",
      installed_view.controls == [], str(len(installed_view.controls)))
check("the count line is still updated", installed_count.value == "40 installed",
      repr(installed_count.value))
check("the segment count is refreshed from the same scan", scans["n"] == 1,
      str(scans["n"]))
labels = [c.content.content.value for c in segment_row.controls
          if getattr(getattr(getattr(c, "content", None), "content", None), "value", None)]
check("the 'Installed (40)' tab label is right",
      any("Installed (40)" in (label or "") for label in labels), str(labels))

# The browse repaint asks for the same tokens twice (Modrinth, then CurseForge).
tokens_fn = find_functions(list(page.controls) + list(page.overlay),
                           "installed_pack_tokens")
check("found installed_pack_tokens", bool(tokens_fn))
scans["n"] = 0
t1 = tokens_fn[0]()
t2 = tokens_fn[0]()
check("browse 'Installed' badges reuse the refresh's scan (no new walk)",
      scans["n"] == 0, str(scans["n"]))
check("the token set matches the installed names",
      "pack0" in t1 and t1 == t2, str(sorted(t1))[:80])

# --- opening the Installed pane builds them ------------------------------
scans["n"] = 0
switch_view("installed")
check("switching to Installed builds one row per pack",
      len(installed_view.controls) == len(PACKS),
      str(len(installed_view.controls)))
check("the switch scans once", scans["n"] == 1, str(scans["n"]))

# --- and a later visit rebuilds while it is showing ----------------------
scans["n"] = 0
refresh()
check("a refresh while Installed is showing keeps the rows",
      len(installed_view.controls) == len(PACKS),
      str(len(installed_view.controls)))
check("that refresh scans once", scans["n"] == 1, str(scans["n"]))

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
