#!/usr/bin/env python3
"""
Play tab version management UI (ui/versions.py + cubeon/instances.py).

Boots the REAL launcher headless under the safe stubs with two fake installed
versions - a plain vanilla and a Fabric loader install carrying two mods - and
checks the three things this feature added:

  1. the Game-version control opens a right-hand side panel (not a dialog)
     that lists installed instances and tags available rows with their
     loader / release date; its search filters its own list;
  2. the "Your instances" rows carry loader + mod-count + last-played text
     and stay plain (no per-row art controls);
  3. the same panel manages every install (Play / Rename / Delete).

No window, no network, no real install.

Run: python3 tools/test_version_ui.py
"""
import inspect
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _sandbox_home                                          # noqa: E402
_sandbox_home.isolate()

import _fuzz_common as fz                                     # noqa: E402
from _fuzz_common import every_control, subtree_text, walk    # noqa: E402
from _fuzz_common import ctrl_text                            # noqa: E402
import app_driver                                             # noqa: E402

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


FABRIC_ID = "fabric-loader-0.19.5-26.1.2"
INSTALLED = [
    {"id": "1.21.11", "type": "release", "display_name": "1.21.11", "folder": "1.21.11"},
    {"id": FABRIC_ID, "type": "release", "display_name": "26.1.2 (Fabric)",
     "folder": FABRIC_ID},
]
# Deliberately does NOT contain FABRIC_ID: an isolated/imported instance has a
# launch id Mojang's manifest has never heard of. Browsing the online list must
# still keep it selected instead of silently jumping to the latest release.
AVAILABLE = [
    {"id": "1.21.11", "type": "release", "releaseTime": "2024-06-13T00:00:00+00:00"},
    {"id": "1.8", "type": "release", "releaseTime": "2014-09-02T00:00:00+00:00"},
    {"id": "1.20.1", "type": "release", "releaseTime": "2023-06-07T00:00:00+00:00"},
    {"id": "26w45a", "type": "snapshot", "releaseTime": "2024-11-06T00:00:00+00:00"},
]

stubs = fz.install_safe_stubs()
stubs.core.get_installed_versions = lambda *a, **k: list(INSTALLED)
stubs.core.get_available_versions = lambda *a, **k: list(AVAILABLE)

from cubeon import instances as instance_info                 # noqa: E402
from cubeon.mod_loaders import find_installed_loader_version
import cubeon.mods as mods_mod                                # noqa: E402

# Two mods in the Fabric (26.1.2) profile so the card shows a count. The stub
# layer redirects get_profile_dir into a throwaway temp dir; list_mods reads
# resolve_profile_dir, so seed that (both are under the sandbox HOME anyway).
profile = mods_mod.resolve_profile_dir("26.1.2", "fabric")
os.makedirs(profile, exist_ok=True)
for name in ("sodium.jar", "lithium.jar"):
    with open(os.path.join(profile, name), "wb") as fh:
        fh.write(b"j")
# And a launch one hour ago so the card has a "last played" chip.
instance_info.mark_played(FABRIC_ID, when=time.time() - 3600)

page = app_driver.DriverPage()
stubs.app.run_sync(page)
driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)
driver.open_tab("play")

picker_btn = fz.clickable_with_subtext(page, "pick a minecraft version")
check("the Game-version button exists", bool(picker_btn))
picker_model = (inspect.getclosurevars(picker_btn[0].on_click).nonlocals["self"]
                if picker_btn else None)
if picker_model:
    picker_model.open()
panel = picker_model.panel if picker_model else None

print("\n1. the version panel's cards carry loader / mods / last-played text")


def find_cards():
    """The panel's instance cards, tagged ``version-panel-row-<version id>``."""
    out = {}
    if panel is None:
        return out
    for c in walk(panel):
        data = getattr(c, "data", None)
        if isinstance(data, str) and data.startswith("version-panel-row-"):
            out[data[len("version-panel-row-"):]] = c
    return out


cards = find_cards()
check("one card per installed version", set(cards) == {"1.21.11", FABRIC_ID},
      f"found {sorted(cards)}")

fabric_text = subtree_text(cards[FABRIC_ID]) if FABRIC_ID in cards else ""
check("the Fabric card is tagged with its loader", "fabric" in fabric_text,
      fabric_text[:160])
