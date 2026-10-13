"""Settings -> Import UI: search + per-instance "Import to" (ui/import_section.py).

test_importer.py covers the pure scan/import logic; this covers the Flet
render path the smoke test never reaches (it only builds main() once, so
_category_group / _item_row / the picker / the import threads are otherwise
unexercised):

  1. The pane builds and advertises a scan button + active-version target line.
  2. render_scan_result() turns a real scan into a summary line plus one
     collapsible group per content type, each with an item row per find.
     There is deliberately NO "Import all" - every find targets an instance.
  3. The search field filters finds live.
  4. "Import to..." opens an instance picker whose model greys out
     incompatible instances (loader / MC dependency) and ones that already
     contain the item; picking one installs into THAT instance.
  5. Duplicate detection still flags scan-time finds and refuses re-imports.
"""
import json
import os
import sys
import tempfile
import time
import types
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_home = tempfile.mkdtemp(prefix="cubeon-import-ui-test-")
os.environ["HOME"] = _home
os.environ["USERPROFILE"] = _home
os.environ["CUBEON_GAME_DIR"] = os.path.join(_home, "game")

import flet as ft  # noqa: E402

from cubeon import importer  # noqa: E402
from cubeon.theme import section_label, THEME  # noqa: E402
from ui.import_section import build_import_section  # noqa: E402

passed = failed = 0


def check(label, ok, extra=""):
    global passed, failed
    passed += ok
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' - ' + extra) if extra and not ok else ''}")


class FakePage:
    """Minimal ft.Page stand-in: overlay, a no-op run_task, clipboard."""

    def __init__(self):
        self.overlay = []
        self.update_calls = 0
        self.session = types.SimpleNamespace()
        self._clipboard = None

    def update(self, *controls):
        self.update_calls += 1

    def run_task(self, fn, *a, **kw):
        return None

    def set_clipboard(self, text):
        self._clipboard = text


def walk(control, depth=0, seen=None):
    if seen is None:
        seen = set()
    if control is None or id(control) in seen or depth > 80:
        return
    seen.add(id(control))
    yield control
    for attr in ("controls", "content", "title", "leading", "trailing",
                 "actions", "items", "tabs"):
        child = getattr(control, attr, None)
        if child is None:
            continue
        if isinstance(child, (list, tuple)):
            for c in child:
                yield from walk(c, depth + 1, seen)
        else:
            yield from walk(child, depth + 1, seen)


def values(control):
    return getattr(control, "_values", {}) or {}


def find_buttons(root, type_name, label):
    return [c for c in walk(root)
            if getattr(c, "_c", None) == type_name
            and values(c).get("content") == label]


def all_values(root):
    out = []
    for c in walk(root):
        for v in list(values(c).values()) + [getattr(c, "value", None)]:
            if isinstance(v, str) and v.strip():
                out.append(v.lower())
    return out


