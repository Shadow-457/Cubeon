"""Icon single-flight caching, stable mod rows, and a quiet native banner fade."""
import inspect
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sandbox_home
_sandbox_home.isolate()

import flet as ft
import msgpack
from flet.controls.base_control import BaseControl
from flet.controls.object_patch import ObjectPatch
from flet.messaging.protocol import configure_encode_object_for_msgpack
from cubeon.theme import hint_message
from cubeon import icons, motion, thread_safe_ui
from cubeon.theme import THEME, section_label
from ui.versions import VersionBanner, BANNER_FADE_MS

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'}   {label}")


class QueuedThread:
    jobs = []

    def __init__(self, target, args=(), kwargs=None, **options):
        self.target = lambda: target(*args, **(kwargs or {}))

    def start(self):
        self.jobs.append(self.target)


with tempfile.TemporaryDirectory() as directory, patch.object(icons, "ICON_DIR", directory):
    url = "https://example.invalid/cached.png"
    icon_path = Path(icons._dest(url))
    icon_path.write_bytes(b"cached icon")
    with patch("builtins.open", wraps=open) as reads:
        first = icons.src(url)
        check("cached icons are read and encoded once", all(icons.src(url) == first for repeat in range(20)) and reads.call_count == 1)
    icon_path.write_bytes(b"updated cached icon")
    check("changed icon files invalidate their encoded cache", icons.src(url) != first)
    response = SimpleNamespace(content=b"downloaded icon", raise_for_status=lambda: None)
    with patch.object(icons.threading, "Thread", QueuedThread), patch.object(icons.requests, "get", return_value=response) as download:
        for repeat in range(20):
            icons.prefetch("https://example.invalid/new.png")
        check("concurrent icon requests start one download worker", len(QueuedThread.jobs) == 1)
        QueuedThread.jobs.pop(0)()
        check("the icon downloads once and clears its in-flight marker", download.call_count == 1 and not icons._inflight)
        for repeat in range(20):
            icons.prefetch("https://example.invalid/new.png")
        check("cached icon prefetch starts no workers", not QueuedThread.jobs)
        with patch.object(icons.requests, "get", side_effect=OSError("offline")):
            icons.prefetch("https://example.invalid/retry.png")
            QueuedThread.jobs.pop(0)()
        check("failed icon downloads leave no stuck in-flight request", not icons._inflight)
        icons.prefetch("https://example.invalid/retry.png")
        check("failed downloads can retry", len(QueuedThread.jobs) == 1)
        QueuedThread.jobs.pop(0)()
    check("the encoded icon cache stays bounded", len(icons._sources) <= icons._SOURCE_LIMIT)

banner = VersionBanner()
with patch.object(thread_safe_ui, "refresh") as repaint:
    switcher = banner.control
    initial_frames = tuple(switcher.controls)
    check("the banner uses retained images and a short opacity fade",
          isinstance(switcher, ft.Stack) and initial_frames[1].animate_opacity.duration == BANNER_FADE_MS == 180
          and all(frame.gapless_playback and frame.rotate is None and frame.scale is None for frame in initial_frames))
    check("a new banner paints once", banner.set_source("next.jpg") and repaint.call_count == 1)
    check("the banner host and both images stay mounted while its background changes",
          banner.control is switcher and tuple(switcher.controls) == initial_frames
          and initial_frames[1].src == 'next.jpg' and initial_frames[1].opacity == 1
          and all(frame.fit == ft.BoxFit.COVER for frame in initial_frames))
    check("repeated banner refreshes do not replay the fade", not banner.set_source("next.jpg")
          and tuple(switcher.controls) == initial_frames and repaint.call_count == 1)
    motion.set_level("reduced")
    banner.set_source("calm.jpg")
    check("reduced motion keeps only the permitted opacity transition",
          initial_frames[1].animate_opacity.duration == 180 and switcher.scale is None and switcher.offset is None
          and initial_frames[0].src == 'calm.jpg' and initial_frames[1].opacity == 0)
    motion.set_level("full")
    banner.set_source(None)
    check("missing banner art falls back safely", banner.source == "titleimg.jpg")

import _fuzz_common
from app_driver import DriverPage
from ui.mods_tab import build_mods_tab

stubs = _fuzz_common.install_safe_stubs()
mods = [{"filename": "demo.jar", "display_name": "Demo", "enabled": True,
         "size_kb": 10, "slug": "demo"},
        {"filename": "other.jar", "display_name": "Other", "enabled": True,
         "size_kb": 20, "slug": "other"}]
