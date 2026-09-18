#!/usr/bin/env python3
"""
Tests for the flexible cape work in cubeon/capes.py. Run with:

    python tools/test_capes.py

No network, no real .minecraft: HOME is pointed at a temp directory before
cubeon imports (see _sandbox_home).

Covers the two behaviors that remain after the animated-cape removal:
  * any image becomes a valid cape sheet (auto-fit onto the 10x16 panel),
  * set_active_cape / sync: LocalSkin/capes/<USERNAME>.png appears, is the
    fitted sheet, and rename/none cleans up the old file.
"""
import io
import os
import sys
import tempfile
import types
from unittest.mock import patch

import _sandbox_home
_home = _sandbox_home.isolate()

# Stub minecraft_launcher_lib like the other tests: paths.py only needs
# get_minecraft_directory().
_fake_mc = os.path.join(_home, ".minecraft")
_mll = types.ModuleType("minecraft_launcher_lib")
_mll.utils = types.SimpleNamespace(get_minecraft_directory=lambda: _fake_mc)
sys.modules["minecraft_launcher_lib"] = _mll

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image                                              # noqa: E402

from cubeon import capes                                           # noqa: E402

_checks = []


def check(name, ok, detail=""):
    _checks.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _make_still(w=40, h=40, color=(200, 30, 30, 255)):
    return _png_bytes(Image.new("RGBA", (w, h), color))


def _tmpfile(data, suffix=".png"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


# --------------------------------------------------------------------------
# 1. Flexible input: any decodable image becomes a cape.
# --------------------------------------------------------------------------
src = _tmpfile(_make_still())
ok, err = capes.validate_cape_file(src)
check("still PNG validates", ok, err)

entry = capes.add_custom_cape(src, "test still")
sheet_path = capes.get_custom_cape_path(entry["filename"])
with Image.open(sheet_path) as im:
    check("still image fitted to 64x32 cape sheet",
          im.size == (64, 32), f"got {im.size}")
    # The panel region (1,1)-(11,17) should hold our red; the rest is clear.
    check("back panel painted", im.getpixel((5, 5))[:3] == (200, 30, 30),
          f"got {im.getpixel((5, 5))}")
    check("off-panel transparent", im.getpixel((40, 5))[3] == 0,
          f"got {im.getpixel((40, 5))}")

# JPEG input (wrong shape AND wrong format) must be accepted and fitted.
jpg = Image.new("RGB", (300, 100), (10, 120, 220))
jb = io.BytesIO(); jpg.save(jb, "JPEG")
src2 = _tmpfile(jb.getvalue(), ".jpg")
entry2 = capes.add_custom_cape(src2, "wide jpg")
with Image.open(capes.get_custom_cape_path(entry2["filename"])) as im:
    check("JPEG accepted, fitted to 64x32", im.size == (64, 32), f"got {im.size}")
    # 300x100 scales to 10x3, centered vertically on the 16-tall panel
    # (rows ~7-9). JPEG is lossy, so compare with tolerance, not equality.
    px = im.getpixel((5, 8))
    check("JPEG panel painted",
          all(abs(a - b) <= 12 for a, b in zip(px[:3], (10, 120, 220))),
          f"got {px}")

# A real 2:1 cape-shaped PNG passes through untouched.
cape_shaped = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
cape_shaped.paste(Image.new("RGBA", (20, 32), (90, 90, 255, 255)), (2, 2))
src3 = _tmpfile(_png_bytes(cape_shaped))
entry3 = capes.add_custom_cape(src3, "hd cape")
with Image.open(capes.get_custom_cape_path(entry3["filename"])) as im:
    check("cape-shaped 128x64 kept as-is", im.size == (128, 64), f"got {im.size}")

# No entry carries animation state anymore; every upload is a plain cape.
check("entry has no animated flag", "animated" not in entry
      and "animated" not in entry2 and "animated" not in entry3)

# --------------------------------------------------------------------------
# 2. set_active_cape / sync: LocalSkin/capes/<USERNAME>.png appears, is the
#    fitted sheet, and rename/none cleans up the old file.
# --------------------------------------------------------------------------
capeA = capes.add_custom_cape(src, "cape a")
capeB = capes.add_custom_cape(src3, "cape b")

cfg = {"username": "Tester", "active_cape": capeA["filename"]}
capes.set_active_cape(cfg, capeA["filename"])
synced = os.path.join(capes.CSL_LOCAL_CAPES_DIR, "Tester.png")
check("csl LocalSkin cape synced", os.path.isfile(synced), synced)
with Image.open(synced) as im:
    check("synced cape is the fitted sheet",
          im.getpixel((5, 5))[:3] == (200, 30, 30), f"got {im.getpixel((5, 5))}")

capes.set_active_cape(cfg, None)
check("csl cape removed when unset", not os.path.exists(synced))

cfg2 = {"username": "Tester", "active_cape": capeB["filename"]}
capes.set_active_cape(cfg2, capeB["filename"])
synced2 = os.path.join(capes.CSL_LOCAL_CAPES_DIR, "Tester.png")
check("re-sync writes new sheet", os.path.isfile(synced2))

# Delete removes the stored file and drops the entry.
capes.delete_custom_cape(capeB["filename"])
check("deleted cape file removed",
      not os.path.exists(capes.get_custom_cape_path(capeB["filename"])))
check("deleted cape dropped from meta",
      capeB["filename"] not in [c["filename"] for c in capes.list_custom_capes()])

prior_meta = capes._load_capes_meta()
with open(capes.CAPES_META_PATH, "rb") as f:
    prior_bytes = f.read()
for failure in ("serialize", "replace"):
    raised = False
    try:
        if failure == "serialize":
            capes._save_capes_meta({"capes": [object()]})
        else:
            with patch("cubeon.atomicio.os.replace", side_effect=OSError("write failed")):
                capes._save_capes_meta({"capes": []})
    except (TypeError, OSError):
        raised = True
    with open(capes.CAPES_META_PATH, "rb") as f:
        check(f"cape {failure} failure preserves prior bytes", raised and f.read() == prior_bytes)
    check(f"cape {failure} failure preserves metadata", capes._load_capes_meta() == prior_meta)
check("cape failed writes clean temporary files",
      not any(n.startswith(".atomic-") for n in os.listdir(capes.CAPES_DIR)))

# --------------------------------------------------------------------------
fails = [n for n, ok, _ in _checks if not ok]
print()
print(f"{len(_checks) - len(fails)}/{len(_checks)} passed")
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
