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
    initial_frame = switcher.content
    check("the banner uses a short fade, not zoom or rotation", switcher.transition == ft.AnimatedSwitcherTransition.FADE and switcher.duration == BANNER_FADE_MS == 180)
    check("a new banner paints once", banner.set_source("next.jpg") and repaint.call_count == 1)
    next_frame = switcher.content
    check("the banner host stays mounted while its background changes", banner.control is switcher and next_frame is not initial_frame and next_frame.image.fit == ft.BoxFit.COVER)
    check("repeated banner refreshes do not replay the fade", not banner.set_source("next.jpg") and switcher.content is next_frame and repaint.call_count == 1)
    motion.set_level("reduced")
    banner.set_source("calm.jpg")
    check("reduced motion keeps only the permitted opacity transition", switcher.transition == ft.AnimatedSwitcherTransition.FADE and switcher.scale is None and switcher.offset is None)
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
    scope = inspect.getclosurevars(refresh).nonlocals
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
    functions = {}

    def collect(function):
        if not inspect.isfunction(function) or function.__name__ in functions:
            return
        functions[function.__name__] = function
        for value in inspect.getclosurevars(function).nonlocals.values():
            collect(value)

    for function in (refresh, load, browse_refresh):
        collect(function)
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
    check("deleted mods offer Download without rebuilding the row", not action.disabled and callable(action.on_click) and action.content.controls[1].value == "Download")
    check("download action width stays fixed while its label changes", action.width == 136 and action.height == 36)
    check("mod rows have no click shrink animation", not callable(row.on_tap_down))
    render = functions["_render_browse_page"]
    browse_scope = inspect.getclosurevars(render).nonlocals
    browse_scope["browse_state"].update(token=object(), page=0, paged=False, pages={0: [project]})
    render()
    browse_list = browse_scope["browse_results_view"]
    visible_rows = tuple(browse_list.controls)
    render()
    check("cached browse pages keep their mounted rows", tuple(browse_list.controls) == visible_rows)
    functions["_show_browse_loading"]()
    check("loading keeps the previous list height and icons", tuple(browse_list.controls) == visible_rows and browse_list.disabled)
    render()
    check("completed page loads re-enable the same controls", tuple(browse_list.controls) == visible_rows and not browse_list.disabled)
    initial, added, removed = ObjectPatch.from_diff(None, browse_list, BaseControl)
    msgpack.packb(initial.to_message(), default=encode)
    render()
    changes, added, removed = ObjectPatch.from_diff(browse_list, browse_list, BaseControl)
    encoded = msgpack.packb(changes.to_message(), default=encode)
    check("real browse refreshes neither remount nor retransmit icons", not added and not removed and b"src" not in encoded)

from ui.modpacks_tab import build_modpacks_tab

installed_pack = {"version_id": "fabric-loader-0.16-1.21.1", "mc_version": "1.21.1",
                  "loader": "fabric", "name": "Installed pack", "mod_count": 10,
                  "icon_url": "https://example.invalid/installed-pack.png"}
stubs.core.list_installed_modpacks = lambda: [dict(installed_pack)]
with patch("ui.modpacks_tab.threading.Thread", QueuedThread), patch.object(icons, "prefetch"):
    pack_root, refresh_packs, load_packs = build_modpacks_tab(
        page, {}, state, section_label=section_label, go_to_pack=lambda meta: None, **THEME)
    functions = {}
    for function in (refresh_packs, load_packs):
        collect(function)
    pack = {"project_id": "store-pack", "provider": "modrinth", "title": "Store pack",
            "description": "A pack", "downloads": 10, "versions": ["1.21.1"],
            "icon_url": "https://example.invalid/pack.png"}
    build_pack = functions["build_pack_row"]
    row = build_pack(pack, False)
    image = row.content.controls[0]
    check("modpack browse refreshes reuse rows and artwork", build_pack(dict(pack), False) is row and row.content.controls[0] is image)
    changed_pack = dict(pack, downloads=20)
    build_pack(changed_pack, False)
    check("new provider metadata updates without reloading pack artwork", row.content.controls[0] is image and "20 downloads" in row.content.controls[1].controls[2].value)
    build_pack(changed_pack, True)
    action = row.content.controls[-1]
    check("modpack install status changes preserve the row and icon", action.disabled and action.content.controls[1].value == "Installed" and row.content.controls[0] is image)
    state["selected_mc_version"] = "1.20.1"
    build_pack(changed_pack, False)
    check("Play-version changes update pack hints without reloading art", row.content.controls[0] is image and "installs its own" in row.content.controls[1].controls[2].value)
    check("pack action width stays fixed", action.width == 136 and action.height == 36)
    refresh_packs()
    pack_scope = inspect.getclosurevars(refresh_packs).nonlocals
    installed_list = pack_scope["installed_view"]
    saved_row = installed_list.controls[0]
    saved_image = saved_row.content.controls[0].content
    refresh_packs()
    check("installed modpack refreshes preserve the row and icon", installed_list.controls[0] is saved_row and saved_row.content.controls[0].content is saved_image)
    installed_pack["mod_count"] = 12
    refresh_packs()
    check("installed pack counts update without replacing artwork", saved_row.content.controls[0].content is saved_image and "12 mods" in saved_row.content.controls[1].controls[1].value)
    render = functions["_render_page"]
    pack_browse_scope = inspect.getclosurevars(render).nonlocals
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
