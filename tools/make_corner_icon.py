"""
Regenerates the two-person glyph the Friends corner button is drawn with.

Minecraft's bitmap font provider treats a texture as an alpha mask tinted by
the text colour, so the PNG below is written as WHITE pixels with the glyph
shape in the alpha channel - the grass-green comes from the style the label
carries (see the 26.x CornerIcon overlay), not from the texture. A white glyph
is also the only choice that renders identically whether a Minecraft version
multiplies the texture's RGB by the text colour or ignores it.

The grid is 8 wide x 8 tall: the two heads sit at columns 1-2 and 5-6 with a
clear vertical gap between them (the "two people" cue), a single shoulder band
joins them at row 2, and two body columns continue the head columns down. Rows
6 and 7 are left empty so the glyph never dips below the baseline.

Run from the repo root:
    python3 tools/make_corner_icon.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "mod", "src", "main", "resources",
                   "assets", "cubeon-friends", "textures", "font",
                   "cubeon_friends.png")

# '#' = opaque (white) pixel; '.' = transparent. Exactly 8 rows of 8 chars.
GRID = [
    "..##..##",
    "..##..##",
    ".######.",
    ".##..##.",
    ".##..##.",
    ".##..##.",
    "........",
    "........",
]


def main():
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("PIL is required (pip install pillow)")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img = Image.new("RGBA", (8, 8), (255, 255, 255, 0))
    px = img.load()
    for y, row in enumerate(GRID):
        for x, ch in enumerate(row):
            if ch == "#":
                px[x, y] = (255, 255, 255, 255)
    img.save(OUT)
    print("wrote " + OUT)


if __name__ == "__main__":
    main()
