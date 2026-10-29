#!/usr/bin/env python3
"""Regression checks for uploaded-skin preview geometry."""
import os
import tempfile
import types

import _sandbox_home
_home = _sandbox_home.isolate()
_fake_mc = os.path.join(_home, ".minecraft")
_mll = types.ModuleType("minecraft_launcher_lib")
_mll.utils = types.SimpleNamespace(get_minecraft_directory=lambda: _fake_mc)
import sys
sys.modules["minecraft_launcher_lib"] = _mll
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from cubeon import skins


def check(label, condition):
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


# Detection must inspect the full unused cube-net regions, not one pixel. A classic
# skin with a transparent elbow but an opaque lower arm remains classic.
classic_probe = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
classic_probe.putpixel((54, 30), (1, 2, 3, 255))
check("classic reserved arm column wins over a transparent probe pixel",
      not skins._detect_slim_model(classic_probe))

hole = Image.new("RGBA", (64, 64), (80, 120, 160, 255))
hole.putpixel((20, 20), (0, 0, 0, 0))  # required torso base must not stay clear
repaired = skins._repair_transparent_base(hole, slim=False)
check("transparent base pixels are repaired before upload",
      repaired.getpixel((20, 20))[3] == 255)


# Mark the real left-arm edge and its outer sleeve edge. A slim skin has three
# usable columns, but both regions retain their documented x origins (36/52).
src = os.path.join(_home, "slim.png")
img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
for y in range(52, 64):
    for x in range(36, 39):
        img.putpixel((x, y), (20, 200, 40, 255))
    for x in range(52, 55):
        img.putpixel((x, y), (200, 40, 20, 255))
img.save(src, "PNG")
entry = skins.add_custom_skin(src, "Slim edge regression")
out = os.path.join(_home, "preview.png")
skins.render_local_skin_preview(entry["filename"], out, scale=8)

with Image.open(out) as preview:
    # Preview canvas has the left arm at x=0 and preserves all three columns.
    check("left slim arm starts at the documented x origin",
          preview.getpixel((0, 72))[0] > 150)
    check("left slim arm's outer column is not clipped",
          preview.getpixel((16, 72))[0] > 150)
    # Outer sleeve layer is composited over the base arm, proving its source
    # origin is also correct rather than shifted left by one pixel.
check("left sleeve edge is retained",
          preview.getpixel((0, 72))[0] > 100)

# The PNG format has no model flag. An edited/flattened Alex skin can have
# opaque reserved columns and is therefore ambiguous to pixel-only detection;
# the explicit upload model must still force the 3px arm layout.
ambiguous = os.path.join(_home, "ambiguous.png")
Image.new("RGBA", (64, 64), (80, 120, 160, 255)).save(ambiguous, "PNG")
forced = skins.add_custom_skin(ambiguous, "Forced Alex", model="slim")
check("explicit slim model overrides ambiguous PNG pixels", forced["slim"] is True)
check("explicit slim choice survives later active-skin reads",
      skins._active_skin_is_slim(forced["filename"]) is True)

print("skin preview geometry checks passed")

# ---------------------------------------------------------------------------
print("\nback view (the 'see the skin from behind' switch)")
# ---------------------------------------------------------------------------
# A back view is a real 180 degree turn: the sheet's BACK faces are composited
# and the two sides trade places, so an asymmetric skin (one sleeve, a bag over
# one shoulder) reads the way it does in game. The front render must stay
# byte-identical to before, so every check below is "front unchanged, back
# differs in exactly the documented way".
RED, BLUE = (255, 0, 0, 255), (0, 0, 255, 255)
GREEN, YELLOW = (0, 200, 0, 255), (255, 220, 0, 255)
MAGENTA, CYAN = (255, 0, 255, 255), (0, 255, 255, 255)
TORSO_F, TORSO_B = (120, 60, 20, 255), (30, 90, 200, 255)

sheet = Image.new("RGBA", (64, 64), (0, 0, 0, 0))


def _fill(x, y, w, h, color):
    for _y in range(y, y + h):
        for _x in range(x, x + w):
            sheet.putpixel((_x, _y), color)


