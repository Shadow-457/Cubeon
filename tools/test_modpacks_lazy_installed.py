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

from unittest.mock import patch
from cubeon.theme import THEME, section_label
from cubeon import thread_safe_ui
from ui.modpacks_tab import build_modpacks_tab
from test_content_install_feedback import QueuedThread, functions, env

page = app_driver.DriverPage()
with patch('threading.Thread', QueuedThread), patch.object(thread_safe_ui, 'refresh'):
    root, refresh, load = build_modpacks_tab(
        page, {}, {'selected_mc_version': '1.20.1'}, section_label=section_label,
        go_to_pack=lambda meta: None, **THEME)
    fns = functions(refresh, load, *[getattr(c, 'on_click', None) for c in fz.walk(root)])
    scope = env(fns['_apply_installed_packs'])
    installed_count = scope['installed_count']
    active_view = scope['active_view']
    segment_row = env(scope['_build_view_segment'])['view_segment_row']
    installed_view = env(fns['_render_installed_rows'])['installed_view']
    check('the tab opens on Browse', active_view['value'] == 'browse')
    scans['n'] = 0
    refresh()
    check('hidden installed rows are not built', installed_view.controls == [])
    check('the count uses one scan', installed_count.value == '40 installed' and scans['n'] == 1)
    check('the Installed action shows its count', segment_row.controls[0].content == 'Installed (40)')
    scans['n'] = 0
    t1 = fns['installed_pack_tokens']()
    t2 = fns['installed_pack_tokens']()
    check('browse badges reuse the snapshot', scans['n'] == 0 and 'pack0' in t1 and t1 == t2)
    QueuedThread.jobs.clear()
    fns['on_view_change']('installed')
    check('showing Installed does not scan on the handler', scans['n'] == 0)
    while QueuedThread.jobs:
        QueuedThread.jobs.pop(0)()
    check('installed rows arrive from one background scan', scans['n'] == 1)
    check('large installed sets start in a bounded batch', len(installed_view.controls) == 26)
    scans['n'] = 0
    installed_view.controls[-1].on_click(None)
    check('Show more uses cached packs without scanning', scans['n'] == 0 and len(installed_view.controls) == 40)
    original = tuple(installed_view.controls)
    refresh()
    check('a shown refresh preserves mounted cards', tuple(installed_view.controls) == original and scans['n'] == 1)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
