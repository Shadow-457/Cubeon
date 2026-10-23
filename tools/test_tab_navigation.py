"""Headless tab-cache and native-navigation animation regressions."""
import inspect
import os
import sys
import time

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
from cubeon import motion

switch = inspect.getclosurevars(driver.tabs()["mods"].on_click).nonlocals["switch_tab"]
variables = inspect.getclosurevars(switch).nonlocals
host = variables["tab_switcher"]
views = variables["_tab_views"]
nav_buttons = variables["nav_buttons"]
blob = variables["nav_blob"]
active_tab = variables["active_tab"]
updates = []
driver.page.update = lambda *controls: updates.append(controls)
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
switch("settings")
patch, added, removed, encoded = flush_host()
check("first Settings visit adds its controls", bool(added))
check("first visit does not remove Play", not removed)
settings_view = views["settings"]
settings_controls = tuple(id(control) for control in walk(settings_view))
check("navigation uses one scoped repaint", len(updates) == 1 and bool(updates[0]))
check("Settings gear hides the top-bar highlight", blob.opacity == 0)
check("only the changed top-bar button repaints",
      {id(control) for control in updates[0] if control in nav_buttons.values()}
      == {id(nav_buttons["play"])})

durations = []
patch_sizes = []
for key in ("play", "settings", "play", "settings"):
    started = time.perf_counter()
    switch(key)
    patch, added, removed, encoded = flush_host()
    durations.append((time.perf_counter() - started) * 1000)
    patch_sizes.append(len(encoded))
    check(f"revisit {key}: no controls remount", not added and not removed)
    check(f"revisit {key}: no image source retransmits", b"src" not in encoded)
    check(f"revisit {key}: exactly one pane is visible",
          [name for name, view in views.items() if view.visible] == [key])

check("cached pane wrappers remain the same objects",
      views["play"] is play_view and views["settings"] is settings_view)
check("cached Settings controls are unchanged",
      tuple(id(control) for control in walk(settings_view)) == settings_controls)
check("host list is mutated, never replaced", host.controls is host_list)
print(f"  cached switch + real Flet diff: {max(durations):.2f} ms maximum")
print(f"  cached pane-switch patch: {max(patch_sizes)} bytes maximum")

print("\n2. repeated and invalid navigation are no-ops")
updates.clear()
switch("settings")
switch("not-a-tab")
patch, added, removed, encoded = flush_host()
check("same-tab/invalid clicks send no repaint", not updates)
check("same-tab/invalid clicks leave state unchanged", active_tab["value"] == "settings")
check("same-tab/invalid clicks keep the cached wrappers",
      views["play"] is play_view and views["settings"] is settings_view)

print("\n3. highlight motion is a single client-side transform")
for key in ("play", "mods", "modpacks", "play", "mods"):
    switch(key)
top_keys = [key for key, button in nav_buttons.items() if getattr(button, "cubeon_top_icon", False)]
expected_offset = top_keys.index("mods") * (50 + 6) / 50
check("rapid navigation lands on the latest icon", blob.offset.x == expected_offset)
check("highlight never stretches/reflows", blob.width == 50 and blob.left == 0)
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
      blob.animate_offset is not None and views["settings"] is settings_view)

print("\n4. lazy content and server navigation still work")
switch("mods")
mods_text = [getattr(control, "value", "") for control in walk(views["mods"])]
check("lazy Mods tab actually builds", "Resource Packs" in mods_text and "Shaders" in mods_text)
switch("server")
check("Servers entry stores the canonical Console tab", active_tab["value"] == "server_console")
server_offset = blob.offset.x
switch("server_plugins")
check("server chip switches the visible pane",
      [name for name, view in views.items() if view.visible] == ["server_plugins"])
check("server chips keep the same top-bar highlight", blob.offset.x == server_offset)
switch("server")
check("Servers entry returns to the cached Console pane", views["server_console"].visible)
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

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