check("the Fabric card shows its mod count", "2 mods" in fabric_text,
      fabric_text[:160])
check("the Fabric card shows when it was last played", "ago" in fabric_text,
      fabric_text[:160])
vanilla_text = subtree_text(cards["1.21.11"]) if "1.21.11" in cards else ""
check("the vanilla card is not mislabelled as a loader install",
      "fabric" not in vanilla_text and "mods" not in vanilla_text,
      vanilla_text[:160])
check("the Play tab itself mounts no instance cards",
      not [c for c in every_control(page)
           if isinstance(getattr(c, "data", None), str)
           and c.data.startswith("instance-row-")])

print("\n2. the version picker switches between installed and new instances")

selection_scope = None
if picker_model and FABRIC_ID in cards and "1.21.11" in cards:
    # The panel's on_pick is main.py's `_pick_version`, which restores the
    # instance's own loader and then calls `_select_version_ui` ->
    # `on_version_selected`. Grab the selection handler through that chain so
    # the test keeps exercising the real repaint path.
    pick_scope = inspect.getclosurevars(picker_model.on_pick).nonlocals
    selection_handler = pick_scope.get("on_version_selected")
    if selection_handler is None:
        selection_handler = inspect.getclosurevars(
            pick_scope["_select_version_ui"]).nonlocals["on_version_selected"]
    selection_scope = inspect.getclosurevars(selection_handler).nonlocals
    selection_state = selection_scope["state"]
    loader_scope = inspect.getclosurevars(selection_scope["refresh_loader_support"]).nonlocals
    loader_control = loader_scope["loader_toggle"]
    status_slots = [control for control in every_control(page) if control.data == "play-loader-status"]
    check("loader notices have a fixed-height slot in the Play card",
          len(status_slots) == 1 and status_slots[0].height == 18
          and status_slots[0].content is loader_scope["loader_status_text"])
    hero_scope = inspect.getclosurevars(selection_scope["update_hero"]).nonlocals
    check("long Jump Back In names cannot wrap the Play header",
          hero_scope["hero_title"].max_lines == 1 and hero_scope["hero_title"].expand
          and hero_scope["hero_version_text"].max_lines == 1 and hero_scope["hero_version_text"].expand)
    loader_ids = list(stubs.core.SUPPORTED_LOADERS)
    loader_scope["loader_check_cache"]["1.21.11"] = {
        loader: (True, False) for loader in loader_ids if loader != "vanilla"
    }
    loader_scope["loader_check_cache"][FABRIC_ID] = {
        loader: (True, loader == "fabric") for loader in loader_ids if loader != "vanilla"
    }
    with patch.object(stubs.core, "find_installed_loader_version", find_installed_loader_version):
        selection_state["mod_loader"] = "vanilla"
        loader_control.selected_index = loader_ids.index("vanilla")
        cards[FABRIC_ID].on_click(None)
        check("Quick Jump selects the Fabric instance's loader", selection_state["mod_loader"] == "fabric")
        check("Quick Jump updates the loader toggle", loader_control.selected_index == loader_ids.index("fabric"))
        check("Jump Back In keeps the loader-status region's height", status_slots[0].height == 18)
        check("Quick Jump uses the Fabric instance's base version", selection_state["selected_mc_version"] == "26.1.2")
        cards["1.21.11"].on_click(None)
        check("Quick Jump back to Vanilla clears the Fabric selection", selection_state["mod_loader"] == "vanilla")
        picker_model.on_pick(FABRIC_ID)
        check("the version picker also selects the installed instance's loader", selection_state["mod_loader"] == "fabric")
        loader_control.selected_index = loader_ids.index("vanilla")
        loader_control.on_change(SimpleNamespace(control=loader_control))
        check("an explicit loader toggle is not overridden by a refresh", selection_state["mod_loader"] == "vanilla")
        selection_state["pending_loader_install"] = {"version_id": FABRIC_ID, "loader": "forge"}
        cards[FABRIC_ID].on_click(None)
        check("selecting an installed instance cancels a stale pending loader choice",
              selection_state["pending_loader_install"] is None and selection_state["mod_loader"] == "fabric")
        # Leave the instance-only id selected so the online browse below proves
        # the manifest merge keeps it (it is not in AVAILABLE at all).
        picker_model.on_pick(FABRIC_ID)
