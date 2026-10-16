#!/usr/bin/env python3
"""
Play tab version management UI (ui/versions.py + cubeon/instances.py).

Boots the REAL launcher headless under the safe stubs with two fake installed
versions - a plain vanilla and a Fabric loader install carrying two mods - and
checks the three things this feature added:

  1. the Game-version picker groups Installed above Available and tags rows
     with their loader / release date, and its search filters its own list;
  2. the "Jump back in" cards carry loader + mod-count + last-played chips
     without breaking the no-rebuild invariant;
  3. the Instances manager lists every install and its Play / Rename / Delete
     buttons work.

No window, no network, no real install.

Run: python3 tools/test_version_ui.py
"""
import os
import sys
import time

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
AVAILABLE = [
    {"id": "1.21.11", "type": "release", "releaseTime": "2024-06-13T00:00:00+00:00"},
    {"id": "1.20.1", "type": "release", "releaseTime": "2023-06-07T00:00:00+00:00"},
    {"id": FABRIC_ID, "type": "release", "releaseTime": "2025-01-01T00:00:00+00:00"},
    {"id": "26w45a", "type": "snapshot", "releaseTime": "2024-11-06T00:00:00+00:00"},
]

stubs = fz.install_safe_stubs()
stubs.core.get_installed_versions = lambda *a, **k: list(INSTALLED)
stubs.core.get_available_versions = lambda *a, **k: list(AVAILABLE)

from cubeon import instances as instance_info                 # noqa: E402
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

print("\n1. Jump back in cards carry loader / mods / last-played chips")


def find_cards():
    out = {}
    for c in every_control(page):
        h = getattr(c, "on_click", None)
        d = getattr(h, "__defaults__", None)
        if callable(h) and isinstance(d, tuple) and len(d) == 1 \
                and isinstance(d[0], str) and getattr(c, "width", None) == 210:
            out[d[0]] = c
    return out


cards = find_cards()
check("one card per installed version", set(cards) == {"1.21.11", FABRIC_ID},
      f"found {sorted(cards)}")

fabric_text = subtree_text(cards[FABRIC_ID]) if FABRIC_ID in cards else ""
check("the Fabric card is tagged with its loader", "fabric" in fabric_text,
      fabric_text[:120])
check("the Fabric card shows its mod count", "2 mods" in fabric_text,
      fabric_text[:120])
check("the Fabric card shows when it was last played", "ago" in fabric_text,
      fabric_text[:120])
vanilla_text = subtree_text(cards["1.21.11"]) if "1.21.11" in cards else ""
check("the vanilla card is not mislabelled as a loader install",
      "fabric" not in vanilla_text and "mods" not in vanilla_text,
      vanilla_text[:120])

print("\n2. the version picker groups Installed / Available and tags rows")

picker_btn = fz.clickable_with_subtext(page, "pick a minecraft version")
check("the Game-version button exists", bool(picker_btn))
if picker_btn:
    driver._fire_named(picker_btn[0], "on_click", "open version picker")


def dialog_titled(name):
    for dlg in getattr(page, "opened", []):
        title = getattr(dlg, "title", None)
        if title is not None and getattr(title, "value", "") == name:
            return dlg
    return None


picker_dlg = dialog_titled("Game version")

# "Browse all versions" pulls the online list and rebuilds the dialog rows.
browse = [c for c in fz.clickable_with_subtext(page, "browse all versions")
          if callable(getattr(c, "on_click", None))]
check("the picker offers 'Browse all versions'", bool(browse))
if browse:
    driver._fire_named(browse[-1], "on_click", "browse all versions")

dialog_text = subtree_text(picker_dlg) if picker_dlg is not None else ""
check("installed versions are grouped under a header", "installed" in dialog_text,
      dialog_text[:200])
check("downloadable-only versions are grouped separately",
      "available to download" in dialog_text, dialog_text[:200])
check("rows carry a release date", "2024-06-13" in dialog_text, dialog_text[:200])
check("installed loader installs are tagged in the online list",
      "fabric" in dialog_text, dialog_text[:200])
check("snapshots are badged", "snapshot" in dialog_text, dialog_text[:200])

# The search must narrow the dialog's own list without touching the dropdown.
filters = [c for c in walk(picker_dlg)
           if type(c).__name__ == "TextField"
           and "filter versions" in (getattr(c, "hint_text", "") or "").lower()]
