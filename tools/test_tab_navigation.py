"""Headless tab-cache and native-navigation animation regressions."""
import inspect
import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch as mock_patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft
import msgpack
from flet.controls.base_control import BaseControl
from flet.controls.object_patch import ObjectPatch
from flet.messaging.protocol import configure_encode_object_for_msgpack

import app_driver
from _fuzz_common import walk

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label} {detail}")


driver = app_driver.build_headless()
from cubeon.theme import hint_message
from cubeon import motion, thread_safe_ui
from cubeon.theme import ACCENT, TEXT_DIM

switch = inspect.getclosurevars(driver.tabs()["mods"].on_click).nonlocals["switch_tab"]
variables = inspect.getclosurevars(switch).nonlocals
host = variables["tab_switcher"]
views = variables["_tab_views"]
nav_buttons = variables["nav_buttons"]
active_tab = variables["active_tab"]
slider = variables['nav_slider']
marker = slider.marker
check('startup shows the small accent marker beside Play', marker.bgcolor == ACCENT
      and marker.width == 3 and marker.height == 22 and marker.opacity == 1
      and marker.offset.y * marker.height == 35)
check('marker animation changes paint offsets without animating layout',
      marker.animate_position is None and marker.on_size_change is None
      and marker.left == 5 and marker.top == 0 and marker.ignore_interactions)
check('the marker has its own noninteractive native paint viewport',
      slider.layer.ignore_interactions and isinstance(slider.layer.content, ft.ListView)
      and slider.layer.content.controls == [slider.paint_area]
      and marker in slider.paint_area.content.controls)
ObjectPatch.from_diff(None, marker, BaseControl)
updates = []
frames = []
pane_repaints = []


def record_update(*controls):
    updates.append(controls)
    frames.append([(key, view.opacity) for key, view in views.items() if view.visible])


driver.page.update = record_update
original_refresh = thread_safe_ui.refresh


def record_refresh(control):
    if control is host or any(control is view for view in views.values()):
        pane_repaints.append(control)
    original_refresh(control)


thread_safe_ui.refresh = record_refresh
encode = configure_encode_object_for_msgpack(BaseControl)


def flush_host(initial=False):
    with thread_safe_ui.update_scope(host):
        patch, added, removed = ObjectPatch.from_diff(None if initial else host, host, BaseControl)
    encoded = msgpack.packb(patch.to_message(), default=encode)
    return patch, added, removed, encoded

check("tab host keeps panes in a Stack", isinstance(host, ft.Stack))
check("startup only mounts Play", list(views) == ["play"] and len(host.controls) == 1)
host_list = host.controls
play_view = views["play"]
flush_host(initial=True)

print("\n1. a tab is added once, then only its visibility changes")
switch("mods")
patch, added, removed, encoded = flush_host()
check("first Mods visit adds its controls", bool(added))
tab_callbacks = inspect.getclosurevars(variables["_ensure_tab"]).nonlocals["_tab_cbs"]
check("first Mods visit leaves Modpacks unbuilt", "modpacks" not in tab_callbacks)
check("first visit does not remove Play", not removed)
settings_view = views["mods"]
settings_controls = tuple(id(control) for control in walk(settings_view))
play_controls = tuple(id(control) for control in walk(play_view))
# The Mods tab legitimately refreshes its list on entry; measure the shell
# repaint on the way back to Play, where only the pane swap should happen.
updates.clear()
frames.clear()
pane_repaints.clear()
switch("play")
patch, added, removed, encoded = flush_host()
check("navigation uses one scoped repaint", len(updates) == 1 and bool(updates[0]))
check("navigation repaints the isolated pane Stack, not a pane's descendants",
      host in updates[0] and all(view not in updates[0] for view in views.values())
      and host._shell_only)
check("content is visible in the first frame, without another pane diff",
      frames == [[("play", 1.0)]] and not pane_repaints)
check('the marker shares the shell paint without adding a frame', marker in updates[0])
check("both changed top-bar buttons repaint",
      {id(control) for control in updates[0] if control in nav_buttons.values()}
      == {id(nav_buttons["play"]), id(nav_buttons["mods"])})

durations = []
patch_sizes = []
for key in ("play", "mods", "play", "mods"):
    started = time.perf_counter()
    switch(key)
    patch, added, removed, encoded = flush_host()
    durations.append((time.perf_counter() - started) * 1000)
    patch_sizes.append(len(encoded))
    if key == "play":
        check(f"revisit {key}: no controls remount", not added and not removed)
    check(f"revisit {key}: no image source retransmits", b"src" not in encoded)
    check(f"revisit {key}: exactly one pane is visible",
          [name for name, view in views.items() if view.visible] == [key])