if picker_btn:
    driver._fire_named(picker_btn[0], "on_click", "open version picker")


panel = picker_model.panel
check("the version control opens a side panel, not a dialog",
      picker_model.is_open() and panel.data == "versions-panel"
      and not any(getattr(d, "title", None) is not None
                  and getattr(d.title, "value", "") == "Choose version"
                  for d in getattr(page, "opened", [])))
check("the panel starts on the installed list", picker_model.title.value == "Instances",
      picker_model.title.value)


def picker_row_ids(picker):
    """Ids of the rows currently rendered in the picker's own list."""
    ids = []
    for c in getattr(picker, "list", SimpleNamespace(controls=[])).controls:
        defaults = getattr(getattr(c, "on_click", None), "__defaults__", None)
        if isinstance(defaults, tuple) and defaults:
            ids.append(defaults[0])
    return ids


def picker_group_headers(control):
    """Visible section headers ('Installed' / 'Available to download')."""
    return [(c.value or "") for c in walk(control)
            if type(c).__name__ == "Text"
            and (c.value or "").strip().lower() in ("installed", "available to download")
            and getattr(c, "visible", True)]


installed_panel_text = subtree_text(panel)
check("installed rows are listed without group headers",
      "1.21.11" in installed_panel_text and "26.1.2" in installed_panel_text
      and not picker_group_headers(panel),
      str(picker_group_headers(panel)) + " " + installed_panel_text[:160])

# "New instance" pulls the online list and switches the panel to new-only rows.
browse = [c for c in walk(panel)
          if callable(getattr(c, "on_click", None))
          and "new instance" in subtree_text(c).lower()]
check("the panel offers 'New instance'", bool(browse))
if browse:
    driver._fire_named(browse[-1], "on_click", "browse new instances")
    check("new instance starts with only the loader step",
          picker_model._new_step == 1 and picker_model.loader_row.visible
          and not picker_model.list.visible and not picker_model.filter_field.visible)
    picker_model._next()
    deadline = time.monotonic() + 3
    from cubeon import thread_safe_ui
    while time.monotonic() < deadline:
        with thread_safe_ui.TREE_LOCK:
            if not picker_model._loading and not picker_model._support_loading:
                break
        time.sleep(0.01)

check("browsing switches the panel to the new-instance view",
      picker_model.title.value == "New instance", picker_model.title.value)

new_ids = picker_row_ids(picker_model)
check("new mode offers only versions that are not installed yet",
      set(new_ids) == {"1.20.1", "26w45a"}, str(sorted(new_ids)))
picker_model._set_install_loader("fabric")
def wait_for_versions():
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with thread_safe_ui.TREE_LOCK:
            if not picker_model._loading and not picker_model._support_loading:
                return
        time.sleep(0.01)
    raise AssertionError("version choices did not finish loading")
wait_for_versions()
check("an installed vanilla base is available for a new Fabric instance",
      "1.21.11" in picker_row_ids(picker_model))
picker_model._set_install_loader("vanilla")
wait_for_versions()
check("switching back to Vanilla hides its already installed base",
      "1.21.11" not in picker_row_ids(picker_model))
panel_text = subtree_text(panel)
check("new mode has no Installed / Available group headers",
      not picker_group_headers(panel),
      str(picker_group_headers(panel)) + " " + panel_text[:160])
check("rows carry a release date", "2023-06-07" in panel_text, panel_text[:200])
check("snapshots are badged", "snapshot" in panel_text, panel_text[:200])
check("the manifest merge keeps an installed-only id selected",
      selection_scope["version_dropdown"].value == FABRIC_ID,
      selection_scope["version_dropdown"].value)

# Legacy and loader support are separate gates: enabling Legacy must expose 1.8 Vanilla.
check("1.8 stays hidden before Legacy is enabled", "1.8" not in picker_row_ids(picker_model))
refresh_versions = inspect.getclosurevars(picker_model.on_browse_online).nonlocals["refresh_version_list"]
selection_state["legacy_ok"] = True
refresh_versions(online=True)
wait_for_versions()
check("Legacy exposes exact 1.8 for Vanilla download", "1.8" in picker_row_ids(picker_model))
picker_model._loader_versions["fabric"] = {"1.20.1", "1.21.11"}
picker_model._set_install_loader("fabric")
wait_for_versions()
picker_model.filter_field.value = "1.8"
picker_model.rebuild()
check("unsupported loader explains why 1.8 is unavailable",
      "no matching versions for fabric" in subtree_text(panel).lower())