check("the picker has a filter field", bool(filters))
if filters:
    filters[0].value = "1.20"
    driver._fire_named(filters[0], "on_change", "filter versions")
    filtered = subtree_text(picker_dlg)
    check("filtering hides non-matching rows", "1.20.1" in filtered)
    check("filtering never rewrites the live dropdown value",
          not driver.errors, str(driver.errors[:2]))

print("\n3. the Instances manager lists every install and acts on it")

manage = fz.clickable_with_subtext(page, "manage installed versions")
check("the Manage button exists", bool(manage))
if manage:
    driver._fire_named(manage[0], "on_click", "open instances manager")

# Find the Instances dialog among the opened ones.
inst_dialog = dialog_titled("Instances")
check("the Instances manager opens", inst_dialog is not None)

if inst_dialog is not None:
    dtext = subtree_text(inst_dialog)
    check("it lists the vanilla instance", "1.21.11" in dtext, dtext[:200])
    check("it lists the Fabric instance", "26.1.2" in dtext, dtext[:200])
    check("it shows loader/mod details", "fabric" in dtext and "2 mods" in dtext,
          dtext[:200])
    # Every row must expose the three actions.
    tips = [getattr(c, "tooltip", "") for c in walk(inst_dialog)]
    check("rows offer Play / Rename / Delete",
          "Play this instance" in tips and "Rename" in tips and "Delete" in tips,
          str(tips[:10]))
    # Fire them all - stubs make this safe; none may raise a hard error.
    for c in list(walk(inst_dialog)):
        h = getattr(c, "on_click", None)
        if callable(h) and getattr(c, "tooltip", "") in (
                "Play this instance", "Rename", "Delete"):
            driver._fire_named(c, "on_click", f"manager:{c.tooltip}")
    check("manager actions raise nothing", not driver.errors,
          str(driver.errors[:3]))

print("\n4. deleting the LAST instance leaves nothing of it in the Play area")

# Regression (2026-10-17, user report): "when there's only 1 version and I
# delete it, it does delete but the UI doesn't correctly disappear". The delete
# itself worked; the page didn't. refresh_version_list()'s "no installed
# versions" branch (only reachable by deleting the last one) re-drew the mods /
# hero parts but NOT the compact Game-version button (which mirrors the
# dropdown) or the rename/delete pair - so the button still advertised the
# version that had just been deleted and the destructive pair stayed lit. A
# delete performed from a row of the OPEN Instances manager was the other half:
# the dialog stays mounted across the action, so it kept listing the instance
# that was gone.
#
# This section drives the real path: a shrinking installed set (one instance),
# the manager's row Delete + its confirmation, then the empty-state resets.
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
# "Browse all versions" is refresh_version_list(online=True).
# (Each fire needs its own action label: the driver de-dupes identical
# (control, handler, action) triples so a pass never double-clicks.)
driver._fire_named(picker_btn[0], "on_click", "open version picker (empty state)")
browse = [c for c in fz.clickable_with_subtext(page, "browse all versions")
          if callable(getattr(c, "on_click", None))]
if browse:
    driver._fire_named(browse[-1], "on_click", "browse all versions (empty state)")

# The manager (opened from the picker) now lists that single instance.
manage = fz.clickable_with_subtext(page, "manage installed versions")
if manage:
    driver._fire_named(manage[0], "on_click", "open instances manager (empty state)")

inst_dialog = dialog_titled("Instances")
check("the manager lists the single remaining instance",
      inst_dialog is not None and "26.1.2" in subtree_text(inst_dialog),
      subtree_text(inst_dialog)[:200] if inst_dialog is not None else "no dialog")

row_deletes = [c for c in (walk(inst_dialog) if inst_dialog is not None else [])
               if getattr(c, "tooltip", "") == "Delete"]
check("that row offers Delete", len(row_deletes) == 1, f"{len(row_deletes)} delete buttons")
if row_deletes:
    driver._fire_named(row_deletes[0], "on_click", "manager:delete")

confirm = None
if page.opened:
    for c in walk(page.opened[-1]):
        if type(c).__name__ == "TextButton" and "delete" == (ctrl_text(c) or "").lower():
            confirm = c
check("Deleting from a row asks for confirmation", confirm is not None)
if confirm is not None:
    driver._fire_named(confirm, "on_click", "confirm delete")

check("the delete really removed the instance", not _remaining, str(_remaining))
check("...without raising", not driver.errors, str(driver.errors[:3]))

# -- the manager must not keep showing a row that no longer exists --------
check("the open manager stops listing the deleted instance",
      inst_dialog is not None and "26.1.2" not in subtree_text(inst_dialog),
      subtree_text(inst_dialog)[:200] if inst_dialog is not None else "no dialog")

