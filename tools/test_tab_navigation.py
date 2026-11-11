"""Headless tab-cache and native-navigation animation regressions."""
import inspect
import os
import sys
import threading
import time
from types import SimpleNamespace

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
from cubeon import motion, thread_safe_ui

switch = inspect.getclosurevars(driver.tabs()["mods"].on_click).nonlocals["switch_tab"]
variables = inspect.getclosurevars(switch).nonlocals
host = variables["tab_switcher"]
views = variables["_tab_views"]
nav_buttons = variables["nav_buttons"]
blob = variables["nav_blob"]
active_tab = variables["active_tab"]
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
check("content is visible in the first frame, without another pane diff",
      frames == [[("play", 1.0)]] and not pane_repaints)
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
      and picture_button.tooltip == "Screenshots")
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

print("\n3. highlight motion is a single client-side transform")
for key in ("play", "mods", "modpacks", "play", "mods"):
    switch(key)
top_keys = [key for key, button in nav_buttons.items() if getattr(button, "cubeon_top_icon", False)]
_move_vars = inspect.getclosurevars(variables["_move_nav_blob"]).nonlocals
nav_h, nav_gap = _move_vars["NAV_BTN_H"], _move_vars["NAV_GAP"]
expected_offset = top_keys.index("mods") * (nav_h + nav_gap) / blob.height
check("rapid navigation lands on the latest icon", blob.offset.y == expected_offset)
check("the selection is a slim, centered accent bar",
      blob.width == 3 and blob.height == 40 and blob.top == (nav_h - blob.height) / 2
      and blob.ignore_interactions)
check("active rail tiles stay clear behind the slider",
      nav_buttons["mods"].bgcolor == "transparent")
check("highlight uses the same native animation as the icons",
      blob.animate_offset is nav_buttons["mods"].content.controls[0].animate_scale)
check("highlight has no timer-delayed settle",
      "Timer" not in inspect.getsource(variables["_move_nav_blob"]))
motion.set_level("reduced")
switch("play")
check("reduced motion disables highlight movement animation", blob.animate_offset is None)
check("reduced motion disables icon/underline movement animations",
      all(control.animate_scale is None for control in nav_buttons["play"].content.controls))
motion.set_level("full")
switch("mods")
check("full motion restores native animation without rebuilding",
      blob.animate_offset is not None and views["mods"] is settings_view)

print("\n4. lazy content and server navigation still work")
switch("mods")
mods_text = [getattr(control, "value", "") for control in walk(views["mods"])]
check("lazy Mods tab actually builds", "Resource Packs" in mods_text and "Shaders" in mods_text)
switch("server")
check("Servers entry stores the canonical Settings tab", active_tab["value"] == "server_settings")
server_offset = blob.offset.y
switch("server_plugins")
check("server chip switches the visible pane",
      [name for name, view in views.items() if view.visible] == ["server_plugins"])
check("server chips keep the same sidebar highlight", blob.offset.y == server_offset)
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

# Chat keeps an icon and label; the retained marker supplies selection.
_chat_btn = nav_buttons.get("chat")
if _chat_btn is not None:
    _chat_texts = [getattr(control, "value", "")
                   for control in walk(_chat_btn)]
    check("Chat is a first-class sidebar entry", "Chat" in _chat_texts,
          str(_chat_texts))
    check("the sidebar BETA chip stays gone",
          "BETA" not in _chat_texts, str(_chat_texts))
    switch("chat")
    check("Chat retains its active rail tile",
          getattr(_chat_btn, "cubeon_top_icon", False) and _chat_btn.data is True,
          str([type(c).__name__ for c in _chat_btn.content.controls]))
    check("Chat still styles as active",
          _chat_btn.data is True
          and _chat_btn.content.controls[1].weight == ft.FontWeight.W_700)
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
      "SIDEBAR_W = 92" in main_src
      and "def _set_sidebar_width" not in main_src)
check("nav tiles are icon-over-label rail tiles",
      getattr(nav_buttons["mods"], "cubeon_top_icon", False)
      and len(nav_buttons["mods"].content.controls) == 2)
check("the old collapse affordance stays gone",
      not any((getattr(control, "tooltip", "") or "").lower().startswith(
                  ("collapse sidebar", "expand sidebar", "toggle sidebar"))
              for control in walk(driver.page)))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