check("cached pane wrappers remain the same objects",
      views["play"] is play_view and views["mods"] is settings_view)
check("cached Play controls are unchanged",
      tuple(id(control) for control in walk(play_view)) == play_controls)
check("host list is mutated, never replaced", host.controls is host_list)
print(f"  cached switch + real Flet diff: {max(durations):.2f} ms maximum")
print(f"  cached pane-switch patch: {max(patch_sizes)} bytes maximum")

print("\n2. repeated and invalid navigation are no-ops")
mods_icon = nav_buttons['mods'].content
check("Mods uses Flet's extension icon", isinstance(mods_icon, ft.Icon)
      and mods_icon.icon == ft.Icons.EXTENSION_ROUNDED and mods_icon.color == ACCENT)
for key, glyph in {'play': ft.Icons.PLAY_ARROW_ROUNDED, 'profile': ft.Icons.PALETTE_ROUNDED,
                   'stats': ft.Icons.BAR_CHART_ROUNDED, 'server': ft.Icons.DNS_ROUNDED,
                   'settings': ft.Icons.SETTINGS_ROUNDED,
                   'chat': ft.Icons.CHAT_BUBBLE_ROUNDED}.items():
    button = nav_buttons.get(key)
    if button is None:
        continue
    icon = button.content
    check(f"{key} uses a Flet icon with the correct selection color", isinstance(icon, ft.Icon)
          and icon.icon == glyph and icon.color == (ACCENT if button.data else TEXT_DIM)
          and icon.size == 22
          and button.cubeon_keyboard_button is not None)
for hovering in ('true', 'false'):
    switch('play')
    # This fixture mounts the pane host, not the rail, so mock only its paint.
    with mock_patch.object(ft.Container, 'update'):
        nav_buttons['mods'].on_hover(SimpleNamespace(control=nav_buttons['mods'], data=hovering))
    check("Mods hover keeps its native glyph and geometry", mods_icon.size == 22
          and mods_icon.icon == ft.Icons.EXTENSION_ROUNDED)
switch('mods')
check("Mods selection preserves the same icon", nav_buttons['mods'].content is mods_icon
      and mods_icon.color == ACCENT)
updates.clear()
switch("mods")
switch("not-a-tab")
patch, added, removed, encoded = flush_host()
check("same-tab/invalid clicks send no repaint", not updates)
check("same-tab/invalid clicks leave state unchanged", active_tab["value"] == "mods")
check("same-tab/invalid clicks keep the cached wrappers",
      views["play"] is play_view and views["mods"] is settings_view)

print("\n2a. Settings is a retained tab")
switch("settings")
settings_pane = views["settings"]
settings_tree = tuple(id(control) for control in walk(settings_pane))
check("Settings is the only visible launcher pane",
      active_tab["value"] == "settings"
      and [key for key, pane in views.items() if pane.visible] == ["settings"])
switch("mods")
check("leaving Settings hides its retained pane", not settings_pane.visible)
switch("settings")
check("returning to Settings preserves the pane and its fields",
      views["settings"] is settings_pane
      and tuple(id(control) for control in walk(settings_pane)) == settings_tree)

print("\n2b. the compact profile-strip button opens retained Screenshots")
before = active_tab["value"]
picture_button = next(control for control in walk(driver.page)
                      if getattr(control, "data", None) == "screenshots-button")
picture_button.on_click(None)
check("Screenshots uses a small native picture button",
      isinstance(picture_button, ft.IconButton)
      and picture_button.width == 32 and picture_button.height == 32
      and hint_message(picture_button.tooltip) == "Screenshots")
check("Screenshots opens its own visible page",
      [key for key, pane in views.items() if pane.visible] == ["screenshots"])
gallery_pane = views["screenshots"]
back = next(control for control in walk(gallery_pane)
            if getattr(control, "data", None) == "screenshots-back")
back.on_click(None)
check("Screenshots Back returns to the destination that opened it",
      active_tab["value"] == before and not gallery_pane.visible)
picture_button.on_click(None)
check("reopening Screenshots retains its page", views["screenshots"] is gallery_pane)

