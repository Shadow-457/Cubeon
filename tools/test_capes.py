#!/usr/bin/env python3
"""
Tests for the 2026-09-07 flexible/animated cape work in cubeon/capes.py +
the GET /cape/frames local API endpoint. Run with:

    python tools/test_capes.py

No network, no real .minecraft: HOME is pointed at a temp directory before
cubeon imports (see _sandbox_home), and the local API is exercised by calling
the provider the HTTP layer would call - friends_service.cape_frames_payload
- against a stub service, plus one real HTTP round-trip against a locally
started api server for the 204/JSON contract.

Covers the three behaviors the mod depends on:
  * any image becomes a valid cape sheet (auto-fit onto the 10x16 panel),
  * a multi-frame GIF gets a .frames.json with capped fps/frames, and the
    static sheet CSL serves is frame 0,
  * animated_cape_frames() -> {"fps","frames","version"} for the active
    animated cape, None for a still cape or none set - and version changes
    when the animation is swapped (that's the mod's "re-decode" signal).
"""
import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
import types

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
from cubeon.config import save_config                              # noqa: E402

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


def _make_gif(n_frames=3, w=40, h=40):
    frames = [Image.new("RGBA", (w, h), c) for c in
              ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))]
    frames = frames[:n_frames] if n_frames <= 3 else \
        frames + [frames[-1]] * (n_frames - 3)
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    return buf.getvalue()


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

# --------------------------------------------------------------------------
# 2. Animated input: GIF -> static sheet (frame 0) + frames.json.
# --------------------------------------------------------------------------
gif_path = _tmpfile(_make_gif(3), ".gif")
entryA = capes.add_custom_cape(gif_path, "animated one")
check("animated entry flagged", entryA.get("animated") is True,
      f"entry={entryA}")

with Image.open(capes.get_custom_cape_path(entryA["filename"])) as im:
    check("static sheet is frame 0 (red)",
          im.getpixel((5, 5))[:3] == (255, 0, 0), f"got {im.getpixel((5, 5))}")

frames_path = os.path.join(capes.CAPES_DIR, entryA["filename"] + ".frames.json")
check("frames.json written", os.path.exists(frames_path))
with open(frames_path) as f:
    fj = json.load(f)
check("3 frames stored", len(fj["frames"]) == 3, f"got {len(fj['frames'])}")
check("fps within cap", 2 <= fj["fps"] <= capes.MAX_FPS, f"got {fj['fps']}")
dec = base64.b64decode(fj["frames"][1])
with Image.open(io.BytesIO(dec)) as im:
    check("frame 1 decodes to green", im.getpixel((5, 5))[:3] == (0, 255, 0),
          f"got {im.getpixel((5, 5))}")

# Frame cap: a GIF with 30 DISTINCT frames stores at most MAX_FRAMES.
# (Distinct on purpose: consecutive-identical frames are deduped before the
# cap, so a lazy "repeat last frame" GIF would store fewer either way.)
many = []
for i in range(30):
    many.append(Image.new("RGBA", (40, 40), (i * 8 % 256, 60, 60, 255)))
mb = io.BytesIO()
many[0].save(mb, "GIF", save_all=True, append_images=many[1:],
             duration=100, loop=0)
big = _tmpfile(mb.getvalue(), ".gif")
entryB = capes.add_custom_cape(big, "big anim")
with open(os.path.join(capes.CAPES_DIR, entryB["filename"] + ".frames.json")) as f:
    check("frames capped at MAX_FRAMES",
          len(json.load(f)["frames"]) == capes.MAX_FRAMES)

# --------------------------------------------------------------------------
# 3. animated_cape_frames() - what GET /cape/frames serves.
# --------------------------------------------------------------------------
cfg = {"username": "Tester", "active_cape": entryA["filename"]}
payload = capes.animated_cape_frames(cfg["active_cape"])
check("payload has fps/frames/version",
      payload and {"fps", "frames", "version"} <= set(payload), f"got {payload}")
check("payload frames == stored frames",
      payload["frames"] == fj["frames"])
v1 = payload["version"]

check("still cape -> None", capes.animated_cape_frames(entry2["filename"]) is None)
check("missing cape -> None", capes.animated_cape_frames("nope.png") is None)
check("no cape set -> None", capes.animated_cape_frames(None) is None)

# Swapping to a different animated cape changes the version.
cfg["active_cape"] = entryB["filename"]
payload_b = capes.animated_cape_frames(cfg["active_cape"])
check("other anim has different version", payload_b["version"] != v1)

# --------------------------------------------------------------------------
# 4. set_active_cape / sync: LocalSkin/capes/<USERNAME>.png appears, is the
#    static sheet, and rename/none cleans up the old file.
# --------------------------------------------------------------------------
cfg = {"username": "Tester", "active_cape": entryA["filename"]}
capes.set_active_cape(cfg, entryA["filename"])
synced = os.path.join(capes.CSL_LOCAL_CAPES_DIR, "Tester.png")
check("csl LocalSkin cape synced", os.path.isfile(synced), synced)
with Image.open(synced) as im:
    check("synced cape is the static sheet (frame 0)",
          im.getpixel((5, 5))[:3] == (255, 0, 0), f"got {im.getpixel((5, 5))}")

capes.set_active_cape(cfg, None)
check("csl cape removed when unset", not os.path.exists(synced))

cfg2 = {"username": "Tester", "active_cape": entryB["filename"]}
capes.set_active_cape(cfg2, entryB["filename"])
synced2 = os.path.join(capes.CSL_LOCAL_CAPES_DIR, "Tester.png")
check("re-sync writes new sheet", os.path.isfile(synced2))

# --------------------------------------------------------------------------
# 5. The local API endpoint contract (204 vs JSON) over real HTTP.
# --------------------------------------------------------------------------
from cubeon import local_api                                     # noqa: E402
import requests                                                  # noqa: E402

local_api.set_capeframes_provider(lambda: capes.animated_cape_frames(entryA["filename"]))
check("local api started", local_api.start())
srv = local_api.start._server
base = f"http://127.0.0.1:{srv.server_address[1]}"
hdr = {"X-Cubeon-Token": srv.token}

r = requests.get(f"{base}/cape/frames", headers=hdr)
check("animated cape -> 200 JSON", r.status_code == 200, str(r.status_code))
body = r.json()
check("HTTP payload matches direct call",
      body["fps"] == payload["fps"] and body["frames"] == payload["frames"])

local_api.set_capeframes_provider(lambda: None)
r2 = requests.get(f"{base}/cape/frames", headers=hdr)
check("no animated cape -> 204", r2.status_code == 204, str(r2.status_code))

# No provider registered at all (older launcher): still 204, not 404, so the
# mod's poll loop treats it as "nothing set".
local_api._providers["capeframes"] = None
r3 = requests.get(f"{base}/cape/frames", headers=hdr)
check("unregistered provider -> 204", r3.status_code == 204, str(r3.status_code))

# --------------------------------------------------------------------------
fails = [n for n, ok, _ in _checks if not ok]
print()
print(f"{len(_checks) - len(fails)}/{len(_checks)} passed")
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
