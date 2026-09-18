#!/usr/bin/env python3
"""
Tests for the LOCAL skins/capes library (cubeon/gallery.py).

Run with:
    python tools/test_gallery.py

No network, no real store: HOME is pointed at a temp dir and the tests drop
files into the library folders the way a user would.

Covers: the drop-folders are created, the catalog reflects their contents
(network-free), previews render from the actual pixels, the install flows land
in skins.py / capes.py state and wear immediately, installed bookkeeping
round-trips, fuzzy search, and the honest no-op stubs left where the Mojang
browse system used to be. Exit code 0 iff every check passes.
"""
import io
import os
import sys
import types
from unittest.mock import patch

import _sandbox_home
_home = _sandbox_home.isolate()

_fake_mc = os.path.join(_home, ".minecraft")
_mll = types.ModuleType("minecraft_launcher_lib")
_mll.utils = types.SimpleNamespace(get_minecraft_directory=lambda: _fake_mc)
sys.modules["minecraft_launcher_lib"] = _mll

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image                                     # noqa: E402

from cubeon import gallery, capes, skins  # noqa: E402

_checks = []


def check(name, ok, detail=""):
    _checks.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def _png(size, color):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


# 1. Folders exist, catalogs start empty
# --------------------------------------
gallery.ensure_gallery()
check("skin library folder created", os.path.isdir(gallery.SKIN_LIBRARY_DIR))
check("cape library folder created", os.path.isdir(gallery.CAPE_LIBRARY_DIR))
check("catalog is empty before any drop", not gallery.list_gallery_skins())
check("cape catalog empty before any drop", not gallery.list_gallery_capes())

# 2. Drop files in the way a user would
# -------------------------------------
open(os.path.join(gallery.SKIN_LIBRARY_DIR, "Cool Skin.png"), "wb").write(
    _png((64, 64), (21, 119, 199, 255)))
open(os.path.join(gallery.SKIN_LIBRARY_DIR, "_ignored.png"), "wb").write(
    _png((64, 64), (0, 0, 0, 255)))  # underscore-prefixed: skipped
open(os.path.join(gallery.SKIN_LIBRARY_DIR, "notes.txt"), "w").write("no")
open(os.path.join(gallery.CAPE_LIBRARY_DIR, "red.png"), "wb").write(
    _png((64, 32), (230, 60, 40, 255)))

skin_items = gallery.list_gallery_skins()
check("skin catalog lists only the dropped image",
      [i["id"] for i in skin_items] == ["Cool Skin.png"],
      str([i["id"] for i in skin_items]))
check("cape catalog lists the dropped cape",
      [i["id"] for i in gallery.list_gallery_capes()] == ["red.png"])
first = skin_items[0]
check("item carries the file as its sheet",
      first["sheet_path"].endswith("Cool Skin.png"), first["sheet_path"])
check("preview was rendered from the actual pixels",
      first["preview_path"].endswith("_v2.png")
      and os.path.isfile(first["preview_path"]), first["preview_path"])
check("catalog is network-free by shape (no remote fields)",
      all("remote" not in k for i in skin_items for k in i))

# 3. Install flows - same pipeline as a manual upload, worn immediately
# ---------------------------------------------------------------------
cfg = {}
entry = gallery.install_gallery_skin(cfg, "Cool Skin.png")
check("install lands in the skins store", entry["filename"] in
      {s["filename"] for s in skins.list_custom_skins()})
check("install wears the skin immediately",
      cfg.get("active_skin") == entry["filename"], str(cfg.get("active_skin")))
check("installed bookkeeping maps gid -> file",
      gallery.gallery_id_for_file("skin", entry["filename"]) == "Cool Skin.png")

cape_entry = gallery.install_gallery_cape(cfg, "red.png")
check("cape install wears it",
      cfg.get("active_cape") == cape_entry["filename"], str(cfg.get("active_cape")))