picker_model._set_install_loader("vanilla")
wait_for_versions()
check("switching to Vanilla restores 1.8", "1.8" in picker_row_ids(picker_model))
picker_model.filter_field.value = "1.21.11"
picker_model.rebuild()
check("installed search explains where to play the existing instance",
      "already installed" in subtree_text(panel).lower())
picker_model.filter_field.value = ""
selection_state["legacy_ok"] = False
refresh_versions(online=True)
wait_for_versions()

# The search must narrow the panel's own list without touching the dropdown.
filters = [c for c in walk(panel)
           if type(c).__name__ == "TextField"
           and "filter versions" in (getattr(c, "hint_text", "") or "").lower()]
check("the panel has a filter field", bool(filters))
if filters:
    filters[0].value = "1.20"
    driver._fire_named(filters[0], "on_change", "filter versions")
    filtered_ids = picker_row_ids(picker_model)
    check("filtering hides non-matching rows",
          set(filtered_ids) == {"1.20.1"}, str(sorted(filtered_ids)))
    check("filtering never rewrites the live dropdown value",
          not driver.errors and selection_scope["version_dropdown"].value == FABRIC_ID,
          str(driver.errors[:2]))

# Back to the installed list.
back = [c for c in walk(panel)
        if callable(getattr(c, "on_click", None))
        and subtree_text(c).strip() == "back"]
if back:
    driver._fire_named(back[0], "on_click", "back to installed versions")
    check("Back first returns to loader selection", picker_model._new_step == 1)
    picker_model._back()
check("Back returns the panel to the installed list",
      picker_model.title.value == "Instances", picker_model.title.value)

print("\n3. the same panel manages every install")

panel_rows = [c for c in walk(panel)
              if isinstance(getattr(c, "data", None), str)
              and c.data.startswith("version-panel-row-")]
check("the panel lists one row per installed instance", len(panel_rows) == 2,
      str([getattr(c, "data", "") for c in panel_rows]))

dtext = subtree_text(panel)
check("it lists the vanilla instance", "1.21.11" in dtext, dtext[:200])
check("it lists the Fabric instance", "26.1.2" in dtext, dtext[:200])
check("it shows loader/mod details", "fabric" in dtext and "2 mods" in dtext,
      dtext[:200])
# Panel rows are select-only: Rename/Delete live on the Play card's folder row.
tips = [getattr(c, "tooltip", "") for c in walk(panel)]
check("rows have no per-row Play / Rename / Delete actions",
      not any(t in ("Play this instance", "Rename", "Delete") for t in tips),
      str(tips[:12]))
check("each row shows a real picture (not a vector glyph)",
      bool(panel_rows) and all(
          any(type(x).__name__ == "Image" and getattr(x, "src", None)
              for x in walk(row)) for row in panel_rows),
      str([[type(x).__name__ for x in walk(row)] for row in panel_rows][:2]))

# The row click is still the selection path (it closes the sheet).
if panel_rows:
    driver._fire_named(panel_rows[-1], "on_click", "select from version panel")
    check("selecting from the panel closes it", not picker_model.is_open())
check("selecting from the panel raises nothing", not driver.errors,
      str(driver.errors[:3]))

print("\n4. deleting the LAST instance from the hero clears the Play area")

# Regression (2026-10-17, user report): "when there's only 1 version and I
# delete it, it does delete but the UI doesn't correctly disappear". The delete
# itself worked; the page didn't. refresh_version_list()'s "no installed
# versions" branch only repainted the mods / hero parts, not the compact
# Game-version button or the rename/delete pair. The panel is the other half:
# it stays mounted across the action, so its rows must be rebuilt too - even
# when the sheet is closed (a stale row there could be clicked later, which
# selected - and silently re-downloaded - the deleted instance).
#
# Rename/Delete are hero-only now (panel rows are select-only), so this drives
# the real path: one installed instance, select it, hero Delete + confirmation,
# then the empty-state resets.
_remaining = [dict(INSTALLED[1])]
stubs.core.get_installed_versions = lambda *a, **k: list(_remaining)