stubs.core.list_mods = lambda *args, **kwargs: [dict(mod) for mod in mods]
stubs.core.get_mod_icons = lambda slugs: {slug: "https://example.invalid/icon.png" for slug in slugs}
state = {"selected_mc_version": "1.21.1", "mod_loader": "fabric"}
page = DriverPage()
with patch("ui.mods_tab.threading.Thread", QueuedThread), patch.object(icons, "prefetch"):
    root, refresh, load, browse_refresh = build_mods_tab(
        page, {}, state, ft.Dropdown(value="1.21.1"), section_label=section_label, **THEME)
    scope = _fuzz_common.callback_scope(refresh)
    refresh()
    rows = tuple(scope["mods_list_view"].controls)
    for repeat in range(3):
        refresh()
    check("installed rows stay mounted on refresh", tuple(scope["mods_list_view"].controls) == rows)
    check("installed icon metadata uses one in-flight worker", len(QueuedThread.jobs) == 1)
    QueuedThread.jobs.pop(0)()
    images = tuple(row.content.controls[0].content for row in rows)
    refresh()
    check("resolved icons stay mounted on later refreshes", all(row.content.controls[0].content is image for row, image in zip(rows, images)))
    with patch.object(thread_safe_ui, 'refresh') as repaint, \
         patch.object(stubs.core, 'list_mods', wraps=stubs.core.list_mods) as scan, \
         patch.object(refresh.__self__, 'auto_check'):
        scope['active_view']['value'] = 'installed'
        refresh(background=True, navigation=True)
        check("returning to fresh Mods performs no list repaint or disk scan",
              repaint.call_count == 0 and scan.call_count == 0)
        state['pending_loader_install'] = {'version_id': '1.21.1', 'loader': 'fabric'}
        refresh(background=True, navigation=True)
        check("a changed install gate still repaints the cached Mods list", repaint.call_count > 0)
        state.pop('pending_loader_install')
        scope['active_view']['value'] = 'browse'
    refresh()
    mods[0].update(filename="demo.jar.disabled", enabled=False)
    refresh()
    check("toggling a mod preserves its row and icon", scope["mods_list_view"].controls[0] is rows[0] and rows[0].content.controls[0].content is images[0])
    check("toggling updates labels and the switch in place", not rows[0].content.controls[2].value and "Disabled" in rows[0].content.controls[1].controls[1].value)
    encode = configure_encode_object_for_msgpack(BaseControl)
    installed_list = scope["mods_list_view"]
    initial, added, removed = ObjectPatch.from_diff(None, installed_list, BaseControl)
    msgpack.packb(initial.to_message(), default=encode)
    refresh()
    changes, added, removed = ObjectPatch.from_diff(installed_list, installed_list, BaseControl)
    encoded = msgpack.packb(changes.to_message(), default=encode)
    check("real installed-list refreshes neither remount nor retransmit icons", not added and not removed and b"src" not in encoded)
    functions = _fuzz_common.callback_functions(refresh, load, browse_refresh)
    project = {"project_id": "store-demo", "slug": "store-demo", "title": "Store demo",
               "description": "Test", "downloads": 10, "icon_url": "https://example.invalid/demo.png"}
    build_row = functions["build_browse_row"]
    row = build_row(project, False)
    image = row.content.controls[0]
    check("browse refreshes reuse the same row and image", build_row(dict(project), False) is row and row.content.controls[0] is image)
    check("install-state changes preserve browse art", build_row(project, True) is row and row.content.controls[0] is image)
    action = row.content.controls[-1]
    check("installed browse actions update in place", action.disabled and action.content.controls[1].value == "Installed")
    build_row(project, False)
    check("deleted mods offer Install without rebuilding the row", not action.disabled and callable(action.on_click) and action.content.controls[1].value == "Install")
    action_width = action.width
    build_row(project, True)
    build_row(project, False)
    check("install action width stays fixed while its label changes", action.width == action_width and action.height == 30)
    check("mod rows have no click shrink animation", not callable(row.on_tap_down))
    render = functions["_render_browse_page"]
    browse_scope = _fuzz_common.callback_scope(render)
    browse_scope["browse_state"].update(token=object(), page=0, paged=False, pages={0: [project]})
    render()
    browse_list = browse_scope["browse_results_view"]
    visible_rows = tuple(browse_list.controls)
    render()
    check("cached browse pages keep their mounted rows", tuple(browse_list.controls) == visible_rows)
    functions["_show_browse_loading"]()
    check("loading keeps the previous list height, icons and native scrolling",
          tuple(browse_list.controls) == visible_rows and not browse_list.disabled
          and all(r.ignore_interactions for r in visible_rows if r.data != 'cubeon-client-browse'))
    render()
    check("completed page loads re-enable the same controls", tuple(browse_list.controls) == visible_rows and not browse_list.disabled)
    initial, added, removed = ObjectPatch.from_diff(None, browse_list, BaseControl)
    msgpack.packb(initial.to_message(), default=encode)
    render()
    changes, added, removed = ObjectPatch.from_diff(browse_list, browse_list, BaseControl)
    encoded = msgpack.packb(changes.to_message(), default=encode)
    check("real browse refreshes neither remount nor retransmit icons", not added and not removed and b"src" not in encoded)