# Stem form resolves too (one match by name without the extension). The store
# may dedup a re-install under a fresh filename - what matters is that the
# resolution worked and the entry is really in the store.
entry2 = gallery.install_gallery_skin(cfg, "Cool Skin")
check("a bare stem resolves to the file", entry2["filename"] in
      {s["filename"] for s in skins.list_custom_skins()})

raised = False
try:
    gallery.install_gallery_skin(cfg, "no-such-file")
except ValueError:
    raised = True
check("an id no longer in the folder raises ValueError", raised)

# 4. Forget round-trips
# ---------------------
skins.delete_custom_skin(entry["filename"])
gallery.forget_file("skin", entry["filename"])
check("forget clears a deleted skin's mapping",
      gallery.gallery_id_for_file("skin", entry["filename"]) is None)
gallery.forget_file("skin", entry["filename"])
check("forget is safe to call twice", True)

# 5. Fuzzy search (network-free)
# ------------------------------
fuzzy = gallery.list_gallery_skins("coolskin")
check("fuzzy query finds the file",
      any(i["id"] == "Cool Skin.png" for i in fuzzy),
      str([i["id"] for i in fuzzy]))
check("nonsense query matches nothing", not gallery.list_gallery_skins("zzqqxx"))
check("query is applied before limit",
      all(i["id"] == "Cool Skin.png" for i in gallery.list_gallery_skins("cool", limit=1)))
check("no-query view is name-sorted",
      [i["name"] for i in gallery.list_gallery_skins()] == sorted(
          i["name"] for i in gallery.list_gallery_skins()))

# 6. The Mojang browse system is gone - honest no-ops
# ---------------------------------------------------
check("featured_count is 0", gallery.featured_count() == 0)
check("prefetch_featured is a no-op", gallery.prefetch_featured() == [])
check("suggest_player is a no-op list", gallery.suggest_player() == [])
check("load_player returns an honest empty snapshot",
      gallery.load_player("Dream")["has_skin"] is False)

prior_state = gallery._load_installed()
with open(gallery.INSTALLED_PATH, "rb") as f:
    prior_bytes = f.read()
for failure in ("serialize", "replace"):
    raised = False
    try:
        if failure == "serialize":
            gallery._save_installed({"skin": {"bad": object()}, "cape": {}})
        else:
            with patch("cubeon.atomicio.os.replace", side_effect=OSError("write failed")):
                gallery._save_installed({"skin": {}, "cape": {}})
    except (TypeError, OSError):
        raised = True
    with open(gallery.INSTALLED_PATH, "rb") as f:
        check(f"gallery {failure} failure preserves prior bytes", raised and f.read() == prior_bytes)
    check(f"gallery {failure} failure preserves mappings", gallery._load_installed() == prior_state)
check("gallery failed writes clean temporary files",
      not any(n.startswith(".atomic-") for n in os.listdir(os.path.dirname(gallery.INSTALLED_PATH))))

cape_path = os.path.join(gallery.CAPE_LIBRARY_DIR, "red.png")
preview = gallery.list_gallery_capes()[0]["preview_path"]
with Image.open(preview) as im:
    before_pixel = im.getpixel((0, 0))
with open(cape_path, "wb") as f:
    f.write(_png((64, 32), (20, 40, 240, 255)))
stat = os.stat(cape_path)
os.utime(cape_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
gallery.list_gallery_capes()
with Image.open(preview) as im:
    check("replacing same-name cape refreshes rendered pixels", im.getpixel((0, 0)) != before_pixel)
stat = os.stat(cape_path)
with open(cape_path, "wb") as f:
    f.write(_png((128, 64), (40, 220, 30, 255)))
os.utime(cape_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
gallery.list_gallery_capes()
with Image.open(preview) as im:
    check("size-only library change invalidates catalog and preview", im.getpixel((0, 0)) == (40, 220, 30, 255))

# Summary
# -------
failed = [c for c in _checks if not c[1]]
print(f"\n{len(_checks) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