def _shrinking_delete(vid):
    _remaining[:] = [v for v in _remaining if v["id"] != vid]


stubs.core.delete_version = _shrinking_delete
# Drop the dialogs section 3 left stacked (the fake page keeps them in
# page.opened) so this section starts from a clean surface.
for _d in list(page.opened):
    _d.open = False
page.opened.clear()
page._dialogs.controls.clear()  # type: ignore[attr-defined]

# Re-sync the app against the new installed set through a real entry point:
# "New instance" is refresh_version_list(online=True).
# (Each fire needs its own action label: the driver de-dupes identical
# (control, handler, action) triples so a pass never double-clicks.)
driver._fire_named(picker_btn[0], "on_click", "open version picker (last instance)")
browse = [c for c in fz.clickable_with_subtext(page, "new instance")
          if callable(getattr(c, "on_click", None))]
if browse:
    driver._fire_named(browse[-1], "on_click", "browse new instances (last instance)")
    picker_model._next()
    wait_for_versions()
back = [c for c in fz.clickable_with_subtext(page, "back")
        if callable(getattr(c, "on_click", None))
        and subtree_text(c).strip() == "back"]
if back:
    driver._fire_named(back[0], "on_click", "back to installed versions (last instance)")
    picker_model._back()

# The panel lists that single instance, with no per-row actions.
panel_rows = [c for c in walk(panel)
              if isinstance(getattr(c, "data", None), str)
              and c.data.startswith("version-panel-row-")]
check("the panel lists the single remaining instance",
      [c.data for c in panel_rows] == [f"version-panel-row-{FABRIC_ID}"],
      str([getattr(c, "data", "") for c in panel_rows]))
row_deletes = [c for c in (walk(panel) if panel is not None else [])
               if getattr(c, "tooltip", "") == "Delete"]
check("that row offers no Delete of its own", not row_deletes,
      f"{len(row_deletes)} delete buttons")

cards = find_cards()
check("the remaining instance has an instance row",
      set(cards) == {FABRIC_ID}, str(sorted(cards)))
if FABRIC_ID in cards:
    driver._fire_named(cards[FABRIC_ID], "on_click", "select the remaining instance")


def hero_btn(tip):
    for c in every_control(page):
        if (getattr(c, "tooltip", "") or "") == tip:
            return c
    return None


del_btn = hero_btn("Delete instance")
check("the hero Delete is live for an installed selection",
      del_btn is not None and not getattr(del_btn, "disabled", True)
      and getattr(del_btn, "opacity", None) == 1,
      f"disabled={getattr(del_btn, 'disabled', None)} "
      f"opacity={getattr(del_btn, 'opacity', None)}")

driver._fire_named(del_btn, "on_click", "hero:delete last instance")
confirm = None
if page.opened:
    for c in walk(page.opened[-1]):
        if type(c).__name__ == "TextButton" and "delete" == (ctrl_text(c) or "").lower():
            confirm = c
check("the hero Delete asks for confirmation", confirm is not None)
if confirm is not None:
    driver._fire_named(confirm, "on_click", "confirm hero delete")

check("the hero delete really removed it", not _remaining, str(_remaining))
check("the hero delete raised nothing", not driver.errors, str(driver.errors[:3]))

# The panel was CLOSED when the delete happened; its old children must still be
# gone, so a later click cannot hit the deleted instance.
check("the closed panel drops the deleted row", not find_cards(),
      str(sorted(find_cards())))
check("the closed panel shows the empty notice",
      "no instances yet" in subtree_text(panel).lower(),
      subtree_text(panel)[:160])

picker_text = subtree_text(picker_btn[0]) if picker_btn else ""
check("the Game-version button goes back to 'nothing installed'",
      "no versions installed yet" in picker_text.lower()
      and "26.1.2" not in picker_text, picker_text[:160])
