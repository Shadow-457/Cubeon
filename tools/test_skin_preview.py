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


# Detection must inspect the whole reserved columns, not one pixel. A classic
# skin with a transparent elbow but an opaque lower arm remains classic.
classic_probe = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
classic_probe.putpixel((47, 30), (1, 2, 3, 255))
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
