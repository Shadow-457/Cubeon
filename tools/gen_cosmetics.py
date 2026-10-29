"""Generate Cubeon's original shoulder and back cosmetics.

Everything here is drawn from scratch with PIL - no downloaded or licensed
art. The output is two identical bundles:

    assets/cosmetics/<id>.png            the launcher's preview textures
    assets/cosmetics/catalog.json        ids, slots, names, box geometry, UVs

    mod/src/main/resources/assets/cubeon-client/textures/cosmetics/<id>.png
    mod/src/main/resources/assets/cubeon-client/cosmetics/catalog.json

The mod reads the second pair from its own jar; the launcher reads the first.
Keeping one generator means the 3D preview and the in-game renderer can never
disagree about where a wing is or which pixel is its leading edge.

GEOMETRY CONTRACT
-----------------
A box is axis-aligned in Minecraft model space: +x is the player's left, +y is
DOWN, and -z is the player's front (so a cape/back item sits at +z). Origins
are absolute model coordinates, the same space `PlayerModel` uses, where the
standing body pivot is (0, 0, 0). The torso spans y=0..12 and the legs end at
y=24. The preview converts with y' = 24 - y and z' = -z,
which is the only place the two coordinate systems meet.

A box's texture atlas is laid out exactly like `cubeon.appearance._box`:

    width  = 2 * (depth + width) * px
    height = (depth + height) * px
    front  at (depth, depth)          back   at (2*depth + width, depth)
    left   at (0, depth)              right  at (depth + width, depth)
    top    at (depth, 0)              bottom at (depth + width, 0)

`uv` is the atlas origin inside the item's PNG, so boxes can be stacked
vertically without a second copy of the layout maths in Java.

Run from the repo root:

    python3 tools/gen_cosmetics.py
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cubeon.cosmetics import face_rects  # noqa: E402  (one atlas layout)

LAUNCHER_DIR = os.path.join(ROOT, "assets", "cosmetics")
MOD_DIR = os.path.join(ROOT, "mod", "src", "main", "resources", "assets",
                       "cubeon-client")
MOD_TEXTURE_DIR = os.path.join(MOD_DIR, "textures", "cosmetics")
MOD_CATALOG_DIR = os.path.join(MOD_DIR, "cosmetics")

# Absolute model-space attachment points. The shoulder anchor is the top of
# the right shoulder (the body's pivot and top edge are both at y=0); the
# back anchor sits just behind the torso's upper back.
ANCHORS = {
    "shoulder": [-6.0, 0.0, 0.0],
    "back": [0.0, 2.0, 2.2],
}

# ---------------------------------------------------------------------------
# Tiny pixel-art canvas
# ---------------------------------------------------------------------------


def C(value):
    """'#rrggbb' / '#rrggbbaa' / (r,g,b,a) -> RGBA tuple."""
    if isinstance(value, tuple):
        return value if len(value) == 4 else value + (255,)
    text = value.lstrip("#")
    if len(text) == 6:
        text += "ff"
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4, 6))


def mix(a, b, amount):
    """Blend two colours; amount=0 -> a, amount=1 -> b."""
    a, b = C(a), C(b)
    return tuple(round(a[i] + (b[i] - a[i]) * amount) for i in range(4))


def shade(colour, amount):
    """Darken (amount<0) or lighten (amount>0) a colour."""
    return mix(colour, "#000000" if amount < 0 else "#ffffff", abs(amount))


class Tile:
    """One 16x16 face, drawn with hard pixels and an optional outline."""

    def __init__(self, size=16):
        self.size = size
        self.im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def r(self, x, y, w, h, colour):
        self.d.rectangle([x, y, x + w - 1, y + h - 1], fill=C(colour))

    def p(self, x, y, colour):
        if 0 <= x < self.size and 0 <= y < self.size:
            self.im.putpixel((x, y), C(colour))

    def poly(self, points, colour):
        self.d.polygon(points, fill=C(colour))

    def hline(self, x, y, w, colour):
        self.r(x, y, w, 1, colour)

    def vline(self, x, y, h, colour):
        self.r(x, y, 1, h, colour)

    def mirror(self):
        half = self.im.crop((0, 0, self.size // 2, self.size))
        self.im.paste(half.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                      (self.size // 2, 0))

    def outline(self, colour, *, inner=False):
        """Trace the silhouette so the item reads on any background."""
        src = self.im.load()
        out = self.im.copy()
        dst = out.load()
        colour = C(colour)
        for y in range(self.size):
            for x in range(self.size):
                if src[x, y][3] != 0:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.size and 0 <= ny < self.size and src[nx, ny][3] != 0:
                        dst[x, y] = colour
                        break
        self.im = out
        self.d = ImageDraw.Draw(self.im)
        return self

    def speckle(self, colour, points):
        for x, y in points:
            self.p(x, y, colour)


def blank():
    return Tile()


def solid(colour):
    t = Tile()
    t.r(0, 0, 16, 16, colour)
    return t.im


def faces(front, back, left, right, top, bottom):
    return {"front": front, "back": back, "left": left, "right": right,
            "top": top, "bottom": bottom}


# ---------------------------------------------------------------------------
# Creatures (shoulder pets)
# ---------------------------------------------------------------------------


def _ears(t, pal, style):
    body, dark = pal["body"], pal["dark"]
    if style == "point":
        t.poly([(2, 5), (4, 0), (7, 5)], body)
        t.poly([(9, 5), (12, 0), (14, 5)], body)
        t.poly([(4, 3), (4, 1), (5, 3)], dark)
        t.poly([(11, 3), (12, 1), (12, 3)], dark)
    elif style == "round":
        t.r(2, 1, 4, 4, body)
        t.r(10, 1, 4, 4, body)
        t.r(3, 2, 2, 2, mix(body, "#ffffff", 0.25))
        t.r(11, 2, 2, 2, mix(body, "#ffffff", 0.25))
    elif style == "tuft":
        t.r(2, 2, 4, 3, body)
        t.r(10, 2, 4, 3, body)
        t.p(2, 1, dark)
        t.p(3, 1, body)
        t.p(13, 1, dark)
        t.p(12, 1, body)


def _head_front(pal, ear="point", muzzle="snout", marking=None):
    t = Tile()
    body, light, dark = pal["body"], pal["light"], pal["dark"]
    accent, eye = pal["accent"], pal["eye"]
    _ears(t, pal, ear)
    t.r(2, 3, 12, 11, body)
    t.r(3, 3, 10, 2, mix(body, "#ffffff", 0.22))
    # eyes
    t.r(4, 6, 2, 3, dark)
    t.r(10, 6, 2, 3, dark)
    t.p(5, 6, eye)
    t.p(11, 6, eye)
    t.p(5, 7, "#ffffff")
    t.p(11, 7, "#ffffff")
    # muzzle / beak
    if muzzle == "snout":
        t.r(6, 10, 4, 3, light)
        t.r(7, 10, 2, 1, dark)
        t.p(6, 12, mix(light, dark, 0.25))
    elif muzzle == "beak":
        t.poly([(6, 10), (9, 10), (8, 13)], accent)
        t.p(7, 10, shade(accent, -0.25))
    elif muzzle == "wide":
        t.r(5, 10, 6, 3, light)
        t.r(7, 11, 2, 1, dark)
    # markings
    if marking == "spots":
        t.p(3, 9, accent)
        t.p(12, 9, accent)
        t.p(3, 12, accent)
        t.p(12, 12, accent)
    elif marking == "stripes":
        t.vline(2, 8, 6, dark)
        t.vline(13, 8, 6, dark)
        t.hline(6, 5, 4, dark)
    elif marking == "goggles":
        t.r(3, 5, 10, 1, pal["accent"])
        t.r(4, 5, 3, 3, "#2b2b2b")
        t.r(9, 5, 3, 3, "#2b2b2b")
        t.r(5, 6, 1, 1, "#cfe8ff")
        t.r(10, 6, 1, 1, "#cfe8ff")
    elif marking == "star":
        for x, y in ((3, 4), (12, 5), (4, 11), (11, 12), (8, 2)):
            t.p(x, y, accent)
    elif marking == "mask":
        t.r(3, 5, 10, 4, mix(body, dark, 0.55))
        t.r(4, 6, 2, 2, eye)
        t.r(10, 6, 2, 2, eye)
        t.r(4, 6, 1, 1, "#ffffff")
        t.r(10, 6, 1, 1, "#ffffff")
    t.outline(dark)
    return t.im


def _head_back(pal, ear="point", marking=None):
    t = Tile()
    body, dark, accent = pal["body"], pal["dark"], pal["accent"]
    _ears(t, pal, ear)
    t.r(2, 3, 12, 11, body)
    t.r(3, 3, 10, 2, mix(body, "#ffffff", 0.14))
    t.r(4, 6, 8, 6, mix(body, dark, 0.35))
    if marking == "spots":
        t.speckle(accent, ((5, 8), (10, 10), (7, 12)))
    elif marking == "stripes":
        t.vline(7, 5, 8, dark)
        t.vline(9, 5, 8, dark)
    elif marking == "star":
        t.speckle(accent, ((5, 7), (10, 9), (7, 12), (11, 6)))
    elif marking == "goggles":
        t.r(5, 6, 6, 1, accent)
    t.outline(dark)
    return t.im


def _head_side(pal, ear="point", muzzle="snout", flip=False):
    t = Tile()
    body, light, dark = pal["body"], pal["light"], pal["dark"]
    accent, eye = pal["accent"], pal["eye"]
    if ear == "point":
        t.poly([(4, 5), (7, 0), (10, 5)], body)
    elif ear == "round":
        t.r(4, 1, 5, 4, body)
    elif ear == "tuft":
        t.r(4, 2, 5, 3, body)
        t.p(5, 1, dark)
    t.r(3, 4, 11, 10, body)
    t.r(4, 4, 9, 2, mix(body, "#ffffff", 0.2))
    t.r(9, 7, 3, 3, dark)
    t.p(10, 7, eye)
    t.p(10, 8, "#ffffff")
    if muzzle == "snout":
        t.r(10, 10, 4, 3, light)
        t.p(13, 11, dark)
    elif muzzle == "beak":
        t.poly([(10, 10), (15, 11), (10, 12)], accent)
    if flip:
        t.im = t.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        t.d = ImageDraw.Draw(t.im)
    t.outline(dark)
    return t.im


def _head_top(pal, ear="point", marking=None):
    t = Tile()
    body, dark, accent = pal["body"], pal["dark"], pal["accent"]
    t.r(3, 3, 10, 10, body)
    t.r(4, 4, 8, 8, mix(body, "#ffffff", 0.1))
    _ears(t, pal, ear)
    if marking == "spots":
        t.speckle(accent, ((5, 6), (10, 9), (8, 11)))
    elif marking == "stripes":
        t.vline(7, 3, 10, dark)
        t.vline(9, 3, 10, dark)
    elif marking == "star":
        t.speckle(accent, ((5, 6), (10, 5), (7, 10), (11, 11)))
    elif marking == "goggles":
        t.r(6, 6, 4, 2, accent)
    t.outline(dark)
    return t.im


def _head_bottom(pal):
    t = Tile()
    t.r(3, 3, 10, 10, pal["dark"])
    t.r(5, 5, 6, 6, mix(pal["body"], pal["dark"], 0.4))
    return t.im


def _body_front(pal, style="belly"):
    t = Tile()
    body, light, dark = pal["body"], pal["light"], pal["dark"]
    accent, eye = pal["accent"], pal["eye"]
    t.r(1, 2, 14, 13, body)
    t.r(2, 2, 12, 2, mix(body, "#ffffff", 0.18))
    if style == "belly":
        t.r(4, 4, 8, 9, light)
        t.r(6, 4, 4, 1, mix(light, "#ffffff", 0.4))
    elif style == "shell":
        t.r(3, 3, 10, 10, pal["shell"])
        for x, y in ((5, 5), (8, 5), (11, 5), (5, 8), (8, 8), (11, 8),
                     (5, 11), (8, 11), (11, 11)):
            t.r(x, y, 2, 2, accent)
    elif style == "scarf":
        t.r(2, 4, 12, 3, accent)
        t.r(4, 7, 8, 6, light)
    elif style == "glow":
        for y in range(4, 14, 2):
            t.r(5, y, 6, 1, accent)
            t.p(6, y, eye)
    elif style == "pumpkin":
        for x in range(3, 14, 3):
            t.vline(x, 3, 11, shade(body, -0.18))
        t.r(4, 5, 3, 2, eye)
        t.r(9, 5, 3, 2, eye)
        t.r(5, 10, 6, 1, eye)
        t.p(7, 11, eye)
        t.p(8, 11, eye)
    # little paws
    t.r(1, 13, 3, 2, dark)
    t.r(12, 13, 3, 2, dark)
    t.outline(dark)
    return t.im


def _body_back(pal, style="tail"):
    t = Tile()
    body, light, dark = pal["body"], pal["light"], pal["dark"]
    accent = pal["accent"]
    t.r(1, 2, 14, 13, body)
    t.r(2, 2, 12, 2, mix(body, "#ffffff", 0.12))
    if style == "tail":
        t.r(9, 4, 5, 10, accent)
        t.r(10, 3, 3, 2, mix(accent, "#ffffff", 0.35))
        t.p(13, 6, light)
        t.p(12, 10, light)
    elif style == "shell":
        t.r(2, 3, 12, 11, pal["shell"])
        t.r(4, 5, 8, 7, accent)
        t.vline(7, 5, 7, dark)
        t.vline(9, 5, 7, dark)
    elif style == "spots":
        t.speckle(accent, ((4, 5), (10, 4), (7, 8), (12, 9), (5, 11), (9, 12)))
    elif style == "stripes":
        t.vline(5, 3, 11, dark)
        t.vline(8, 3, 11, dark)
        t.vline(11, 3, 11, dark)
    elif style == "scarf":
        t.r(2, 3, 12, 3, accent)
        t.r(6, 6, 4, 8, light)
    elif style == "glow":
        for y in range(3, 14, 2):
            t.r(5, y, 6, 1, accent)
    t.outline(dark)
    return t.im


def _body_side(pal, style="plain"):
    t = Tile()
    body, light, dark = pal["body"], pal["light"], pal["dark"]
    accent = pal["accent"]
    t.r(2, 2, 12, 13, body)
    t.r(3, 2, 10, 2, mix(body, "#ffffff", 0.15))
    if style == "shell":
        t.r(2, 4, 12, 8, pal["shell"])
        t.r(5, 6, 3, 3, accent)
        t.r(9, 8, 3, 2, accent)
    elif style == "spots":
        t.speckle(accent, ((5, 6), (10, 7), (7, 10), (11, 12)))
    elif style == "stripes":
        t.hline(3, 6, 10, dark)
        t.hline(3, 9, 10, dark)
        t.hline(3, 12, 10, dark)
    elif style == "scarf":
        t.r(2, 4, 12, 3, accent)
    elif style == "glow":
        t.r(4, 5, 8, 1, accent)
        t.r(4, 9, 8, 1, accent)
        t.r(4, 13, 8, 1, accent)
    t.outline(dark)
    return t.im


def _body_top(pal, style="plain"):
    t = Tile()
    body, dark = pal["body"], pal["dark"]
    accent = pal["accent"]
    t.r(2, 2, 12, 12, body)
    t.r(3, 3, 10, 10, mix(body, "#ffffff", 0.08))
    if style == "shell":
        t.r(3, 3, 10, 10, pal["shell"])
        t.r(6, 6, 4, 4, accent)
    elif style == "spots":
        t.speckle(accent, ((5, 5), (10, 7), (7, 11), (11, 10)))
    elif style == "stripes":
        t.vline(6, 3, 10, dark)
        t.vline(9, 3, 10, dark)
    elif style == "scarf":
        t.r(2, 3, 12, 3, accent)
    elif style == "glow":
        t.r(5, 7, 6, 2, accent)
    t.outline(dark)
    return t.im


def _body_bottom(pal):
    t = Tile()
    t.r(2, 2, 12, 12, pal["dark"])
    t.r(4, 4, 8, 8, mix(pal["body"], pal["dark"], 0.45))
    return t.im


def creature_faces(pal, *, ear="point", muzzle="snout", marking=None,
                   body_style="belly", back_style="tail", side_style="plain"):
    head = faces(
        _head_front(pal, ear, muzzle, marking),
        _head_back(pal, ear, marking),
        _head_side(pal, ear, muzzle, flip=False),
        _head_side(pal, ear, muzzle, flip=True),
        _head_top(pal, ear, marking),
        _head_bottom(pal),
    )
    body = faces(
        _body_front(pal, body_style),
        _body_back(pal, back_style),
        _body_side(pal, side_style),
        _body_side(pal, side_style),
        _body_top(pal, side_style),
        _body_bottom(pal),
    )
    return [body, head]


# ---------------------------------------------------------------------------
# Special shoulder items
# ---------------------------------------------------------------------------


def moth_faces(pal):
    # Head: big compound eyes, feathery antennae. Body: glowing lantern tail.
    hf = Tile()
    body, dark, accent, eye = pal["body"], pal["dark"], pal["accent"], pal["eye"]
    hf.poly([(2, 4), (0, 0), (5, 2)], dark)
    hf.poly([(13, 4), (15, 0), (10, 2)], dark)
    hf.r(3, 3, 10, 10, body)
    hf.r(4, 5, 3, 4, dark)
    hf.r(9, 5, 3, 4, dark)
    hf.r(5, 6, 1, 2, eye)
    hf.r(10, 6, 1, 2, eye)
    hf.r(7, 9, 2, 3, accent)
    hf.outline(dark)
    hb = Tile()
    hb.r(3, 3, 10, 10, body)
    hb.r(4, 4, 8, 3, mix(body, dark, 0.3))
    hb.r(6, 8, 4, 4, accent)
    hb.outline(dark)
    hs = Tile()
    hs.r(3, 4, 10, 9, body)
    hs.r(7, 6, 4, 3, dark)
    hs.p(9, 7, eye)
    hs.r(5, 10, 5, 2, accent)
    hs.outline(dark)
    ht = Tile()
    ht.r(3, 3, 10, 10, body)
    ht.r(4, 4, 8, 8, mix(body, "#ffffff", 0.2))
    ht.poly([(3, 3), (0, 0), (6, 2)], dark)
    ht.poly([(12, 3), (15, 0), (9, 2)], dark)
    ht.outline(dark)
    hbot = Tile()
    hbot.r(4, 4, 8, 8, dark)
    head = faces(hf.im, hb.im, hs.im, hs.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                 ht.im, hbot.im)

    bf = Tile()
    bf.r(3, 2, 10, 12, body)
    for y in range(3, 14, 2):
        bf.r(4, y, 8, 1, mix(body, dark, 0.25))
    bf.r(5, 6, 6, 4, accent)
    bf.r(6, 7, 4, 2, eye)
    bf.r(3, 13, 4, 2, dark)
    bf.r(9, 13, 4, 2, dark)
    bf.outline(dark)
    bb = Tile()
    bb.r(3, 2, 10, 12, body)
    for y in range(3, 14, 2):
        bb.r(4, y, 8, 1, mix(body, dark, 0.25))
    bb.r(6, 8, 4, 3, accent)
    bb.outline(dark)
    bs = Tile()
    bs.r(3, 3, 10, 10, body)
    bs.r(4, 5, 8, 1, dark)
    bs.r(4, 8, 8, 1, dark)
    bs.r(4, 11, 8, 1, dark)
    bs.outline(dark)
    bt = Tile()
    bt.r(3, 3, 10, 10, body)
    bt.r(5, 5, 6, 6, accent)
    bt.outline(dark)
    bbot = Tile()
    bbot.r(3, 3, 10, 10, dark)
    body_faces = faces(bf.im, bb.im, bs.im, bs.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                       bt.im, bbot.im)
    return [body_faces, head]


def mushroom_faces(pal):
    # Head box is the cap, body box is the little stem-person.
    hf = Tile()
    cap, spot, dark, body = pal["body"], pal["light"], pal["dark"], pal["accent"]
    hf.r(1, 2, 14, 7, cap)
    hf.r(2, 1, 12, 2, mix(cap, "#ffffff", 0.15))
    hf.r(3, 4, 2, 2, spot)
    hf.r(7, 3, 2, 2, spot)
    hf.r(11, 4, 2, 2, spot)
    hf.r(5, 9, 6, 5, body)
    hf.r(6, 10, 2, 2, dark)
    hf.r(9, 10, 2, 2, dark)
    hf.p(7, 12, dark)
    hf.outline(dark)
    hb = Tile()
    hb.r(1, 2, 14, 7, cap)
    hb.r(2, 1, 12, 2, mix(cap, "#ffffff", 0.1))
    hb.r(4, 4, 2, 2, spot)
    hb.r(10, 5, 2, 2, spot)
    hb.r(5, 9, 6, 5, body)
    hb.outline(dark)
    hs = Tile()
    hs.r(1, 2, 14, 7, cap)
    hs.r(3, 4, 2, 2, spot)
    hs.r(10, 3, 2, 2, spot)
    hs.r(5, 9, 6, 5, body)
    hs.outline(dark)
    ht = Tile()
    ht.r(2, 2, 12, 12, cap)
    ht.r(4, 4, 3, 3, spot)
    ht.r(9, 6, 3, 3, spot)
    ht.r(6, 10, 2, 2, spot)
    ht.outline(dark)
    hbot = Tile()
    hbot.r(3, 3, 10, 10, dark)
    head = faces(hf.im, hb.im, hs.im, hs.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                 ht.im, hbot.im)

    bf = Tile()
    bf.r(4, 2, 8, 12, body)
    bf.r(5, 2, 6, 2, mix(body, "#ffffff", 0.2))
    bf.r(6, 8, 4, 4, spot)
    bf.r(4, 13, 3, 2, dark)
    bf.r(9, 13, 3, 2, dark)
    bf.outline(dark)
    bb = Tile()
    bb.r(4, 2, 8, 12, body)
    bb.r(5, 4, 6, 6, mix(body, dark, 0.25))
    bb.outline(dark)
    bs = Tile()
    bs.r(4, 3, 8, 11, body)
    bs.r(5, 5, 6, 2, spot)
    bs.outline(dark)
    bt = Tile()
    bt.r(4, 4, 8, 8, body)
    bt.outline(dark)
    bbot = Tile()
    bbot.r(4, 4, 8, 8, dark)
    body_faces = faces(bf.im, bb.im, bs.im, bs.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                       bt.im, bbot.im)
    return [body_faces, head]


# ---------------------------------------------------------------------------
# Wings and packs (back items)
# ---------------------------------------------------------------------------


def wing_faces(pal, box):
    """One folded wing slab; the renderer mirrors it for the other side.

    The tile is a transparent cut-out, not a filled rectangle: the root sits
    at the TOP-left (the shoulder blade), the leading edge runs out to the
    tip, and the trailing edge hangs down in feather points. In the slab that
    puts the root at the spine, the tip past the arm, and the feathers down
    the back - which is what makes it read as a wing instead of a plank.
    """
    root, mid, tip = pal["body"], pal["light"], pal["accent"]
    dark, edge = pal["dark"], pal["eye"]

    def feather_face(flip=False):
        t = Tile()
        silhouette = [(0, 0), (5, 0), (9, 1), (13, 2), (15, 5),
                      (12, 6), (14, 9), (10, 8), (11, 12), (7, 10),
                      (7, 14), (3, 11), (2, 15), (0, 9)]
        mask = Image.new("L", (16, 16), 0)
        ImageDraw.Draw(mask).polygon(silhouette, fill=255)
        base = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        bd = ImageDraw.Draw(base)
        bd.polygon(silhouette, fill=C(mid))
        # Feather bands radiate from the shoulder root to each trailing point.
        bands = [(12, 6), (14, 9), (11, 12), (7, 14), (2, 15)]
        for index, point in enumerate(bands):
            bd.polygon([(1, 1), point, (point[0] - 1, point[1]), (1, 3)],
                       fill=C(root if index % 2 == 0 else shade(root, -0.16)))
            bd.point(point, fill=C(tip))
            bd.point((point[0] - 1, point[1] - 1), fill=C(tip))
        # Bright leading edge from the root to the tip.
        bd.line([(1, 1), (6, 1), (10, 2), (14, 4)], fill=C(tip))
        base.putalpha(Image.composite(base.getchannel("A"), Image.new("L", (16, 16), 0), mask))
        t.im = base
        t.d = ImageDraw.Draw(t.im)
        t.outline(dark)
        if flip:
            t.im = t.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        return t.im

    main = feather_face()
    back = feather_face(flip=True)

    # The slab's EDGE faces must follow the cut-out, not the full rectangle.
    # A solid top strip is exactly the "bar floating over the shoulders" bug:
    # the front face is transparent there, but the box's top face still painted
    # a full-width bar.
    #
    # These tiles are built at their FINAL atlas size (depth*px wide, height*px
    # tall) instead of 16x16. The atlas resizer samples a 16x16 tile down to
    # 3px with NEAREST, which skips the one-pixel edge line entirely - the wing
    # then renders as a zero-thickness plane. Painting the thickness at the
    # target resolution makes it survive.
    mask = Image.new("L", (16, 16), 0)
    ImageDraw.Draw(mask).polygon([(0, 0), (5, 0), (9, 1), (13, 2), (15, 5),
                                  (12, 6), (14, 9), (10, 8), (11, 12), (7, 10),
                                  (7, 14), (3, 11), (2, 15), (0, 9)], fill=255)
    alpha = mask.load()

    def edge_face(profile, length, depth, vertical):
        """A thickness face sized exactly like its atlas slot.

        profile[i] says whether the silhouette touches the edge at source
        column/row i. length is the atlas length (height for a side face,
        width for a top/bottom face); depth is the slab's px thickness.
        """
        size = (depth, length) if vertical else (length, depth)
        t = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(t)
        for index in range(length):
            source = min(15, int((index + 0.5) * 16 / length))
            if not profile[source]:
                continue
            if vertical:
                draw.rectangle([0, index, depth - 1, index], fill=C(dark))
            else:
                draw.rectangle([index, 0, index, depth - 1], fill=C(dark))
        return t

    width, height, thickness = box["size"]
    px = box["px"]
    top_im = edge_face([alpha[x, 0] for x in range(16)], width * px,
                       thickness * px, vertical=False)
    bottom_im = edge_face([alpha[x, 15] for x in range(16)], width * px,
                          thickness * px, vertical=False)
    left_im = edge_face([alpha[0, y] for y in range(16)], height * px,
                        thickness * px, vertical=True)
    right_im = edge_face([alpha[15, y] for y in range(16)], height * px,
                         thickness * px, vertical=True)
    return faces(main, back, left_im, right_im, top_im, bottom_im)


def pack_faces(pal, emblem="gear"):
    leather, brass, dark, accent = pal["body"], pal["light"], pal["dark"], pal["accent"]

    def front_face(with_emblem):
        t = Tile()
        t.r(1, 2, 14, 13, leather)
        t.r(2, 2, 12, 2, mix(leather, "#ffffff", 0.18))
        t.r(2, 5, 12, 7, shade(leather, -0.18))
        t.r(3, 6, 10, 5, leather)
        # flap + buckle
        t.r(3, 2, 10, 3, mix(leather, "#ffffff", 0.1))
        t.r(7, 4, 2, 4, brass)
        t.p(7, 5, dark)
        if with_emblem:
            if emblem == "gear":
                t.r(5, 7, 6, 6, brass)
                t.r(6, 8, 4, 4, leather)
                t.r(7, 9, 2, 2, brass)
            elif emblem == "book":
                t.r(4, 7, 8, 6, accent)
                t.r(5, 7, 1, 6, mix(accent, "#ffffff", 0.4))
                t.r(7, 8, 4, 1, brass)
                t.r(7, 10, 4, 1, brass)
            elif emblem == "lantern":
                t.r(5, 6, 6, 7, dark)
                t.r(6, 7, 4, 5, accent)
                t.r(7, 8, 2, 3, "#fff2b0")
                t.r(6, 5, 4, 1, brass)
            elif emblem == "shell":
                t.r(4, 6, 8, 7, accent)
                t.r(6, 8, 4, 3, brass)
                t.p(5, 7, brass)
                t.p(10, 7, brass)
            elif emblem == "banner":
                t.r(5, 5, 6, 8, accent)
                t.r(6, 6, 4, 2, "#ffffff")
                t.r(7, 9, 2, 2, "#ffffff")
        # straps
        t.r(2, 2, 2, 5, dark)
        t.r(12, 2, 2, 5, dark)
        t.outline(dark)
        return t.im

    side = Tile()
    side.r(2, 2, 12, 13, shade(leather, -0.1))
    side.r(3, 4, 10, 8, leather)
    side.r(3, 3, 10, 2, brass)
    side.outline(dark)
    top = Tile()
    top.r(2, 2, 12, 12, mix(leather, "#ffffff", 0.12))
    top.r(4, 4, 8, 8, leather)
    top.r(7, 3, 2, 10, dark)
    top.outline(dark)
    bottom = Tile()
    bottom.r(2, 2, 12, 12, dark)
    bottom.r(4, 4, 8, 8, shade(leather, -0.3))
    return faces(front_face(False), front_face(True),
                 side.im, side.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                 top.im, bottom.im)


# ---------------------------------------------------------------------------
# Palettes + item table
# ---------------------------------------------------------------------------

PALETTES = {
    "ember_fox": dict(body="#e8722c", light="#f7d9a8", dark="#6b2e12",
                      accent="#ffc24d", eye="#2b1a10"),
    "moss_frog": dict(body="#4e9b3a", light="#cfe8a0", dark="#23471c",
                      accent="#7ed957", eye="#f2e85c"),
    "lantern_moth": dict(body="#e8dcc0", light="#c9b48a", dark="#5a4632",
                         accent="#ffc857", eye="#3a2e22"),
    "frost_cub": dict(body="#bfe3f2", light="#eaf7fc", dark="#5c8fa8",
                      accent="#8fd3ee", eye="#2f6e8c"),
    "cloud_serpent": dict(body="#ddebf7", light="#ffffff", dark="#7c9bb5",
                          accent="#a9cbe8", eye="#e8b44a"),
    "gear_imp": dict(body="#8a8f98", light="#c9cdd4", dark="#3a3e45",
                     accent="#c9a24b", eye="#ff7a3c"),
    "spore_sprite": dict(body="#c94b3b", light="#f3e7d0", dark="#5a2a22",
                         accent="#e8dcc0", eye="#2b1a10"),
    "star_owl": dict(body="#3b3f73", light="#6a6fa8", dark="#1e2040",
                     accent="#f4e9b8", eye="#f4c95d"),
    "tide_turtle": dict(body="#3e8e8a", light="#cfe8d8", dark="#1f4644",
                        accent="#7ed9c8", eye="#f4c95d", shell="#2f6f6b"),
    "pumpkin_pal": dict(body="#e07a2e", light="#f2a24e", dark="#7a3a14",
                        accent="#4e8b3a", eye="#ffe08a"),
    "ember_wings": dict(body="#e8722c", light="#ffb347", dark="#7a2e12",
                        accent="#ffe08a", eye="#c94b3b"),
    "frost_wings": dict(body="#bfe3f2", light="#eaf7fc", dark="#5c8fa8",
                        accent="#ffffff", eye="#8fd3ee"),
    "leaf_wings": dict(body="#4e9b3a", light="#7ed957", dark="#23471c",
                       accent="#cfe8a0", eye="#2f6f2a"),
    "void_wings": dict(body="#2a2140", light="#4b3a73", dark="#120c20",
                       accent="#b98cff", eye="#6a4fb3"),
    "aurora_wings": dict(body="#3ecfb2", light="#7c6cf0", dark="#1e4a5a",
                         accent="#e8fffa", eye="#3ecfb2"),
    "gear_pack": dict(body="#7a4b2a", light="#c9a24b", dark="#3a2414",
                      accent="#ff7a3c", eye="#c9a24b"),
    "scholar_pack": dict(body="#8a5a34", light="#c9a24b", dark="#3a2414",
                         accent="#c94b3b", eye="#f3e7d0"),
    "lantern_pack": dict(body="#3a3e45", light="#c9a24b", dark="#1e2024",
                         accent="#ffc857", eye="#fff2b0"),
    "shell_pack": dict(body="#2f6f6b", light="#cfe8d8", dark="#1f4644",
                       accent="#3e8e8a", eye="#7ed9c8"),
    "banner_pack": dict(body="#5a3a22", light="#c9a24b", dark="#2a1a10",
                        accent="#4b8bd9", eye="#e8dcc0"),
}


def _creature(item_id, name, blurb, pal, **art):
    p = PALETTES[pal]
    return dict(
        id=item_id, slot="shoulder", name=name, blurb=blurb,
        boxes=[
            dict(origin=[-8.0, -2.0, -1.5], size=[4, 3, 3], px=3, part=0),
            dict(origin=[-8.0, -5.5, -2.0], size=[4, 4, 4], px=3, part=1),
        ],
        _faces=creature_faces(p, **art),
    )


def _special(item_id, name, blurb, pal, painter):
    p = PALETTES[pal]
    return dict(
        id=item_id, slot="shoulder", name=name, blurb=blurb,
        boxes=[
            dict(origin=[-8.0, -2.0, -1.5], size=[4, 3, 3], px=3, part=0),
            dict(origin=[-8.0, -5.5, -2.0], size=[4, 4, 4], px=3, part=1),
        ],
        _faces=painter(p),
    )


def _wings(item_id, name, blurb, pal):
    p = PALETTES[pal]
    box = dict(origin=[1.0, 0.0, 2.2], size=[10, 13, 1], px=3,
               part=0, mirror=True)
    return dict(
        id=item_id, slot="back", name=name, blurb=blurb,
        boxes=[box],
        _faces=[wing_faces(p, box)],
    )


def _pack(item_id, name, blurb, pal, emblem):
    p = PALETTES[pal]
    return dict(
        id=item_id, slot="back", name=name, blurb=blurb,
        boxes=[
            dict(origin=[-4.0, 2.0, 2.2], size=[8, 9, 4], px=3, part=0),
        ],
        _faces=[pack_faces(p, emblem)],
    )


ITEMS = [
    _creature("shoulder_ember_fox", "Ember Fox",
              "A warm little fox that curls up on your shoulder.",
              "ember_fox", ear="point", muzzle="snout", marking="spots",
              body_style="belly", back_style="tail", side_style="spots"),
    _creature("shoulder_moss_frog", "Moss Frog",
              "A pond-green frog with a very serious expression.",
              "moss_frog", ear="none", muzzle="wide", marking="spots",
              body_style="belly", back_style="spots", side_style="spots"),
    _special("shoulder_lantern_moth", "Lantern Moth",
             "Its lantern tail glows softly in the dark.",
             "lantern_moth", moth_faces),
    _creature("shoulder_frost_cub", "Frost Cub",
              "A snow-pale cub that never seems to feel the cold.",
              "frost_cub", ear="round", muzzle="snout", marking="mask",
              body_style="belly", back_style="tail", side_style="plain"),
    _creature("shoulder_cloud_serpent", "Cloud Serpent",
              "A tiny sky serpent coiled into a comfortable knot.",
              "cloud_serpent", ear="tuft", muzzle="snout", marking="star",
              body_style="belly", back_style="spots", side_style="spots"),
    _creature("shoulder_gear_imp", "Gear Imp",
              "A workshop imp wearing brass goggles and a red scarf.",
              "gear_imp", ear="point", muzzle="snout", marking="goggles",
              body_style="scarf", back_style="scarf", side_style="scarf"),
    _special("shoulder_spore_sprite", "Spore Sprite",
             "A mushroom-cap friend with a tiny, curious face.",
             "spore_sprite", mushroom_faces),
    _creature("shoulder_star_owl", "Star Owl",
              "A night owl whose feathers hold a small constellation.",
              "star_owl", ear="tuft", muzzle="beak", marking="star",
              body_style="belly", back_style="spots", side_style="spots"),
    _creature("shoulder_tide_turtle", "Tide Turtle",
              "A pocket-sized turtle with a wave-worn shell.",
              "tide_turtle", ear="none", muzzle="wide", marking="spots",
              body_style="shell", back_style="shell", side_style="shell"),
    _special("shoulder_pumpkin_pal", "Pumpkin Pal",
             "A grinning pumpkin companion for the harvest season.",
             "pumpkin_pal", lambda p: creature_faces(
                 p, ear="none", muzzle="none", marking=None,
                 body_style="pumpkin", back_style="glow", side_style="glow")),

    _wings("back_ember_wings", "Ember Wings",
           "Feathers that smoulder orange at the tips.", "ember_wings"),
    _wings("back_frost_wings", "Frost Wings",
           "Pale wings edged in fresh snow.", "frost_wings"),
    _wings("back_leaf_wings", "Leaf Wings",
           "Grown from a single, very ambitious seed.", "leaf_wings"),
    _wings("back_void_wings", "Void Wings",
           "Dark wings scattered with distant violet stars.", "void_wings"),
    _wings("back_aurora_wings", "Aurora Wings",
           "Wings that carry a piece of the northern lights.", "aurora_wings"),
    _pack("back_gear_pack", "Gear Pack",
          "A sturdy pack with a brass gear clasp.", "gear_pack", "gear"),
    _pack("back_scholar_pack", "Scholar Pack",
          "A leather pack with room for one more book.", "scholar_pack", "book"),
    _pack("back_lantern_pack", "Lantern Pack",
          "A dark travel pack with a warm lantern.", "lantern_pack", "lantern"),
    _pack("back_shell_pack", "Shell Pack",
          "A shell-backed pack, waterproof and steady.", "shell_pack", "shell"),
    _pack("back_banner_pack", "Banner Pack",
          "A travel pack flying a small Cubeon banner.", "banner_pack", "banner"),
]


# ---------------------------------------------------------------------------
# Atlas packing + output
# ---------------------------------------------------------------------------


def box_atlas_size(box):
    w, h, d = box["size"]
    px = box["px"]
    return (2 * (w + d)) * px, (h + d) * px


def render_item(item):
    """Paint one item's PNG and fill in its box UVs. Returns (image, meta)."""
    boxes = item["boxes"]
    painted = item["_faces"]

    # Stack each box's atlas vertically. Width is shared so the PNG stays a
    # simple rectangle; a box's own atlas may be narrower than the sheet.
    sizes = [box_atlas_size(box) for box in boxes]
    sheet_w = max(w for w, _ in sizes)
    sheet_h = sum(h for _, h in sizes) + 2 * (len(boxes) - 1)
    sheet_w = max(4, (sheet_w + 3) // 4 * 4)
    sheet_h = max(4, (sheet_h + 3) // 4 * 4)
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))

    cursor = 0
    out_boxes = []
    for index, box in enumerate(boxes):
        box["uv"] = [0, cursor]
        rects = face_rects(box)
        tiles = painted[box["part"]]
        for face, (x, y, w, h) in rects.items():
            tile = tiles[face]
            if tile.size != (w, h):
                tile = tile.resize((w, h), Image.Resampling.NEAREST)
            sheet.alpha_composite(tile, (x, y))
        bw, bh = sizes[index]
        cursor += bh + 2
        out_boxes.append({
            "origin": [float(v) for v in box["origin"]],
            "size": [int(v) for v in box["size"]],
            "px": int(box["px"]),
            "uv": [int(box["uv"][0]), int(box["uv"][1])],
            "mirror": bool(box.get("mirror", False)),
        })
    return sheet, out_boxes