ren = hero_btn("Rename instance")
check("rename/delete dim out after the last instance is deleted",
      all(getattr(c, "disabled", None)
          for c in (del_btn, ren) if c is not None)
      and all(getattr(c, "opacity", None) == 0.4
              for c in (del_btn, ren) if c is not None),
      f"delete={getattr(del_btn, 'disabled', None)}/{getattr(del_btn, 'opacity', None)} "
      f"rename={getattr(ren, 'disabled', None)}/{getattr(ren, 'opacity', None)}")

print("\n5. a version whose folder is already gone is still forgotten")

# The 2026-10-26 report: "when i delete it still shows stale instance and
# doesn't let me change it". One way to land there: delete_version() raises
# ValueError("That version folder no longer exists") - the folder is already
# gone, so the only useful action left is to forget the instance. The old code
# showed the error and returned, leaving a dead row/card on screen forever.
_remaining[:] = [dict(INSTALLED[1])]
stubs.core.get_installed_versions = lambda *a, **k: list(_remaining)


def _already_gone(vid):
    # The folder vanished before the click; a rescan will no longer find it.
    _remaining[:] = []
    raise ValueError("That version folder no longer exists.")


stubs.core.delete_version = _already_gone
driver._fire_named(picker_btn[0], "on_click", "open version picker (already gone)")
browse = [c for c in fz.clickable_with_subtext(page, "new instance")
          if callable(getattr(c, "on_click", None))]
if browse:
    driver._fire_named(browse[-1], "on_click", "browse new instances (already gone)")
back = [c for c in fz.clickable_with_subtext(page, "back")
        if callable(getattr(c, "on_click", None))
        and subtree_text(c).strip() == "back"]
if back:
    driver._fire_named(back[0], "on_click", "back to installed versions (already gone)")

cards = find_cards()
if FABRIC_ID in cards:
    driver._fire_named(cards[FABRIC_ID], "on_click", "select the vanished instance")
del_btn = hero_btn("Delete instance")
driver._fire_named(del_btn, "on_click", "hero:delete vanished instance")
confirm = None
if page.opened:
    for c in walk(page.opened[-1]):
        if type(c).__name__ == "TextButton" and "delete" == (ctrl_text(c) or "").lower():
            confirm = c
check("the vanished instance still asks for confirmation", confirm is not None)
if confirm is not None:
    driver._fire_named(confirm, "on_click", "confirm vanished delete")

check("'folder no longer exists' is treated as success, not an error",
      not driver.errors, str(driver.errors[:3]))
check("the vanished instance is dropped from the panel", not find_cards(),
      str(sorted(find_cards())))
picker_text = subtree_text(picker_btn[0]) if picker_btn else ""
check("the Game-version button no longer advertises it",
      "26.1.2" not in picker_text and "no versions installed yet" in picker_text.lower(),
      picker_text[:160])
check("rename/delete are disabled again",
      all(getattr(c, "disabled", None)
          for c in (hero_btn("Delete instance"), hero_btn("Rename instance"))
          if c is not None))

print("\n6. repeated panel rebuilds are safe")

# Install / launch workers repaint off the UI thread while the Play tab's own
# selection path can rebuild the same panel rows on the UI thread. The list is
# a pure view of the live instance descriptors and every mutation happens under
# TREE_LOCK, so interleaving them must never raise. Drive the real render path
# from several threads (sizes stubbed out so the test does not spawn walkers).
picker_model.get_instances = lambda: [{
    "id": FABRIC_ID, "display_name": "26.1.2 (Fabric)",
    "base_version": "26.1.2", "loader": "fabric", "loader_label": "Fabric",
    "mod_count": 2, "last_played": None, "incomplete": False,
    "folder": FABRIC_ID,
}]
picker_model.get_selected = lambda: FABRIC_ID
picker_model._fill_sizes = staticmethod(lambda slots: None)
rebuild = picker_model._render_installed
race_errors = []


def _repaint():
    try:
        for _ in range(40):
            rebuild()
    except Exception as ex:                # noqa: BLE001 - reported below
        race_errors.append(ex)


import threading                          # noqa: E402
threads = [threading.Thread(target=_repaint) for _ in range(6)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("concurrent panel rebuilds never raise", not race_errors,
      str(race_errors[:2]))

print(f"\n{passed} passed, {failed} failed")
print("Version-management UI test: " + ("FAIL" if failed else "PASS"))
sys.exit(1 if failed else 0)