print("\n2c. a stray visible pane can never survive a switch")
# The 2026-10-25 "Play and Modpacks both visible" report: one interrupted
# transition left an old pane visible, and every later switch only hid the
# immediate previous pane - so the stale one stayed on screen forever.
views["play"].visible = True
switch("stats")
check("switching hides every non-active pane, not just the previous one",
      [name for name, view in views.items() if view.visible] == ["stats"])

# Tab switches can also arrive from a worker thread (go_to_pack after a
# modpack install), so two switches can genuinely be in flight at once.
errors = []
barrier = threading.Barrier(4)


def _hammer(keys):
    try:
        barrier.wait()
        for key in keys:
            switch(key)
    except Exception as exc:  # pragma: no cover - surfaced in the check
        errors.append(exc)


threads = [threading.Thread(target=_hammer,
                            args=(("play", "modpacks", "mods", "play"),))
           for _ in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
visible = [name for name, view in views.items() if view.visible]
check("concurrent switches raise nothing", not errors, str(errors[:2]))
check("concurrent switches still leave exactly one pane visible",
      len(visible) == 1, str(visible))

print("\n3. selection highlights the icon and moves only the marker's paint")
for key in ('play', 'mods', 'modpacks', 'play', 'mods'):
    switch(key)
check('the selected icon uses the accent', nav_buttons['mods'].content.color == ACCENT)
check('there is no colored tile or border around the active icon',
      nav_buttons['mods'].bgcolor == 'transparent' and nav_buttons['mods'].border is None)
with mock_patch.object(ft.Container, 'update') as paint, mock_patch.object(ft.context, 'disable_auto_update') as no_auto:
    for hovering in ('true', 'false'):
        nav_buttons['mods'].on_hover(SimpleNamespace(control=nav_buttons['mods'], data=hovering))
        check('hover preserves icon-only selection',
              nav_buttons['mods'].content.color == ACCENT and nav_buttons['mods'].bgcolor == 'transparent')
    check('active hover disables automatic full-page diffs', no_auto.call_count == 2 and not paint.called)
check('keyboard focus uses a neutral outline',
      nav_buttons['mods'].cubeon_keyboard_button.style.side[ft.ControlState.FOCUSED].color == TEXT_DIM)
check('leaving a tab restores its neutral icon color', nav_buttons['play'].content.color == TEXT_DIM)
check('selection keeps every icon stationary',
      all(button.content.scale is None and button.content.animate_scale is None
          for button in nav_buttons.values() if getattr(button, 'cubeon_top_icon', False)))
check('the old colored slider is removed', 'nav_blob' not in variables)
check('selection moves the marker beside Mods using the native transform',
      marker.offset.y * marker.height == 85 and marker.animate_offset.duration == 120)
marker_patch, marker_added, marker_removed = ObjectPatch.from_diff(marker, marker, BaseControl)
marker_bytes = msgpack.packb(marker_patch.to_message(), default=encode)
check('moving the marker sends no layout change, artwork or remount',
      not marker_added and not marker_removed and b'offset' in marker_bytes
      and all(field not in marker_bytes for field in (b'top', b'height', b'width', b'src')))
motion.set_level('reduced')
switch('play')
check('reduced motion preserves the icon highlight', nav_buttons['play'].content.color == ACCENT)
check('reduced motion snaps the same marker', marker.offset.y * marker.height == 35
      and marker.animate_offset.duration == 0)
motion.set_level('full')
switch('mods')
check('full motion keeps the same cached pane', views['mods'] is settings_view)
check('full motion restores native offset tweening', marker.animate_offset.duration == 120)
rail_scroll = next(control for control in walk(driver.page)
                   if getattr(getattr(control, 'on_scroll', None), '__name__', '') == '_on_nav_scroll')
scroll_paints = []
# Other metadata workers may repaint concurrently; count calls made by this
# handler on the test thread, including any accidental whole-page refresh.
scroll_thread = threading.get_ident()
def record_scroll_paint(control):
    if threading.get_ident() == scroll_thread:
        scroll_paints.append(control)
with mock_patch.object(thread_safe_ui, 'refresh', side_effect=record_scroll_paint):
    for _ in range(20):
        rail_scroll.on_scroll(SimpleNamespace(pixels=0))
    check('unchanged native scroll events cause no repaint', not scroll_paints)
    rail_scroll.on_scroll(SimpleNamespace(pixels=30))
    check('real scrolling keeps the marker beside its icon with one scoped paint',
          marker.offset.y * marker.height == 55 and scroll_paints == [marker] and marker.animate_offset.duration == 0)
    rail_scroll.on_scroll(SimpleNamespace(pixels=100))
    check('a scrolled-out selection hides its marker', marker.opacity == 0)
    rail_scroll.on_scroll(SimpleNamespace(pixels=0))
    check('scrolling back restores the correct marker', marker.opacity == 1
          and marker.offset.y * marker.height == 85)
switch('settings')
slider.resize(450)
check('existing window geometry keeps the marker aligned with pinned Settings',
      marker.offset.y * marker.height == 405 and marker.animate_offset.duration == 0
      and slider.paint_area.height == 450 and not slider.resize(450)
      and not slider.resize(-44))
switch('screenshots')
check('off-rail destinations hide the marker', marker.opacity == 0)

print("\n4. lazy content and server navigation still work")
switch("mods")
mods_text = [getattr(control, "value", "") for control in walk(views["mods"])]
check("lazy Mods tab actually builds", "Resource Packs" in mods_text and "Shaders" in mods_text)
switch("server")
check("Servers entry stores the canonical Settings tab", active_tab["value"] == "server_settings")
switch("server_plugins")
check("server chip switches the visible pane",
      [name for name, view in views.items() if view.visible] == ["server_plugins"])
check("server sub-tabs keep Servers highlighted", nav_buttons['server'].content.color == ACCENT)
server_offset = marker.offset.y
switch('server_console')
check('Server chips share one stationary rail marker', marker.offset.y == server_offset
      and marker.opacity == 1)
switch("server")
check("Servers entry returns to the cached Settings pane", views["server_settings"].visible)
check("server chip row stays visible", variables["subnav_bar"].visible)
switch("play")
check("leaving Servers hides the chip row", not variables["subnav_bar"].visible)
for key in ("profile", "stats", "chat", "server_settings"):
    switch(key)
    check(f"{key}: cached pane mounts and is the only visible pane",
          [name for name, view in views.items() if view.visible] == [key]
          and (not isinstance(views[key].content, ft.Container)
               or views[key].content.content is not None))
check("Servers has no Browse navigation entry", "server_browse" not in driver.tabs())

# Chat keeps its tooltip and keyboard label on the existing icon-only rail.
_chat_btn = nav_buttons.get("chat")
if _chat_btn is not None:
    _chat_texts = [getattr(control, "value", "")
                   for control in walk(_chat_btn)]
    check("Chat is a first-class sidebar entry", hint_message(_chat_btn.tooltip) == "Chat"
          and _chat_btn.cubeon_keyboard_button is not None)
    check("the sidebar BETA chip stays gone",
          "BETA" not in _chat_texts, str(_chat_texts))
    switch("chat")
    check("Chat retains its active rail tile",
          getattr(_chat_btn, "cubeon_top_icon", False) and _chat_btn.data is True,
          type(_chat_btn.content).__name__)
    check("Chat still styles as active",
          _chat_btn.data is True
          and _chat_btn.content.opacity == 1 and _chat_btn.content.color == ACCENT)
check("server browser UI and backend are removed",
      all(not os.path.exists(os.path.join(app_driver.REPO, filename))
          for filename in ("ui/server_browse_tab.py", "cubeon/server_browse.py")))

owners = {}
duplicates = []
for key, view in views.items():
    for control in walk(view):
        previous_owner = owners.setdefault(id(control), key)
        if previous_owner != key:
            duplicates.append((previous_owner, key, type(control).__name__))
check("cached panes never mount the same control in two parents", not duplicates, str(duplicates[:3]))

print("\n5. the sidebar is a fixed-width icon rail")

main_src = open(os.path.join(app_driver.REPO, "main.py"), encoding="utf-8").read()
splitter = next((control for control in walk(driver.page)
                 if type(control).__name__ == "GestureDetector"
                 and getattr(control, "mouse_cursor", None)
                 == ft.MouseCursor.RESIZE_LEFT_RIGHT), None)
check("the drag-to-resize edge is gone", splitter is None)
check("the rail has one designed width",
      "SIDEBAR_W = 64" in main_src
      and "def _set_sidebar_width" not in main_src)
check("nav tiles retain the icon-only rail layout",
      getattr(nav_buttons["mods"], "cubeon_top_icon", False)
      and isinstance(nav_buttons["mods"].content, ft.Icon)
      and hint_message(nav_buttons["mods"].tooltip) == 'Mods')
check("the old collapse affordance stays gone",
      not any((hint_message(getattr(control, "tooltip", "")) or "").lower().startswith(
                  ("collapse sidebar", "expand sidebar", "toggle sidebar"))
              for control in walk(driver.page)))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