# -- and the Play tab must go back to its empty state ---------------------
picker_text = subtree_text(picker_btn[0]) if picker_btn else ""
check("the Game-version button stops advertising the deleted version",
      "1.21.11" not in picker_text and "26.1.2" not in picker_text,
      picker_text[:160])
check("the Game-version button says nothing is installed",
      "no versions installed yet" in picker_text.lower(), picker_text[:160])

tips = {}
for c in every_control(page):
    tip = getattr(c, "tooltip", "") or ""
    if tip in ("Delete instance", "Rename instance"):
        tips[tip] = c
check("the hero still exposes rename/delete",
      set(tips) == {"Delete instance", "Rename instance"}, str(sorted(tips)))
check("rename/delete are disabled with nothing installed",
      all(getattr(c, "disabled", None) for c in tips.values()),
      str({k: getattr(c, "disabled", None) for k, c in tips.items()}))
check("rename/delete are dimmed with nothing installed",
      all(getattr(c, "opacity", None) == 0.4 for c in tips.values()),
      str({k: getattr(c, "opacity", None) for k, c in tips.items()}))

check("the Jump back in cards are gone", not find_cards(), str(sorted(find_cards())))
empties = [c for c in every_control(page)
           if type(c).__name__ == "Text"
           and (c.value or "").lower().startswith("no versions installed yet -")
           and getattr(c, "visible", None)]
check("the empty 'Jump back in' notice shows instead", bool(empties),
      str([c.value for c in every_control(page) if type(c).__name__ == "Text"][:20]))

print("\n5. the hero's own Delete on the LAST instance does the same")

# The reported path exactly: one instance installed, selected, rename/delete
# lit - delete it and the whole Play area must go back to its empty state.
_remaining[:] = [dict(INSTALLED[1])]
driver._fire_named(picker_btn[0], "on_click", "open version picker (hero flow)")
browse = [c for c in fz.clickable_with_subtext(page, "browse all versions")
          if callable(getattr(c, "on_click", None))]
if browse:
    driver._fire_named(browse[-1], "on_click", "browse all versions (hero flow)")

cards = find_cards()
check("the remaining instance has a Jump back in card",
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
check("the Jump back in row is gone after the hero delete", not find_cards(),
      str(sorted(find_cards())))

print("\n6. the 'Jump back in' row survives a concurrent repaint")

# The install / launch workers repaint off the UI thread (_rescan_installed ->
# update_hero -> InstanceCards.rebuild), while the Play tab's own selection path
# calls the same rebuild on the UI thread. Both pop dropped ids BEFORE
# assembling the row from them, so an interleaved pair raised KeyError on the
# id the other call had just popped - the repaint and its whole handler died
# with it (found as a flaky crash in the delete/Play flow above). The row is a
# pure view object, so the interleaving is reproduced directly here.
from ui.versions import InstanceCards                          # noqa: E402
import threading                                               # noqa: E402

META_ONE = {"a": {"id": "a", "display_name": "Alpha"},
            "b": {"id": "b", "display_name": "Beta"}}
_tls = threading.local()
race_cards = InstanceCards(
    page,
    get_metas=lambda: getattr(_tls, "metas", {}),
    get_labels=lambda: {},
    get_selected=lambda: None,
    on_select=lambda _vid: None,
    art_src=lambda _base: None,
    request_art=lambda _base, _apply: None,
)
race_errors = []


def _repaint(metas, rounds):
    _tls.metas = metas
    try:
        for _ in range(rounds):
            race_cards.rebuild()
    except Exception as ex:                    # noqa: BLE001 - reported below
        race_errors.append(ex)


threads = [threading.Thread(target=_repaint, args=(m, 150))
           for m in (META_ONE, {}, META_ONE, {}) for _ in range(3)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("concurrent rebuilds never raise", not race_errors, str(race_errors[:2]))

_tls.metas = META_ONE
race_cards.rebuild()
check("the row is consistent once the race is over",
      len(race_cards.row.controls) == 2 and race_cards.row.visible
      and not race_cards.empty.visible,
      f"{len(race_cards.row.controls)} cards, row.visible="
      f"{race_cards.row.visible}, empty.visible={race_cards.empty.visible}")

print(f"\n{passed} passed, {failed} failed")
print("Version-management UI test: " + ("FAIL" if failed else "PASS"))
sys.exit(1 if failed else 0)