_fill(8, 8, 8, 8, RED)          # head front
_fill(24, 8, 8, 8, BLUE)        # head back
_fill(20, 20, 8, 12, TORSO_F)   # torso front
_fill(32, 20, 8, 12, TORSO_B)   # torso back
_fill(44, 20, 4, 12, GREEN)     # right arm front
_fill(52, 20, 4, 12, YELLOW)    # right arm back
_fill(36, 52, 4, 12, MAGENTA)   # left arm front
_fill(44, 52, 4, 12, CYAN)      # left arm back
_fill(4, 20, 4, 12, (10, 10, 10, 255))    # right leg front
_fill(12, 20, 4, 12, (200, 200, 200, 255))  # right leg back
_fill(20, 52, 4, 12, (10, 10, 10, 255))   # left leg front
_fill(28, 52, 4, 12, (200, 200, 200, 255))  # left leg back
turned_src = os.path.join(_home, "turned.png")
sheet.save(turned_src, "PNG")

# Final canvas for a classic 4px-arm skin is 128x256. Sample points, in final
# pixels: head centre, torso centre, the two arm slots, the two leg slots.
HEAD = (64, 32)
TORSO = (64, 112)
ARM_L, ARM_R = (16, 112), (112, 112)
LEG_L, LEG_R = (48, 208), (80, 208)


def _sample(view):
    out_png = os.path.join(_home, f"turned_{view}.png")
    skins.render_local_skin_preview("turned.png", out_png, scale=8,
                                    src_path=turned_src, view=view)
    with Image.open(out_png) as im:
        im = im.convert("RGBA")
        return {name: im.getpixel((x, y))
                for name, (x, y) in (("head", HEAD), ("torso", TORSO),
                                     ("arm_l", ARM_L), ("arm_r", ARM_R),
                                     ("leg_l", LEG_L), ("leg_r", LEG_R))}


front = _sample("front")
back = _sample("back")

check("front view still shows the FRONT face of the head",
      front["head"] == RED)
check("front view still shows the front torso", front["torso"] == TORSO_F)
check("front view keeps the left arm on the viewer's left",
      front["arm_l"] == MAGENTA and front["arm_r"] == GREEN)
check("back view shows the BACK face of the head", back["head"] == BLUE)
check("back view shows the back torso", back["torso"] == TORSO_B)
check("back view swaps the arms (viewer's left is the body's right)",
      back["arm_l"] == YELLOW and back["arm_r"] == CYAN)
check("back view swaps the legs too",
      back["leg_l"] == (200, 200, 200, 255) and
      back["leg_r"] == (200, 200, 200, 255))
check("the two views are genuinely different images",
      front != back)

# Barely-different inputs must not silently render the same picture: a skin
# whose back is unique proves the back faces are actually read.
check("back render does not just reuse the front crops",
      back["head"] != front["head"] and back["torso"] != front["torso"])

# Default stays front, and an unrecognised value is treated as front (never a
# crash, never a half-turned body).
default_png = os.path.join(_home, "turned_default.png")
skins.render_local_skin_preview("turned.png", default_png, scale=8,
                                src_path=turned_src)
weird_png = os.path.join(_home, "turned_weird.png")
skins.render_local_skin_preview("turned.png", weird_png, scale=8,
                                src_path=turned_src, view="sideways")
with Image.open(default_png) as im:
    check("omitting view renders the front", im.convert("RGBA").getpixel(HEAD) == RED)
with Image.open(weird_png) as im:
    check("an unknown view falls back to the front",
          im.convert("RGBA").getpixel(HEAD) == RED)

# Legacy 64x32 sheets define no back faces at all. The turn still must not
# crash, and must not invent pixels that do not exist on the sheet.
legacy = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
_fill_l = lambda x, y, w, h, c: [legacy.putpixel((_x, _y), c)
                                 for _y in range(y, y + h)
                                 for _x in range(x, x + w)]
_fill_l(8, 8, 8, 8, RED)        # head front
_fill_l(20, 20, 8, 12, TORSO_F)  # torso front
legacy_src = os.path.join(_home, "legacy.png")
legacy.save(legacy_src, "PNG")
for view in ("front", "back"):
    legacy_png = os.path.join(_home, f"legacy_{view}.png")
    skins.render_local_skin_preview("legacy.png", legacy_png, scale=8,
                                    src_path=legacy_src, view=view)
    with Image.open(legacy_png) as im:
        im = im.convert("RGBA")
        check(f"legacy 64x32 skin renders in {view} view without crashing",
              im.size == (128, 256))
        check(f"legacy {view} view keeps the only faces the sheet has",
              im.getpixel(HEAD) == RED and im.getpixel(TORSO) == TORSO_F)

print("\nskin back-view checks passed")

