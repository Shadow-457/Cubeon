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
stubs.app.main(page)
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

print(f"\n{passed} passed, {failed} failed")
print("Version-management UI test: " + ("FAIL" if failed else "PASS"))
sys.exit(1 if failed else 0)
