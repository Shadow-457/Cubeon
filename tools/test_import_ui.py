"""Settings -> Import UI: rendering a scan result and one-click import
(ui/import_section.py).

test_importer.py covers the pure scan/import logic; this covers the Flet
render path the smoke test never reaches (it only builds main() once, so
_category_group / _item_row / the import threads are otherwise unexercised):

  1. The pane builds and advertises a scan button + active-version target line.
  2. render_scan_result() turns a real scan into a summary line plus one
     collapsible group per content type, each with an item row per find.
  3. Item rows carry an Import button and a copy-path button.
  4. Clicking Import actually installs into the sandboxed game dir and the
     status line reports it; Import-all does the same for a whole group.
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

# --------------------------------------------------------------------------
# Build the pane.
# --------------------------------------------------------------------------
print("build:")
page = FakePage()
pane = build_import_section(
    page, cfg={}, section_label=section_label,
    get_active_target=lambda: ("1.21.11", "fabric", "fabric-loader.0.16.9-1.21.11"),
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

# One "Import all" button per non-empty category = 5 groups here (counted by
# button, since a walk also matches the parent results column that CONTAINS
# them all).
n_groups = len(find_buttons(pane._results_col, "TextButton", "Import all"))
check("one group per content type (5)", n_groups == 5, str(n_groups))

import_btns = find_buttons(pane._results_col, "OutlinedButton", "Import")
check("one Import button per found item (6)", len(import_btns) == 6,
      str(len(import_btns)))
check("copy-path buttons present",
      any(getattr(c, "tooltip", None) == "Copy file path"
          for c in walk(pane._results_col)))

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
# One-click import dispatches and reports.
# --------------------------------------------------------------------------
print("import:")
mod_entry = next(e for e in result["mods"] if e["name"] == "Sodium")
pane.import_item_ui(mod_entry, None)   # what the Import button's on_click calls
deadline = time.time() + 6
while time.time() < deadline and not (
        pane._status_text.value or "").startswith("Added mod"):
    time.sleep(0.05)
check("import status reported",
      (pane._status_text.value or "").startswith("Added mod"),
      str(pane._status_text.value))
# Mods land in the PER-PROFILE folder (real bytes), not the wiped staging
# game/mods - sync_mods_to_game only links them in at launch.
from cubeon import mods  # noqa: E402
pdir = mods.get_profile_dir("1.21.11", "fabric")
check("mod file landed in the profile folder",
      os.path.isdir(pdir) and any(f.endswith(".jar") for f in os.listdir(pdir)),
      str(os.listdir(pdir) if os.path.isdir(pdir) else "missing"))

# Import-all via the group's button (mods group is first: 2 jars).
pane._status_text.value = ""  # clear the single-import status so we wait for THIS
all_btn = find_buttons(pane._results_col, "TextButton", "Import all")[0]
all_btn.on_click(types.SimpleNamespace())
deadline = time.time() + 6
while time.time() < deadline and "imported" not in (
        pane._status_text.value or "").lower():
    time.sleep(0.05)
check("import-all reports progress",
      "imported" in (pane._status_text.value or "").lower(),
      str(pane._status_text.value))

# Copy-path button wires the clipboard.
copy_btn = [c for c in walk(pane._results_col)
            if getattr(c, "tooltip", None) == "Copy file path"][0]
copy_btn.on_click(types.SimpleNamespace())
check("copy-path filled the clipboard", bool(page._clipboard), str(page._clipboard))

# Scanning with no version selected must refuse cleanly, not crash.
_no_target = build_import_section(
    page, cfg={}, section_label=section_label,
    get_active_target=lambda: (None, None, None),
    show_snack=None, **THEME)
_no_target.import_item_ui(mod_entry, None)
time.sleep(0.3)
check("no active version -> clear refusal, no crash",
      "pick a game version" in (_no_target._status_text.value or "").lower(),
      str(_no_target._status_text.value))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
