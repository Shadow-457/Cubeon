"""
Generate Cubeon's launcher background images (assets/bg/glass*.jpg).

WHY GENERATED IMAGES

The "glassy" look the launcher is going for is a dark, faintly-lit backdrop that
the translucent panels float over. On Linux the honest way to do that - a
translucent NATIVE window that shows the desktop - is not reliable (the embedder
has to opt into per-pixel alpha, and most setups simply show a black window), so
the backdrop is painted INSIDE the app instead: one dark image behind everything,
with the design system's translucent panels (CARD_FILL) on top.

Each image is deliberately almost black and very quiet - a soft glow top-left, a
faint vignette, a barely-there cube watermark low-right and a touch of grain - so
it reads as depth, never as decoration competing with the UI.

SEASONAL VARIANTS

glass.jpg is the green (default) look. The four seasonal files are the SAME
structure with the glow and watermark re-tinted to that season's palette accent
(templates/color_<season>.py), so the backdrop matches whichever template the
launcher boots with. main.py picks glass_<season>.jpg for a seasonal palette and
falls back to glass.jpg for green / a pinned --color / anything unknown.

Run:  python tools/make_background.py
Out:  assets/bg/glass.jpg            (green - the fallback look)
      assets/bg/glass_spring.jpg
      assets/bg/glass_summer.jpg
      assets/bg/glass_autumn.jpg
      assets/bg/glass_winter.jpg

Re-runnable and deterministic (fixed seed), so the committed assets can always be
regenerated from this source rather than living as untraceable binaries.
"""
import os
import random

from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
BASE = (5, 5, 5)          # matches theme.BG - every image is an extension of it
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "bg")
OUT = os.path.join(OUT_DIR, "glass.jpg")

# Per-palette-key tint. "glow" is the soft pool of light (a dark, desaturated
# version of the template's accent); "line" is the watermark stroke (the accent
# itself at ~12% alpha). Keep these roughly in step with templates/color_<key>.py.
LOOKS = {
    "green":  {"glow": (24, 52, 20),  "line": (90, 210, 70, 30)},
    "spring": {"glow": (58, 28, 40),  "line": (232, 106, 154, 30)},
    "summer": {"glow": (62, 48, 18),  "line": (228, 178, 60, 30)},
    "autumn": {"glow": (60, 32, 13),  "line": (224, 118, 42, 30)},
    "winter": {"glow": (24, 46, 62),  "line": (95, 182, 224, 32)},
}


def _glow(color):
    """Two soft pools of light in `color`: a brighter one top-left (behind the
    top bar) and a fainter one bottom-right, so the backdrop has a direction."""
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-500, -600, 1350, 820], fill=150)              # top-left
    d.ellipse([W - 900, H - 950, W + 550, H + 400], fill=78)   # bottom-right
    mask = mask.filter(ImageFilter.GaussianBlur(260))
    return Image.composite(Image.new("RGB", (W, H), color),
                           Image.new("RGB", (W, H), BASE), mask)


def _vignette(img):
    """Darken the edges so the eye lands on the content in the middle."""
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse(
        [-W * 0.10, -H * 0.10, W * 1.10, H * 1.10], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(300))
    darkened = Image.composite(img, Image.new("RGB", (W, H), (0, 0, 0)), mask)
    return Image.blend(img, darkened, 0.70)


def _cube_watermark(img, line):
    """A large, barely-visible isometric cube outline in `line` (the palette
    accent at low alpha) low-right - the same mark as the app icon, used as a
    watermark."""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cx, cy, s = W - 430, H - 330, 300
    top = (cx, cy - s)
    left = (cx - s, cy - s * 0.5)
    right = (cx + s, cy - s * 0.5)
    mid = (cx, cy)
    bot_l = (cx - s, cy + s * 0.5)
    bot_r = (cx + s, cy + s * 0.5)
    bottom = (cx, cy + s)
    for a, b in ((top, left), (top, right), (left, mid), (right, mid),
                 (left, bot_l), (right, bot_r), (mid, bottom),
                 (bot_l, bottom), (bot_r, bottom), (mid, top)):
        d.line([a, b], fill=line, width=3)
    overlay = overlay.filter(ImageFilter.GaussianBlur(0.6))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _grain(img, amount=5, seed=457):
    """A whisper of film grain so large flat areas do not band on cheap panels."""
    rng = random.Random(seed)
    noise = Image.new("L", (W, H))
    noise.putdata([rng.randint(128 - amount, 128 + amount)
                   for _ in range(W * H)])
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    return Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.035)


def _render(look):
    img = _glow(look["glow"])
    img = _cube_watermark(img, look["line"])
    img = _vignette(img)
    return _grain(img)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for key, look in LOOKS.items():
        path = OUT if key == "green" else os.path.join(OUT_DIR,
                                                       f"glass_{key}.jpg")
        _render(look).save(path, "JPEG", quality=86, optimize=True)
        print(f"+ wrote {path} ({os.path.getsize(path) // 1024} KB, {W}x{H})")


if __name__ == "__main__":
    main()