print('\nMods loading follows the visible pane')


class NamedQueuedThread:
    jobs = []

    def __init__(self, target, args=(), kwargs=None, name='', **options):
        self.job = (name, lambda: target(*args, **(kwargs or {})))

    def start(self):
        self.jobs.append(self.job)


loading_state = dict(selected_mc_version='1.21.1', mod_loader='fabric',
                     installed={'loading-probe'}, active_tab='mods', mods_recommendations_loaded=True)
installed_item = dict(filename='demo.jar', display_name='Demo', size_kb=10, enabled=True, stem='demo')
with patch('ui.mods_tab.threading.Thread', NamedQueuedThread), \
     patch('ui.mods_tab.instance_info.describe', return_value={'loader': 'fabric'}) as descriptor, \
     patch.object(stubs.core, 'list_mods', return_value=[installed_item]) as scan, \
     patch('ui.mods_tab.check_content', return_value={'unfixed': [], 'elapsed': .001}), \
     patch.object(icons, 'prefetch'):
    dropdown = ft.Dropdown(value='loading-probe')
    root, refresh, enter, changed = build_mods_tab(
        page, {}, loading_state, dropdown, section_label=section_label, **THEME)
    view = refresh.__self__
    projects = [dict(project_id=str(i), slug=f'demo-{i}', title=f'Demo {i}') for i in range(24)]
    with patch.object(view, '_browse_fetch', return_value=projects):
        enter()
        check('opening Browse starts only the two catalogue providers',
              [name for name, job in NamedQueuedThread.jobs] ==
              ['cubeon-mod-search-modrinth', 'cubeon-mod-search-curseforge'])
        check('building and opening Browse never reads an instance descriptor or archive',
              descriptor.call_count == 0 and scan.call_count == 0)
        with patch.object(thread_safe_ui, 'refresh') as repaint:
            enter()
            check('returning during a fetch adds no worker or repaint',
                  len(NamedQueuedThread.jobs) == 2 and repaint.call_count == 0)
        NamedQueuedThread.jobs.pop(0)[1]()
        check('the first provider publishes results before the badge scan',
              len(view.browse_state['results']) == 24 and scan.call_count == 0
              and NamedQueuedThread.jobs[-1][0] == 'mods-refresh')
        generation = view.installed_refresh._generation
        NamedQueuedThread.jobs.pop(0)[1]()
        check('the second provider shares the same installed snapshot request',
              len(NamedQueuedThread.jobs) == 1 and view.installed_refresh._generation == generation)
        NamedQueuedThread.jobs.pop(0)[1]()
    check('the snapshot scans and verifies the selected instance once',
          scan.call_count == 1 and descriptor.call_count == 1 and not view.local_install_btn.disabled)
    check('Browse never builds hidden installed cards or starts compatibility checks',
          not view.installed_rows and not NamedQueuedThread.jobs)
    mounted = tuple(view.browse_results_view.controls)
    descriptor.reset_mock()
    view._render_browse_page()
    check('a full two-provider page paints without descriptor reads or remounts',
          descriptor.call_count == 0 and tuple(view.browse_results_view.controls) == mounted)
    with patch.object(thread_safe_ui, 'refresh') as repaint:
        enter()
        check('a cached Browse entry skips workers and result repaints',
              not NamedQueuedThread.jobs and repaint.call_count == 0)
    with patch('ui.mods_tab.instance_info.describe', return_value={'loader': 'vanilla'}) as verify:
        mounted[1].content.controls[-1].on_click(None)
        check('an actual install rechecks disk truth and rejects a changed Vanilla instance',
              verify.call_count == 1 and not NamedQueuedThread.jobs)
    view.on_view_change('installed')
    check('Installed reuses the snapshot and starts one compatibility check',
          scan.call_count == 1 and bool(view.installed_rows)
          and [name for name, job in NamedQueuedThread.jobs] == ['cubeon-content-check'])
    NamedQueuedThread.jobs.pop(0)[1]()
    view.on_view_change('browse')
    view.mod_search_field.value = 'pending'
    with patch.object(view, '_browse_fetch', return_value=projects):
        view.run_mod_search()
        before = tuple(view.browse_results_view.controls)
        loading_state['active_tab'] = 'play'
        with patch.object(thread_safe_ui, 'refresh') as repaint:
            while NamedQueuedThread.jobs:
                NamedQueuedThread.jobs.pop(0)[1]()
            check('provider completions cache data without repainting a hidden tab',
                  repaint.call_count == 0 and tuple(view.browse_results_view.controls) == before)
        loading_state['active_tab'] = 'mods'
        enter()
        check('returning after hidden completion paints the finished cached page',
              len(view.browse_state['results']) == 48 and not NamedQueuedThread.jobs
              and view._rendered_browse_results is view.browse_state['pages'][0])
        loading_state['active_tab'] = 'play'
        dropdown.value = 'new-profile'
        loading_state['selected_mc_version'] = '1.20.1'
        changed()
        check('changing profiles while Mods is hidden starts no search or scan', not NamedQueuedThread.jobs)
        loading_state['active_tab'] = 'mods'
        enter()
        check('reopening Mods loads the current profile rather than hidden stale results',
              view.browse_state['token'][1][2] == 'new-profile'
              and len(NamedQueuedThread.jobs) == 2)
    NamedQueuedThread.jobs.clear()
    view.selected_content['value'] = 'modpack'
    snapshot = view._read_installed_snapshot(view._installed_target())
    with patch.object(thread_safe_ui, 'refresh') as repaint:
        view._apply_installed_snapshot(snapshot)
        check('a late Mods snapshot does not repaint behind embedded Modpacks', repaint.call_count == 0)

