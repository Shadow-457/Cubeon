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
import math
import random
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

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
# The pet sits one model unit outward from the shoulder centre, leaving room
# for its independent head turns beside the player's standing head.
ANCHORS = {
    "shoulder": [-7.0, 0.0, 0.0],
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


def _pet_surface(pal, face, *, head=True):
    """32px opaque pixel art: soft edges, two-pixel shading and deliberate fur marks."""
    t = Tile(32)
    base = pal['body']
    amount = {'front': .03, 'back': -.04, 'left': -.03,
              'right': -.06, 'top': .13, 'bottom': -.14}[face]
    for y in range(0, 32, 2):
        t.r(0, y, 32, 2, shade(base, amount + .08 - y / 240))
    rim = mix(base, pal['dark'], .18)
    t.vline(0, 0, 32, rim)
    t.vline(31, 0, 32, rim)
    t.hline(1, 31, 30, rim)
    t.hline(2, 1, 28, shade(base, .22))
    # Intentional small tufts rather than random noise.
    for x, y in ((3, 7), (26, 8), (2, 20), (27, 22), (11, 3), (19, 5)):
        t.hline(x, y, 2, shade(base, .12))
        t.p(x + 1, y + 1, shade(base, -.05))
    return t


def _pet_eye(t, x, y, pal, width=7, height=9):
    """Rounded dark eyes, coloured lower iris, a big reflection and a small sparkle."""
    ink = mix(pal['dark'], '#18202c', .65)
    t.r(x + 1, y, width - 2, height, ink)
    t.r(x, y + 1, width, height - 2, ink)
    iris = mix(pal['eye'], pal['accent'], .35)
    t.r(x + 1, y + height - 3, width - 2, 2, iris)
    t.r(x + 1, y + 1, 2, 3, '#fff9ed')
    t.p(x + 3, y + 1, '#fff9ed')
    t.p(x + width - 2, y + height - 4, shade(iris, .5))


def _pet_cheeks(t, pal, y=23):
    blush = mix(pal['body'], '#f4a8a6', .6)
    for x in (3, 24):
        t.r(x, y, 5, 2, blush)
        t.p(x + 1, y, mix(blush, '#fff1e3', .4))


def _pet_front(pal, species):
    t = _pet_surface(pal, 'front')
    body, light, accent = pal['body'], pal['light'], pal['accent']
    ink = mix(pal['dark'], '#18202c', .6)
    cream = mix(light, '#fff3df', .4)
    if species in ('ember_fox', 'gear_imp'):
        for x in (3, 23):
            t.poly([(x, 8), (x + 3, 1), (x + 7, 8)], shade(body, -.16))
            t.poly([(x + 2, 6), (x + 3, 3), (x + 5, 6)], mix(body, '#f6b2ad', .7))
    elif species == 'frost_cub':
        for x in (3, 23):
            t.r(x, 2, 6, 6, shade(body, -.10))
            t.r(x + 1, 3, 4, 3, mix(body, '#f4c4cb', .6))
    elif species in ('star_owl', 'cloud_serpent'):
        for x in (3, 24):
            t.poly([(x, 8), (x + 2, 1), (x + 5, 7)], accent)
            t.p(x + 2, 2, shade(accent, .4))
    if species == 'ember_fox':
        t.poly([(1, 19), (8, 18), (12, 23), (19, 23), (23, 18), (30, 19),
                (28, 28), (24, 30), (7, 30), (3, 28)], cream)
        for x in (5, 22):
            t.hline(x, 11, 5, shade(body, .35))
    elif species == 'frost_cub':
        t.r(3, 11, 11, 13, cream)
        t.r(18, 11, 11, 13, cream)
        t.r(7, 21, 18, 9, light)
    elif species == 'star_owl':
        for x in (7, 24):
            t.d.ellipse((x - 7, 10, x + 7, 26), fill=C(cream))
        t.p(15, 5, '#fff5d1')
        t.hline(13, 6, 5, '#fff5d1')
        t.vline(15, 4, 5, '#fff5d1')
    elif species in ('moss_frog', 'tide_turtle'):
        t.r(2, 22, 28, 7, light)
        t.hline(4, 22, 24, shade(light, .2))
        if species == 'moss_frog':
            t.poly([(13, 7), (11, 4), (16, 5), (20, 2), (20, 6), (16, 8)], accent)
            t.p(4, 10, shade(body, -.14)); t.p(26, 10, shade(body, -.14))
        else:
            t.poly([(12, 3), (19, 3), (21, 7), (16, 10), (10, 7)], accent)
            t.hline(13, 4, 5, shade(accent, .3))
    elif species == 'cloud_serpent':
        t.r(8, 24, 16, 6, cream)
        for x in (3, 25):
            t.r(x, 9, 4, 2, accent)
            t.p(x + 1, 8, shade(accent, .25))
        for x, y in ((12, 5), (16, 8), (19, 5)):
            t.hline(x, y, 2, shade(accent, -.12))
    elif species == 'lantern_moth':
        for x, sign in ((4, -1), (27, 1)):
            t.vline(x, 1, 8, pal['dark'])
            for y in (2, 4, 6):
                t.hline(x - 2 if sign < 0 else x, y, 3, accent)
        t.r(11, 6, 10, 4, cream)
        t.hline(8, 10, 16, shade(body, .3))
    elif species == 'spore_sprite':
        t.r(0, 0, 32, 18, shade(body, -.08))
        t.r(1, 1, 30, 3, shade(body, .2))
        for x, y, w in ((3, 6, 6), (13, 3, 5), (23, 7, 6)):
            t.r(x, y, w, 4, cream)
            t.r(x + 1, y, w - 2, 1, '#fffaf0')
        t.hline(0, 16, 32, pal['dark'])
        t.r(2, 18, 28, 14, pal['accent'])
        for x in (6, 23):
            _pet_eye(t, x, 20, pal, 4, 6)
        _pet_cheeks(t, pal, 27)
        t.hline(14, 28, 4, ink)
        return t.im
    elif species == 'pumpkin_pal':
        for x in (3, 10, 21, 28):
            t.vline(x, 3, 28, shade(body, -.10))
            t.vline(x + 1, 4, 26, shade(body, .12))
        t.r(13, 1, 6, 5, accent)
        t.poly([(17, 4), (22, 1), (27, 2), (22, 6)], shade(accent, .15))
    # Big eyes sit low on the face, leaving a soft, rounded forehead.
    for x in (6, 20):
        _pet_eye(t, x, 13, pal)
    if species == 'gear_imp':
        brass = pal['accent']
        for x in (4, 18):
            t.hline(x + 1, 11, 9, brass); t.hline(x + 1, 23, 9, shade(brass, -.25))
            t.vline(x, 12, 11, brass); t.vline(x + 10, 12, 11, brass)
            t.p(x + 1, 12, '#fff0bb'); t.p(x + 9, 22, '#fff0bb')
        t.hline(14, 16, 4, brass)
        t.r(10, 26, 12, 4, cream)
    _pet_cheeks(t, pal)
    if species in ('star_owl', 'lantern_moth'):
        t.poly([(13, 24), (18, 24), (16, 28)], accent)
        t.hline(14, 24, 3, shade(accent, .4))
    elif species in ('moss_frog', 'tide_turtle', 'pumpkin_pal'):
        t.hline(12, 27, 8, ink)
        t.p(11, 26, ink); t.p(20, 26, ink)
    else:
        t.r(14, 24, 4, 2, ink)
        t.p(14, 24, shade(ink, .3))
        t.p(15, 26, ink)
        t.hline(12, 28, 3, shade(light, -.25))
        t.hline(17, 28, 3, shade(light, -.25))
    return t.im


def pet_faces(pal, species):
    """Every pet gets matching front, rear, profile, crown and underside artwork."""
    head = {}
    body = {}
    for face in ('front', 'back', 'left', 'right', 'top', 'bottom'):
        h = _pet_surface(pal, face)
        b = _pet_surface(pal, face, head=False)
        light, accent = pal['light'], pal['accent']
        if face == 'front':
            head[face] = _pet_front(pal, species)
            b.d.ellipse((6, 3, 25, 29), fill=C(mix(light, '#fff1df', .25)))
            b.hline(11, 5, 10, shade(light, .3))
            for x, y in ((9, 11), (17, 14), (12, 21)):
                b.hline(x, y, 4, mix(light, pal['body'], .18))
                b.hline(x + 1, y + 1, 2, shade(light, .16))
            for x in (1, 24):
                b.r(x, 23, 7, 8, shade(pal['body'], -.1))
                b.r(x + 1, 27, 5, 2, mix(light, '#f0b1af', .35))
                b.p(x + 2, 29, shade(pal['body'], -.25))
            if species == 'gear_imp':
                b.r(0, 2, 32, 6, '#c85c62'); b.hline(1, 3, 30, '#ef9990')
                b.r(22, 8, 6, 13, '#c85c62'); b.hline(23, 19, 4, '#edb89b')
            elif species == 'lantern_moth':
                for y in (8, 13, 18):
                    b.hline(5, y, 22, shade(pal['body'], -.13))
                b.r(9, 11, 14, 12, accent); b.r(11, 13, 10, 8, '#ffeab1')
                b.r(13, 14, 6, 5, '#fff9e0')
            elif species == 'spore_sprite':
                b.r(6, 2, 20, 25, pal['accent'])
                b.r(6, 24, 7, 6, pal['light']); b.r(19, 24, 7, 6, pal['light'])
        else:
            # Small coherent directional tufts / scale flecks over the coat.
            for x, y in ((6, 7), (16, 11), (23, 6), (8, 21), (21, 24)):
                h.hline(x, y, 3, shade(pal['body'], .17))
                b.hline(x, y, 3, shade(pal['body'], -.09))
            if face in ('left', 'right'):
                h.r(19, 23, 12, 7, mix(light, '#fff3df', .35))
                _pet_eye(h, 21, 14, pal, 6, 8)
                h.r(18, 23, 4, 2, mix(pal['body'], '#f4a8a6', .55))
                h.r(5, 3, 7, 5, accent)
            if species == 'ember_fox' and face == 'back':
                b.poly([(16, 3), (24, 8), (28, 23), (19, 29), (13, 22)], accent)
                b.poly([(13, 22), (19, 24), (25, 22), (19, 29)], light)
        if species == 'tide_turtle' and face != 'bottom':
            if face != 'front':
                b.r(1, 2, 30, 28, pal['shell'])
                for x, y in ((3, 4), (17, 4), (10, 13), (3, 22), (22, 22)):
                    b.poly([(x, y + 2), (x + 3, y), (x + 8, y + 2),
                            (x + 8, y + 6), (x + 4, y + 8), (x, y + 6)], accent)
                    b.hline(x + 3, y + 1, 3, shade(accent, .3))
        if species == 'star_owl' and face != 'front':
            for x, y in ((4, 12), (12, 17), (21, 12), (7, 24), (23, 25)):
                b.poly([(x, y), (x + 4, y + 3), (x + 8, y)], light)
            h.hline(9, 5, 5, accent); h.vline(11, 3, 5, accent)
        if species == 'spore_sprite' and face != 'front':
            if face in ('left', 'right', 'back'):
                h.hline(0, 16, 32, pal['dark'])
                h.r(0, 18, 32, 14, pal['accent'])
            for x, y in ((4, 5), (19, 9), (10, 22)):
                if face == 'top' or y < 16:
                    h.r(x, y, 6, 4, pal['light'])
            b.r(4, 3, 24, 26, pal['accent'])
        if face not in head:
            head[face] = h.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if face == 'right' else h.im
        body[face] = b.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if face == 'right' else b.im
    return [body, head]


# ---------------------------------------------------------------------------
# Wings and packs (back items)
# ---------------------------------------------------------------------------


WING_SIZE = (160, 176)
PRIMARY_FEATHERS = [
    ((10, 49), (69, 169), 12, -11),
    ((16, 44), (106, 148), 14, -16),
    ((22, 40), (139, 112), 14, -17),
    ((27, 37), (156, 73), 13, -15),
    ((30, 33), (155, 35), 12, -11),
    ((31, 30), (128, 3), 11, -7),
]
COVERT_FEATHERS = [
    ((9, 47), (49, 104), 10, -7),
    ((14, 41), (87, 73), 11, -9),
    ((19, 33), (101, 29), 10, -5),
    ((5, 44), (29, 69), 7, -2),
    ((5, 44), (43, 36), 7, -2),
]
WING_PALETTE = ["#211421", "#342037", "#542338", "#7c2939", "#a63236",
                "#cf4533", "#ed6535", "#ff9143", "#ffbc59", "#ffe18c", "#fff4c9"]
WING_RAMPS = {
    "frost": ["#111c35", "#1d3450", "#28536d", "#337691", "#409ab2",
              "#61bdd0", "#87dce7", "#aaf0f2", "#c8fbf7", "#e8ffff", "#ffffff"],
    "leaf": ["#142822", "#203d28", "#2d5731", "#3c7131", "#519437",
             "#72b944", "#9bda5b", "#c6eb72", "#e1f68c", "#f1ffb5", "#ffffdc"],
    "void": ["#100e25", "#201839", "#352153", "#4d2b76", "#663697",
             "#894bbb", "#a364d8", "#bf8bec", "#d9b3ff", "#eee0ff", "#ffffff"],
    "aurora": ["#121c36", "#242949", "#393665", "#4f4398", "#6c58c4",
               "#8b72e7", "#689ddd", "#59c8c7", "#7ee7d9", "#b0fff0", "#eefffc"],
}


def _wing_feather(start, end, width, curve=0, seed=0, molten=True, joined=False):
    """Paint a tapered feather with separated vanes and stepped molten veins."""
    sx, sy = start
    dx, dy = end[0] - sx, end[1] - sy
    length = math.hypot(dx, dy)
    ax, ay = dx / length, dy / length
    nx, ny = -ay, ax

    def point(t, side=0):
        offset = curve * math.sin(math.pi * t) + side
        return (round(sx + dx * t + nx * offset), round(sy + dy * t + ny * offset))

    def breadth(t):
        base = width * math.sin(math.pi * (0.07 + t * 0.93)) ** 0.72 * (1 - 0.18 * t)
        # Broader inner vanes overlap farther out along the fan. The final
        # fifth keeps V2's exact tapered tips and open outer silhouette.
        overlap = 1 + 0.75 * max(0, 1 - max(0, t - 0.5) / 0.3) if joined else 1
        return base * overlap

    steps = 32
    polygon = []
    for sign in (-1, 1):
        indices = range(steps + 1) if sign == -1 else range(steps, -1, -1)
        for i in indices:
            t = i / steps
            notch = 0.67 if i % 4 == (seed % 3) and 0.45 < t < 0.93 else 1
            polygon.append(point(t, sign * breadth(t) * notch))
    mask = Image.new("L", WING_SIZE)
    ImageDraw.Draw(mask).polygon(polygon, fill=255)
    inset = mask.filter(ImageFilter.MinFilter(3))
    tile = Image.new("RGBA", WING_SIZE)
    pixels = tile.load()
    rim = ImageChops.subtract(mask, inset)
    for y in range(WING_SIZE[1]):
        for x in range(WING_SIZE[0]):
            if not mask.getpixel((x, y)):
                continue
            t = max(0, min(1, ((x - sx) * ax + (y - sy) * ay) / length))
            side = ((x - sx) * nx + (y - sy) * ny) - curve * math.sin(math.pi * t)
            # The brightest area is the outer feather; the root stays volcanic.
            heat = 1.5 + 7.5 * t
            heat += 0.6 if side < -1 else -0.7
            # Parallel vanes are deliberate bands, rather than random noise.
            if (int(t * length + abs(side) * 0.75) + seed) % 7 < 2:
                heat -= 1.6
            if abs(side) > breadth(t) * 0.72:
                heat -= 1.2
            colour = WING_PALETTE[max(0, min(10, int(heat)))]
            if rim.getpixel((x, y)):
                colour = "#281728" if t < 0.9 else "#ffb747"
            pixels[x, y] = (*bytes.fromhex(colour[1:]), 255)
    drawing = ImageDraw.Draw(tile)
    # Warm bevel along the leading side and a pale, sharp final tip.
    edge = [point(i / steps, -breadth(i / steps) * 0.76) for i in range(8, 31)]
    drawing.line(edge, fill="#f7843d", width=1)
    drawing.line([point(0.87, -1), point(0.96), point(1)], fill="#fff4c9", width=2)
    if molten:
        vein = [point(t, math.sin(t * 33 + seed) * 1.1) for t in (0.18, 0.28, 0.4, 0.52, 0.65, 0.79, 0.92)]
        drawing.line(vein, fill="#a63b2c", width=5)
        drawing.line(vein, fill="#ff963e", width=3)
        drawing.line(vein, fill="#ffe6a0", width=1)
        for j, t in enumerate((0.33, 0.5, 0.67, 0.8)):
            sign = 1 if (j + seed) % 2 else -1
            crack = [point(t), point(t + 0.035, sign * breadth(t) * 0.3),
                     point(t + 0.02, sign * breadth(t) * 0.48),
                     point(t + 0.09, sign * breadth(t) * 0.75)]
            drawing.line(crack, fill="#fb9a43", width=2)
            drawing.line(crack[:3], fill="#ffe2a0", width=1)
    tile.putalpha(mask)
    return tile


def _ember_layers():
    """Independent vanes and shoulder armour; never merge them into a sheet."""
    layers = []
    # Long primary feathers, drawn trailing edge first. The rising upper
    # feathers and detached points give the wing its dramatic open fan.
    primaries = PRIMARY_FEATHERS
    for i, (start, end, width, curve) in enumerate(primaries):
        layers.append(_wing_feather(start, end, width, curve, i))
    # Distinct shorter layers over the primary roots; these are darker, broad
    # armoured feathers with the same copper rim and warm vein language.
    coverts = COVERT_FEATHERS[:3]
    for i, (start, end, width, curve) in enumerate(coverts):
        layers.append(_wing_feather(start, end, width, curve, i + 20, molten=i % 2 == 0))
    for i, end in enumerate(((29, 69), (43, 36))):
        layers.append(_wing_feather((5, 44), end, 7, -2, 40 + i, molten=False))
    # Obsidian shoulder armour, with a molten eye/rune at its centre.
    armour = Image.new("RGBA", WING_SIZE)
    drawing = ImageDraw.Draw(armour)
    drawing.polygon([(3, 39), (9, 29), (19, 26), (28, 33), (27, 47), (17, 59), (6, 57)],
                    fill="#281a2d", outline="#ba5634", width=2)
    drawing.line([(7, 40), (12, 33), (18, 31), (24, 35)], fill="#ffc267", width=1)
    drawing.polygon([(10, 42), (18, 35), (23, 41), (18, 49)], fill="#7c2939", outline="#ff9a43")
    drawing.polygon([(14, 41), (18, 37), (21, 41), (18, 46)], fill="#ffe9b0")
    drawing.line([(7, 48), (12, 50), (16, 54), (23, 47)], fill="#d8723d", width=1)
    layers.append(armour)
    # Tiny ember flecks stay inside the feathers and can be baked into texture.
    rng = random.Random(709)
    for _ in range(35):
        x, y = rng.randrange(25, 148), rng.randrange(10, 156)
        for layer in reversed(layers):
            if layer.getpixel((x, y))[3]:
                if layer.getpixel((x, y))[0] < 160:
                    ImageDraw.Draw(layer).point((x, y), fill="#ffb965")
                break
    return layers


def small_wing_art(pal):
    """Feather artwork used to build a closed silhouette with thin solid pieces.

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

    return main, back


def _wing_theme(image, pal):
    theme = pal.get("wing_theme", "ember")
    if theme != "ember":
        ramp = WING_RAMPS[theme]
        palette = [C(colour) for colour in WING_PALETTE]
        colours = {colour for count, colour in image.getcolors(image.width * image.height) if colour[3]}
        lookup = {colour: C(ramp[min(range(len(palette)), key=lambda i:
                    sum((colour[channel] - palette[i][channel]) ** 2 for channel in range(3)))])
                  for colour in colours}
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                if pixels[x, y][3]:
                    colour = lookup[pixels[x, y]]
                    if theme == "aurora":
                        shimmer = (math.sin(x / 18 + y / 27) + 1) / 2
                        colour = mix(colour, "#68f6cb" if shimmer > 0.5 else "#b97eff",
                                     0.25 * shimmer)
                    pixels[x, y] = colour
        # Theme-specific highlights remain inside the approved silhouette.
        def point(x, y, colour):
            if 0 <= x < image.width and 0 <= y < image.height and pixels[x, y][3]:
                pixels[x, y] = C(colour)
        if theme in ("frost", "void"):
            for x, y in ((43, 34), (77, 26), (111, 37), (122, 62),
                         (103, 90), (88, 113), (63, 132), (55, 79)):
                point(x, y, "#ffffff")
                for offset in (-2, -1, 1, 2):
                    point(x + offset, y, "#e5f7ff" if theme == "frost" else "#dfc0ff")
                    point(x, y + offset, "#e5f7ff" if theme == "frost" else "#dfc0ff")
                if theme == "frost":
                    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                        point(x + dx, y + dy, "#c0f7ff")
        elif theme == "leaf":
            for x, y in ((51, 52), (83, 63), (110, 85), (71, 120)):
                for dx, dy in ((0, 0), (1, 0), (0, 1), (-1, 0)):
                    point(x + dx, y + dy, "#f5e993")
    return image, image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)


def _feather_mesh_art(image):
    """Two-pixel contour grid with full-resolution paint inside each vane.

    Interior colour detail stays native; merging tiny edge steps bounds the
    number of closed walls when eleven feathers are real independent volumes.
    """
    mask = image.getchannel("A").resize((80, 88), Image.Resampling.BOX)
    mask = mask.point(lambda value: 255 if value >= 128 else 0).resize(WING_SIZE, Image.Resampling.NEAREST)
    result = image.copy()
    source, pixels = image.load(), result.load()
    for y in range(image.height):
        for x in range(image.width):
            if not mask.getpixel((x, y)):
                pixels[x, y] = (0, 0, 0, 0)
                continue
            if mask.getpixel((x, y)) and not source[x, y][3]:
                nearby = [(dx*dx + dy*dy, source[x+dx, y+dy])
                          for dy in range(-2, 3) for dx in range(-2, 3)
                          if 0 <= x+dx < image.width and 0 <= y+dy < image.height and source[x+dx, y+dy][3]]
                if nearby:
                    pixels[x, y] = min(nearby, key=lambda candidate: candidate[0])[1]
    result.putalpha(mask)
    return result


def wing_layers(pal):
    return [_feather_mesh_art(_wing_theme(image, pal)[0]) for image in _ember_layers()]


def wing_art(pal):
    """Front-view composite for artwork checks; geometry keeps these layers apart."""
    image = Image.new("RGBA", WING_SIZE)
    for layer in wing_layers(pal):
        image.alpha_composite(layer)
    return image, image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)


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
    "ember_wings": dict(wing_theme="ember", body="#e8722c", light="#ffb347", dark="#7a2e12",
                        accent="#ffe08a", eye="#c94b3b"),
    "frost_wings": dict(wing_theme="frost", body="#bfe3f2", light="#eaf7fc", dark="#5c8fa8",
                        accent="#ffffff", eye="#8fd3ee"),
    "leaf_wings": dict(wing_theme="leaf", body="#4e9b3a", light="#7ed957", dark="#23471c",
                       accent="#cfe8a0", eye="#2f6f2a"),
    "void_wings": dict(wing_theme="void", body="#2a2140", light="#4b3a73", dark="#120c20",
                       accent="#b98cff", eye="#6a4fb3"),
    "aurora_wings": dict(wing_theme="aurora", body="#3ecfb2", light="#7c6cf0", dark="#1e4a5a",
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


def sealed_faces(pal, painted):
    """Opaque cuboid faces: sprite margins must not punch holes in solid pets/packs."""
    amounts = {"front": 0.02, "back": -0.12, "left": -0.08,
               "right": -0.16, "top": 0.12, "bottom": -0.25}
    output = []
    for part in painted:
        faces_out = {}
        for face, tile in part.items():
            filled = Image.new("RGBA", tile.size, C(shade(pal["body"], amounts[face])))
            filled.alpha_composite(tile)
            faces_out[face] = filled
        output.append(faces_out)
    return output


def silhouette_rectangles(image):
    """Non-overlapping opaque runs, merged vertically on the native pixel grid."""
    alpha = image.getchannel("A")
    output, active = [], {}
    for y in range(image.height):
        spans = []
        x = 0
        while x < image.width:
            if not alpha.getpixel((x, y)):
                x += 1
                continue
            left = x
            while x < image.width and alpha.getpixel((x, y)):
                x += 1
            spans.append((left, x))
        current = {}
        for left, right in spans:
            key = (left, right)
            rectangle = active.pop(key, [left, y, right - left, 0])
            rectangle[3] += 1
            current[key] = rectangle
        output.extend(active.values())
        active = current
    output.extend(active.values())
    return output


def _creature(item_id, name, blurb, pal):
    p = PALETTES[pal]
    return dict(
        id=item_id, slot="shoulder", name=name, blurb=blurb,
        boxes=[
            dict(origin=[-9.0, -2.0, -1.5], size=[4, 3, 3], px=8, part=0,
                 motion="body", pivot=[-7, 1, 0]),
            dict(origin=[-9.0, -5.5, -2.0], size=[4, 4, 4], px=8, part=1,
                 motion="head", pivot=[-7, -2, 0]),
        ],
        _faces=sealed_faces(p, pet_faces(p, pal)),
    )


def wing_rectangles(image, limit=36, strip=0):
    """Bounded opaque caps; no transparent slab, no hidden interior walls."""
    alpha = image.getchannel("A")
    used = set()
    output = []
    for y in range(image.height):
        x = 0
        while x < image.width:
            if not alpha.getpixel((x, y)) or (x, y) in used:
                x += 1
                continue
            width = 1
            while (x + width < image.width and width < limit
                   and alpha.getpixel((x + width, y)) and (x + width, y) not in used):
                width += 1
            height = 1
            while (y + height < image.height and height < limit
                   and all(alpha.getpixel((xx, y + height)) and (xx, y + height) not in used
                           for xx in range(x, x + width))):
                height += 1
            used.update((xx, yy) for yy in range(y, y + height) for xx in range(x, x + width))
            output.append((x, y, width, height, ["front", "back"]))
            x += width
    # Only native silhouette edges get thickness. Each wall shares the cap rig.
    for side, dx, dy in (("left", 1, 0), ("right", -1, 0),
                         ("top", 0, -1), ("bottom", 0, 1)):
        mask = Image.new("RGBA", image.size)
        for y in range(image.height):
            for x in range(image.width):
                if alpha.getpixel((x, y)) and not (
                        0 <= x + dx < image.width and 0 <= y + dy < image.height
                        and alpha.getpixel((x + dx, y + dy))):
                    mask.putpixel((x, y), (255, 255, 255, 255))
        for x, y, width, height in silhouette_rectangles(mask):
            output.append((x, y, width, height, [side]))
    if strip:
        # All caps and horizontal walls share the same X breakpoints. A curved
        # feather is piecewise planar, so its cached three-anchor preview and
        # game quads agree and no resting T-junction can open.
        divided = []
        for x, y, width, height, visible in output:
            while width:
                piece = min(width, strip - x % strip)
                divided.append((x, y, piece, height, visible))
                x += piece
                width -= piece
        return divided
    return output


def _wings(item_id, name, blurb, pal, small=False):
    p = PALETTES[pal]
    px = 4
    if small:
        front, _ = small_wing_art(p)
        front = front.resize((40, 52), Image.Resampling.NEAREST)
        y_origin, depth, hinge = 2, 2, [1, 2, 2.45]
        guides = [((1, 1), end, 2, 0) for end in ((12, 6), (14, 9), (11, 12), (7, 14), (2, 15))]
        feathers = [dict(start=[1 + x * 2.5 / px, y_origin + y * 3.25 / px],
                         end=[1 + ex * 2.5 / px, y_origin + ey * 3.25 / px],
                         width=width * 2.5 / px, curve=0)
                    for (x, y), (ex, ey), width, curve in guides]
    else:
        layers = wing_layers(p)
        y_origin, depth, hinge = -9, 1, [2, 2, 2.25]
        feathers = [dict(start=[1 + x / px, y_origin + y / px],
                         end=[1 + ex / px, y_origin + ey / px],
                         width=width / px, curve=curve / px)
                    for (x, y), (ex, ey), width, curve in PRIMARY_FEATHERS + COVERT_FEATHERS]
        for index, feather in enumerate(feathers):
            old_layer = 2.25 + index * .375 if index < 6 else 5.0 + (index - 6) * .25
            root_layer = 2.125 + index / 64
            tip_curl = 3.5 + index * .25 if index < 6 else 1 + (index - 6) * .125
            # Keep the previous tip depth, but bring each root against the back.
            # Tiny root offsets avoid coplanar fighting between overlapping vanes.
            feather["curl"] = tip_curl + old_layer - root_layer
            feather["tilt"] = (index - 2) / 64 if index < 6 else 0
    surfaces = [(front, -1, 2.2)] if small else [
        (layer, index if index < len(feathers) else -1,
         2.125 + index / 64)
        for index, layer in enumerate(layers)]
    boxes, painted = [], []
    for front, feather_index, layer_z in surfaces:
        back = front.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        for left, top, width, height, visible in wing_rectangles(front, strip=0 if small else 16):
            face = front.crop((left, top, left + width, top + height))
            rear = back.crop((front.width - left - width, top, front.width - left, top + height))
            def cap(row):
                return face.crop((0, row, width, row + 1)).resize((width, depth), Image.Resampling.NEAREST)
            left_face = face.crop((width - 1, 0, width, height)).resize((depth, height), Image.Resampling.NEAREST)
            right_face = face.crop((0, 0, 1, height)).resize((depth, height), Image.Resampling.NEAREST)
            boxes.append(dict(origin=[1 + left / px, y_origin + top / px, layer_z],
                              size=[width / px, height / px, depth / px], px=px,
                              part=len(painted), mirror=True, faces=visible,
                              motion="wing", pivot=hinge,
                              **({"feather": feather_index} if not small else {})))
            painted.append(faces(face, rear, left_face, right_face, cap(0), cap(height - 1)))
    flat = None
    if not small:
        # Low-cost option: four alpha-cutout faces per pair, no volume walls or
        # per-feather weights. Preserve the hinge and overall wing animation.
        composite = Image.new("RGBA", WING_SIZE)
        for layer in layers:
            composite.alpha_composite(layer)
        blank = Image.new("RGBA", (1, 1))
        flat = dict(id=item_id, slot="back", name=name, blurb=blurb, wing_flare=True,
                    boxes=[dict(origin=[1, y_origin, 2.125], size=[40, 44, .25], px=px,
                                part=0, mirror=True, faces=["front", "back"],
                                motion="wing", pivot=hinge)],
                    _faces=[faces(composite, composite.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                                  blank, blank, blank, blank)])
    return dict(id=item_id, slot="back", name=name, blurb=blurb,
                boxes=boxes, feathers=feathers, wing_flare=not small,
                **({"separate_feathers": True, "_flat": flat} if not small else {}), _faces=painted)


def _pack(item_id, name, blurb, pal, emblem):
    p = PALETTES[pal]
    return dict(
        id=item_id, slot="back", name=name, blurb=blurb,
        boxes=[
            dict(origin=[-4.0, 2.0, 2.2], size=[8, 9, 4], px=3, part=0,
                 motion="pack", pivot=[0, 2, 2.2]),
        ],
        _faces=sealed_faces(p, [pack_faces(p, emblem)]),
    )


ITEMS = [
    _creature("shoulder_ember_fox", "Ember Fox",
              "A warm little fox with soft fur and a curious smile.", "ember_fox"),
    _creature("shoulder_moss_frog", "Moss Frog",
              "A cheerful pond-green frog with rosy cheeks.", "moss_frog"),
    _creature("shoulder_lantern_moth", "Lantern Moth",
              "A fluffy moth with sparkling eyes and a warm lantern tail.", "lantern_moth"),
    _creature("shoulder_frost_cub", "Frost Cub",
              "A snow-pale cub with tiny pink paws.", "frost_cub"),
    _creature("shoulder_cloud_serpent", "Cloud Serpent",
              "A tiny sky serpent with pearly scales and gentle eyes.", "cloud_serpent"),
    _creature("shoulder_gear_imp", "Gear Imp",
              "A workshop imp wearing brass goggles and a red scarf.", "gear_imp"),
    _creature("shoulder_spore_sprite", "Spore Sprite",
              "A mushroom-cap friend with a tiny, curious face.", "spore_sprite"),
    _creature("shoulder_star_owl", "Star Owl",
              "A fluffy night owl with a little constellation in its feathers.", "star_owl"),
    _creature("shoulder_tide_turtle", "Tide Turtle",
              "A pocket-sized turtle with a patterned sea-green shell.", "tide_turtle"),
    _creature("shoulder_pumpkin_pal", "Pumpkin Pal",
              "A smiling pumpkin companion for the harvest season.", "pumpkin_pal"),

    _wings("back_ember_wings", "Ember Wings (Giant)",
           "Giant phoenix feathers traced with molten gold.", "ember_wings"),
    _wings("back_frost_wings", "Frost Wings (Giant)",
           "Giant crystalline wings with bright frost veins.", "frost_wings"),
    _wings("back_leaf_wings", "Leaf Wings (Giant)",
           "Great emerald feathers with luminous living veins.", "leaf_wings"),
    _wings("back_void_wings", "Void Wings (Giant)",
           "Giant violet feathers scattered with distant stars.", "void_wings"),
    _wings("back_aurora_wings", "Aurora Wings (Giant)",
           "Great flowing feathers carrying the northern lights.", "aurora_wings"),
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

# Restore the original cute artwork and 10×13 dimensions alongside approved V3.
for theme in ("ember", "frost", "leaf", "void", "aurora"):
    ITEMS.append(_wings("back_" + theme + "_wings_small", theme.title() + " Wings (Small)",
                        "Original cute feather wings.", theme + "_wings", small=True))


# ---------------------------------------------------------------------------
# Atlas packing + output
# ---------------------------------------------------------------------------


def box_atlas_size(box):
    w, h, d = box["size"]
    px = box["px"]
    dimensions = ((2 * (w + d)) * px, (h + d) * px)
    if any(abs(value - round(value)) > 1e-6 for value in dimensions):
        raise ValueError("Cosmetic atlas dimensions must land on whole texels")
    return tuple(round(value) for value in dimensions)


def render_item(item):
    """Paint one item's PNG and fill in its box UVs. Returns (image, meta)."""
    boxes = item["boxes"]
    painted = item["_faces"]

    # Stack each box's atlas vertically. Width is shared so the PNG stays a
    # simple rectangle; a box's own atlas may be narrower than the sheet.
    sizes = [box_atlas_size(box) for box in boxes]
    placements = {}
    if "feathers" in item:
        # Compact shelves keep even detailed giant wings below old GPU limits.
        sheet_w = 512 if item.get("separate_feathers") else 256
        x = y = shelf_height = 0
        for index in sorted(range(len(sizes)), key=lambda i: -sizes[i][1]):
            width, height = sizes[index]
            if x + width > sheet_w:
                x = 0
                y += shelf_height + 2
                shelf_height = 0
            placements[index] = [x, y]
            x += width + 2
            shelf_height = max(shelf_height, height)
        sheet_h = y + shelf_height
    else:
        sheet_w = max(w for w, _ in sizes)
        sheet_h = sum(h for _, h in sizes) + 2 * (len(boxes) - 1)
        cursor = 0
        for index, (width, height) in enumerate(sizes):
            placements[index] = [0, cursor]
            cursor += height + 2
    sheet_w = max(4, (sheet_w + 3) // 4 * 4)
    sheet_h = max(4, (sheet_h + 3) // 4 * 4)
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))

    out_boxes = []
    for index, box in enumerate(boxes):
        box["uv"] = placements[index]
        rects = face_rects(box)
        tiles = painted[box["part"]]
        for face, rect in rects.items():
            if any(abs(value - round(value)) > 1e-6 for value in rect):
                raise ValueError("Every cosmetic face must land on whole texels")
            x, y, w, h = (round(value) for value in rect)
            tile = tiles[face]
            if tile.size != (w, h):
                tile = tile.resize((w, h), Image.Resampling.NEAREST)
            sheet.alpha_composite(tile, (x, y))
        out_boxes.append({
            "origin": [float(v) for v in box["origin"]],
            "size": [int(v) if float(v).is_integer() else float(v) for v in box["size"]],
            "px": int(box["px"]),
            "uv": [int(box["uv"][0]), int(box["uv"][1])],
            "mirror": bool(box.get("mirror", False)),
            "motion": box.get("motion", "none"),
            "pivot": box.get("pivot", [0, 0, 0]),
            **({"faces": box["faces"]} if "faces" in box else {}),
            **({"feather": box["feather"]} if "feather" in box else {}),
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
        entry = {
            "id": item["id"],
            "slot": item["slot"],
            "name": item["name"],
            "blurb": item["blurb"],
            "texture": name,
            "tex_w": image.width,
            "tex_h": image.height,
            "boxes": boxes,
            **({"feathers": item["feathers"]} if "feathers" in item else {}),
            **({"wing_flare": item["wing_flare"]} if "wing_flare" in item else {}),
            **({"separate_feathers": True} if item.get("separate_feathers") else {}),
        }
        if item.get("_flat"):
            flat_image, flat_boxes = render_item(item["_flat"])
            flat_name = item["id"] + "_flat.png"
            for folder in (LAUNCHER_DIR, MOD_TEXTURE_DIR):
                flat_image.save(os.path.join(folder, flat_name), optimize=True)
            entry["flat"] = dict(id=item["id"], slot=item["slot"], name=item["name"],
                                 texture=flat_name, tex_w=flat_image.width, tex_h=flat_image.height,
                                 boxes=flat_boxes, wing_flare=True)
        catalog["items"].append(entry)

    text = json.dumps(catalog, indent=2) + "\n"
    for folder in (LAUNCHER_DIR, MOD_CATALOG_DIR):
        with open(os.path.join(folder, "catalog.json"), "w", encoding="utf-8") as fh:
            fh.write(text)
    print(f"generated {len(catalog['items'])} cosmetics -> {LAUNCHER_DIR}")
    print(f"mirrored bundle -> {MOD_TEXTURE_DIR}")


if __name__ == "__main__":
    main()