def main():
    os.makedirs(LAUNCHER_DIR, exist_ok=True)
    os.makedirs(MOD_TEXTURE_DIR, exist_ok=True)
    os.makedirs(MOD_CATALOG_DIR, exist_ok=True)

    catalog = {"version": 1, "anchors": ANCHORS, "items": []}
    for item in ITEMS:
        image, boxes = render_item(item)
        name = item["id"] + ".png"
        for folder in (LAUNCHER_DIR, MOD_TEXTURE_DIR):
            image.save(os.path.join(folder, name), optimize=True)
        catalog["items"].append({
            "id": item["id"],
            "slot": item["slot"],
            "name": item["name"],
            "blurb": item["blurb"],
            "texture": name,
            "tex_w": image.width,
            "tex_h": image.height,
            "boxes": boxes,
        })

    text = json.dumps(catalog, indent=2) + "\n"
    for folder in (LAUNCHER_DIR, MOD_CATALOG_DIR):
        with open(os.path.join(folder, "catalog.json"), "w", encoding="utf-8") as fh:
            fh.write(text)
    print(f"generated {len(catalog['items'])} cosmetics -> {LAUNCHER_DIR}")
    print(f"mirrored bundle -> {MOD_TEXTURE_DIR}")


if __name__ == "__main__":
    main()