from ui.modpacks_tab import build_modpacks_tab

installed_pack = {"version_id": "fabric-loader-0.16-1.21.1", "mc_version": "1.21.1",
                  "loader": "fabric", "name": "Installed pack", "mod_count": 10,
                  "icon_url": "https://example.invalid/installed-pack.png"}
stubs.core.list_installed_modpacks = lambda: [dict(installed_pack)]
with patch("ui.modpacks_tab.threading.Thread", QueuedThread), patch.object(icons, "prefetch"):
    pack_root, refresh_packs, load_packs = build_modpacks_tab(
        page, {}, state, section_label=section_label, go_to_pack=lambda meta: None, **THEME)
    functions = _fuzz_common.callback_functions(refresh_packs, load_packs)
    pack = {"project_id": "store-pack", "provider": "modrinth", "title": "Store pack",
            "description": "A pack", "downloads": 10, "versions": ["1.21.1"],
            "icon_url": "https://example.invalid/pack.png"}
    build_pack = functions["build_pack_row"]
    row = build_pack(pack, False)
    image = row.content.controls[0]
    check("modpack browse refreshes reuse rows and artwork", build_pack(dict(pack), False) is row and row.content.controls[0] is image)
    changed_pack = dict(pack, downloads=20)
    build_pack(changed_pack, False)
    check("new provider metadata updates without reloading pack artwork", row.content.controls[0] is image and row.content.controls[1].controls[2].controls[1].value == "20")
    build_pack(changed_pack, True)
    action = row.content.controls[-1]
    check("modpack install status changes preserve the row and icon", action.disabled and action.content.controls[1].value == "Installed" and row.content.controls[0] is image)
    state["selected_mc_version"] = "1.20.1"
    build_pack(changed_pack, False)
    check("Play-version changes update pack hints without reloading art", row.content.controls[0] is image and "installs its own" in hint_message(row.tooltip))
    check("pack action width stays fixed", action.width == 84 and action.height == 30)
    pack_scope = _fuzz_common.callback_scope(functions["_render_installed_rows"])
    _fuzz_common.callback_scope(functions["_apply_installed_packs"])["active_view"]["value"] = "installed"
    refresh_packs()
    installed_list = pack_scope["installed_view"]
    saved_row = installed_list.controls[0]
    saved_image = saved_row.content.controls[0].content
    refresh_packs()
    check("installed modpack refreshes preserve the row and icon", installed_list.controls[0] is saved_row and saved_row.content.controls[0].content is saved_image)
    installed_pack["mod_count"] = 12
    refresh_packs()
    check("installed pack counts update without replacing artwork", saved_row.content.controls[0].content is saved_image and "12 mods" in saved_row.content.controls[1].controls[1].value)
    render = functions["_render_page"]
    pack_browse_scope = _fuzz_common.callback_scope(render)
    pack_browse_scope["browse_state"].update(gen=0, page=0, total_pages=2, pages={0: [pack]})
    render()
    catalog = pack_browse_scope["results_view"]
    catalog_rows = tuple(catalog.controls)
    initial, added, removed = ObjectPatch.from_diff(None, catalog, BaseControl)
    msgpack.packb(initial.to_message(), default=encode)
    render()
    changes, added, removed = ObjectPatch.from_diff(catalog, catalog, BaseControl)
    encoded = msgpack.packb(changes.to_message(), default=encode)
    check("real modpack page refreshes neither remount nor retransmit icons", not added and not removed and b"src" not in encoded)
    pack_browse_scope["browse_state"]["page"] = 1
    render()
    check("modpack loading keeps existing artwork and layout", tuple(catalog.controls) == catalog_rows and catalog.disabled)
    pack_browse_scope["browse_state"]["page"] = 0
    render()
    check("cached pack pages re-enable their existing rows", tuple(catalog.controls) == catalog_rows and not catalog.disabled)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
