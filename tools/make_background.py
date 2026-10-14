"""
Generate Cubeon's launcher background image (assets/bg/glass.jpg).

WHY A GENERATED IMAGE

The "glassy" look the launcher is going for is a dark, faintly-lit backdrop that
the translucent panels float over. On Linux the honest way to do that - a
translucent NATIVE window that shows the desktop - is not reliable (the embedder
has to opt into per-pixel alpha, and most setups simply show a black window), so
the backdrop is painted INSIDE the app instead: one dark image behind everything,
with the design system's translucent panels (CARD_FILL) on top.

The image is deliberately almost black and very quiet - a soft green-black glow
top-left, a faint vignette, a barely-there cube watermark low-right and a touch of
grain - so it reads as depth, never as decoration competing with the UI.

Run:  python tools/make_background.py
Out:  assets/bg/glass.jpg

Re-runnable and deterministic (fixed seed), so the committed asset can always be
regenerated from this source rather than living as an untraceable binary.
"""
import os
import random

from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
BASE = (5, 5, 5)          # matches theme.BG - the image is an extension of it
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "bg", "glass.jpg")


def _glow():
    """Two soft green-black pools of light: a brighter one top-left (behind the
    top bar) and a fainter one bottom-right, so the backdrop has a direction."""
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-500, -600, 1350, 820], fill=150)              # top-left
    d.ellipse([W - 900, H - 950, W + 550, H + 400], fill=78)   # bottom-right
    mask = mask.filter(ImageFilter.GaussianBlur(260))
    return Image.composite(Image.new("RGB", (W, H), (24, 52, 20)),
                           Image.new("RGB", (W, H), BASE), mask)


def _vignette(img):
    """Darken the edges so the eye lands on the content in the middle."""
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse(
        [-W * 0.10, -H * 0.10, W * 1.10, H * 1.10], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(300))
    darkened = Image.composite(img, Image.new("RGB", (W, H), (0, 0, 0)), mask)
    return Image.blend(img, darkened, 0.70)


def _cube_watermark(img):
    """A large, barely-visible isometric cube outline in the brand green,
    low-right - the same mark as the app icon, used as a watermark."""
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
    line = (90, 210, 70, 30)   # ACCENT at ~12% alpha
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


def main():
    img = _glow()
    img = _cube_watermark(img)
    img = _vignette(img)
    img = _grain(img)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, "JPEG", quality=86, optimize=True)
    print(f"+ wrote {OUT} ({os.path.getsize(OUT) // 1024} KB, {W}x{H})")


if __name__ == "__main__":
    main()