# --------------------------------------------------------------------------
# A fixture with one of every content type.
# --------------------------------------------------------------------------
def mkzip(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(name, data)


src = os.path.join(_home, "stuff")
mkzip(f"{src}/mods/sodium.jar",
      [("fabric.mod.json", json.dumps({"id": "sodium", "name": "Sodium",
                                       "depends": {"minecraft": "1.21"}}))])
mkzip(f"{src}/mods/lithium.jar",
      [("fabric.mod.json", json.dumps({"id": "lithium", "name": "Lithium"}))])
mkzip(f"{src}/resourcepacks/pack.zip",
      [("pack.mcmeta", json.dumps({"pack": {"pack_format": 34}}))])
mkzip(f"{src}/shaderpacks/bsl.zip", [("shaders/c.fsh", "void main(){}")])
mkzip(f"{src}/modpacks/mr.mrpack", [("modrinth.index.json", "{}")])
os.makedirs(f"{src}/saves/World", exist_ok=True)
open(f"{src}/saves/World/level.dat", "wb").write(b"\x00")

# Three installed instances for the picker: the active one (1.21.11 fabric),
# an older MC (Sodium's "1.21" dependency fails there), and a Forge instance
# (a Fabric mod never goes there). Loader is OMITTED on purpose - the pane
# must derive it from the version id the way main.py's callback does.
INSTANCES = [
    {"version_id": "fabric-loader.0.16.9-1.21.11", "mc_version": "1.21.11",
     "label": "1.21.11 Fabric"},
    {"version_id": "fabric-loader.0.16.9-1.20.1", "mc_version": "1.20.1",
     "label": "1.20.1 Fabric"},
    {"version_id": "forge-47.2.0-1.21.11", "mc_version": "1.21.11",
     "label": "1.21.11 Forge"},
]

# --------------------------------------------------------------------------
# Build the pane.
# --------------------------------------------------------------------------
print("build:")
page = FakePage()
pane = build_import_section(
    page, cfg={}, section_label=section_label,
    get_active_target=lambda: ("1.21.11", "fabric", "fabric-loader.0.16.9-1.21.11"),
    get_instances=lambda: INSTANCES,
    show_snack=None, **THEME)

check("returns a Column", isinstance(pane, ft.Column))
check("starts hidden (a Settings pane)", pane.visible is False)
txt = all_values(pane)
check("has a scan button", bool(find_buttons(pane, "FilledButton", "Scan a folder")))
check("shows the active target version",
      any("1.21.11" in t for t in txt), str(txt[:6]))
check("section heading present", any("import" == t for t in txt), str(txt[:6]))

# --------------------------------------------------------------------------
# Render a real scan result.
# --------------------------------------------------------------------------
print("render:")
result = importer.scan_folder(src)
pane.render_scan_result(result)
rtexts = all_values(pane._results_col)
check("summary line rendered",
      any(t.startswith("found") for t in rtexts), str(rtexts[:4]))
for label in ("mods", "resource packs", "shader packs", "modpacks", "worlds"):
    check(f"group '{label}' present", label in rtexts)

# No "Import all" anywhere - targeting is per item now.
check("no Import-all buttons (per-instance targeting only)",
      not find_buttons(pane._results_col, "TextButton", "Import all"))

# Groups are the top-level Columns of the results column (the summary line
# is a Text). One per non-empty category.
n_groups = len([c for c in pane._results_col.controls
                if getattr(c, "_c", None) == "Column"])
check("one group per content type (5)", n_groups == 5, str(n_groups))

import_btns = find_buttons(pane._results_col, "OutlinedButton", "Import to...")
check("one Import-to button per found item (6)", len(import_btns) == 6,
      str(len(import_btns)))
check("copy-path buttons present",
      any(getattr(c, "tooltip", None) == "Copy file path"
          for c in walk(pane._results_col)))
check("search field appears with results", pane._search_field.visible is True)

# Item rows carry name + meta (size / loader / MC version).
check("a mod row shows its loader", any("fabric" in t for t in rtexts))

# The group starts collapsed (details hidden) so the list doesn't blast open.
collapsed = [c for c in walk(pane._results_col)
             if getattr(c, "_c", None) == "Column" and getattr(c, "visible", True) is False]
check("groups start collapsed", len(collapsed) >= 5, str(len(collapsed)))

# Expanding a group reveals the details AND flips the chevron glyph. The
# chevron part matters: ft.Icon's glyph lives in .icon, and setting .name
# silently keeps the old arrow (a bug the codebase has elsewhere).
first_group = next(c for c in pane._results_col.controls
                   if getattr(c, "_c", None) == "Column" and len(getattr(c, "controls", [])) == 2)
header, details = first_group.controls[0], first_group.controls[1]
chevron = next(c for c in walk(header) if getattr(c, "_c", None) == "Icon")
was_icon = chevron.icon
check("chevron starts as a right arrow",
      was_icon == ft.Icons.KEYBOARD_ARROW_RIGHT, str(was_icon))
header.on_click(types.SimpleNamespace())
check("clicking the header expands the group", details.visible is True)
check("chevron flips to a down arrow",
      chevron.icon == ft.Icons.KEYBOARD_ARROW_DOWN, str(chevron.icon))
header.on_click(types.SimpleNamespace())
check("clicking again collapses it", details.visible is False)

# --------------------------------------------------------------------------
# Search filters the finds live.
# --------------------------------------------------------------------------
print("search:")
# Row visibility is the observable contract of the filter. Item rows are the
# Row controls directly inside each group's details column.
pane.render_scan_result(result)


def _item_rows():
    rows = []
    for g_ctrl in pane._results_col.controls:
        if getattr(g_ctrl, "_c", None) != "Column" or len(getattr(g_ctrl, "controls", [])) != 2:
            continue
        details = g_ctrl.controls[1]
        rows.extend([c for c in getattr(details, "controls", [])
                     if getattr(c, "_c", None) == "Row"])
    return rows


rows_before = _item_rows()
check("all 6 item rows visible before filtering",
      sum(1 for r in rows_before if getattr(r, "visible", True)) == 6,
      str(sum(1 for r in rows_before if getattr(r, "visible", True))))
pane._search_field.value = "sodium"
pane._search_field.on_change(types.SimpleNamespace(control=pane._search_field))
rows_after = _item_rows()
vis = [r for r in rows_after if getattr(r, "visible", True)]
check("filter leaves only the matching row visible", len(vis) == 1, str(len(vis)))
# Empty query shows everything again.
pane._search_field.value = ""
pane._search_field.on_change(types.SimpleNamespace(control=pane._search_field))
check("clearing the filter shows everything again",
      sum(1 for r in _item_rows() if getattr(r, "visible", True)) == 6)

# --------------------------------------------------------------------------
# Import-to: the picker model and installs into a CHOSEN instance.
# --------------------------------------------------------------------------
print("import-to:")
mod_entry = next(e for e in result["mods"] if e["name"] == "Sodium")
model = pane.picker_model_ui(mod_entry)
check("picker lists every instance (3)", len(model) == 3, str(len(model)))
(inst_a, ok_a, reason_a), (inst_b, ok_b, reason_b), (inst_c, ok_c, reason_c) = model
check("loader derived from the version id", inst_a["loader"] == "fabric",
      str(inst_a))
check("compatible instance stays enabled", ok_a is True, str(reason_a))
check("MC-dependency mismatch is greyed out",
      ok_b is False and "1.21" in reason_b, str(reason_b))
check("wrong loader is greyed out",
      ok_c is False and "fabric" in reason_c, str(reason_c))

# Import into the ACTIVE target via the fallback (what a picker click ends
# up calling when no explicit instance is passed).
pane.import_item_ui(mod_entry, None)
deadline = time.time() + 6
while time.time() < deadline and not (
        pane._status_text.value or "").startswith("Added mod"):
    time.sleep(0.05)
check("import status reported",
      (pane._status_text.value or "").startswith("Added mod"),
      str(pane._status_text.value))
from cubeon import mods  # noqa: E402
pdir = mods.get_profile_dir("1.21.11", "fabric")
check("mod file landed in the active profile folder",
      os.path.isdir(pdir) and any(f.endswith(".jar") for f in os.listdir(pdir)),
      str(os.listdir(pdir) if os.path.isdir(pdir) else "missing"))

# Import Lithium into the FORGE instance - a different profile entirely -
# and into the active fabric one, so the picker can show both states.
lithium = next(e for e in result["mods"] if e["name"] == "Lithium")
forge_inst = next(i for i, _ok, _r in model if i["loader"] == "forge")
pane._status_text.value = ""
pane.import_item_ui(lithium, None, inst=forge_inst)
deadline = time.time() + 6
while time.time() < deadline and not (
        pane._status_text.value or "").startswith("Added mod"):
    time.sleep(0.05)
forge_dir = mods.get_profile_dir("1.21.11", "forge")
check("import into a non-active instance lands in ITS profile",
      os.path.isdir(forge_dir) and any(f.endswith(".jar") for f in os.listdir(forge_dir)),
      str(os.listdir(forge_dir) if os.path.isdir(forge_dir) else "missing"))
check("the active profile did NOT receive the forge-targeted mod",
      not any("lithium" in f for f in os.listdir(pdir)),
      str(os.listdir(pdir)))

pane._status_text.value = ""
pane.import_item_ui(lithium, None)  # active fabric target
deadline = time.time() + 6
while time.time() < deadline and not (
        pane._status_text.value or "").startswith("Added mod"):
    time.sleep(0.05)
check("lithium also lands in the active fabric profile",
      any("lithium" in f for f in os.listdir(pdir)),
      str(os.listdir(pdir)))

# Lithium is now in the fabric profile (and the forge one): the picker
# greys those rows while the 1.20.1 fabric instance stays enabled.
model2 = pane.picker_model_ui(lithium)
fabric_row = next((i, ok, reason) for i, ok, reason in model2
                  if i["label"] == "1.21.11 Fabric")
old_row = next((i, ok, reason) for i, ok, reason in model2
               if i["label"] == "1.20.1 Fabric")
forge_row = next((i, ok, reason) for i, ok, reason in model2
                 if i["loader"] == "forge")
check("already-installed instance is greyed in the picker",
      fabric_row[1] is False and "already" in fabric_row[2].lower(),
      str(fabric_row))
check("another compatible instance stays enabled", old_row[1] is True,
      str(old_row))
check("incompatible loader is still greyed (not 'already')",
      forge_row[1] is False and "already" not in forge_row[2].lower(),
      str(forge_row))

# Copy-path button wires the clipboard.
copy_btn = [c for c in walk(pane._results_col)
            if getattr(c, "tooltip", None) == "Copy file path"][0]
copy_btn.on_click(types.SimpleNamespace())
check("copy-path filled the clipboard", bool(page._clipboard), str(page._clipboard))

# --------------------------------------------------------------------------
# Duplicate detection: a rescan flags what's already in the active profile.
# --------------------------------------------------------------------------
print("duplicate detection:")
result2 = importer.scan_folder(src)
importer.mark_installed(result2, mc_version="1.21.11", loader="fabric")
pane.render_scan_result(result2)

rtexts2 = all_values(pane._results_col)
check("rows show the already note in their meta line",
      any("already in this profile" in t for t in rtexts2),
      str(rtexts2[:8]))
check("summary line counts the already entries",
      any("already added" in t for t in rtexts2), str(rtexts2[:2]))
check("active-target duplicate is flagged",
      bool(next(e for e in result2["mods"] if e["name"] == "Sodium").get("already")))

# Re-import of a flagged row is refused by the import guard.
pane._status_text.value = ""
sodium2 = next(e for e in result2["mods"] if e["name"] == "Sodium")
pane.import_item_ui(sodium2, None)
deadline = time.time() + 6
while time.time() < deadline and "already in this profile" not in (
        pane._status_text.value or ""):
    time.sleep(0.05)
check("re-import of a duplicate is refused with a clear message",
      "already in this profile" in (pane._status_text.value or ""),
      str(pane._status_text.value))

# A successful import flips its own row to "already" (the pane re-renders
# with fresh duplicate flags once the install lands).
bsl = next(e for e in result2["shaderpacks"])
bsl.pop("already", None)
pane._status_text.value = ""
pane.import_item_ui(bsl, None)
flipped = False
deadline = time.time() + 6
while time.time() < deadline:
    texts = all_values(pane._results_col)
    if ("Added shader" in (pane._status_text.value or "")
            and any("already in this profile" in t for t in texts)):
        flipped = True
        break
    time.sleep(0.05)
check("import flips its row to already in the active profile",
      flipped, f"status={pane._status_text.value!r}")

# Scanning with no version selected must refuse cleanly, not crash.
_no_target = build_import_section(
    page, cfg={}, section_label=section_label,
    get_active_target=lambda: (None, None, None),
    get_instances=lambda: [],
    show_snack=None, **THEME)
_no_target.import_item_ui(mod_entry, None)
time.sleep(0.3)
check("no active version -> clear refusal, no crash",
      "pick a game version" in (_no_target._status_text.value or "").lower(),
      str(_no_target._status_text.value))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
