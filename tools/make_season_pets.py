#!/usr/bin/env python3
"""
Generates the seasonal companion sprites (assets/pets/*.gif).

WHY GENERATED, NOT DOWNLOADED
-----------------------------
Cubeon already draws its own small pixel art in-house (assets/grass_block.gif
and the Friends corner glyph in tools/make_corner_icon.py), and the launcher has
to work offline with no license questions - so the pets are built here from
ASCII grids, exactly like the corner icon. Pillow is already a dependency
(cubeon/tray.py, cubeon/skins.py).

Each pet is a 16x16 grid of characters mapped to colours, rendered at 4x
(nearest-neighbour, so it stays pixel-crisp) and assembled into a 4-frame hop
cycle: rest -> airborne (1px up) -> rest -> squash (1px down). The animation
lives entirely in the GIF, so it costs the Python side nothing: Flutter decodes
and loops it without a single page.update(), which matters in a launcher whose
animation budget is one shared ticker (see ui/seasonal_ui.py).

Summer has no sprite here on purpose: it reuses assets/parrot.gif, the mascot
the account panel already perches on the avatar.

Run from the repo root (writes assets/pets/, plus an optional contact sheet so a
human - or an agent with an image reader - can actually LOOK at the result):

    python3 tools/make_season_pets.py
    python3 tools/make_season_pets.py --sheet /tmp/pets.png
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "pets")

SCALE = 4
# Rest -> airborne -> rest -> squash. The airborne leg is quicker than the rest,
# which is what makes a bob read as a hop instead of a slow float.
FRAME_OFFSETS = (0, -1, 0, 1)
FRAME_MS = (320, 130, 160, 130)

# Every pet names its own colours for the same characters:
#   '#' body/fur   '.' transparent      'o' dark (eyes, stripes, legs)
#   'w' white/pale (belly, muzzle, snow, pumpkin face)
#   '+' inner accent                   'e' wing / pale blue
FOX = [
    "................",
    "....#......#....",
    "...#+#....#+#...",
    "...#+######+#...",
    "...##########...",
    "...#o######o#...",
    "...###wwww###...",
    "...##wwowww##...",
    "....##wwww##....",
    "....########....",
    "....##wwww##.##.",
    "....##wwww#####.",
    "....##wwww##www.",
    "...oo#wwww##www.",
    "...oo.....oowww.",
    "................",
]
GOLEM = [
    "................",
    "......####......",
    ".....######.....",
    ".....######.....",
    ".....o####o.....",
    ".....######.....",
    "......o##o......",
    "......####......",
    "....wwwwwwww....",
    "...wwwwwwwwww...",
    "...wwwwwwwwww...",
    "...wwwwwwwwww...",
    "....wwwwwwww....",
    "....ww....ww....",
    "....ww....ww....",
    "................",
]
BEE = [
    "................",
    "...ee......ee...",
    "..eeee....eeee..",
    "..ee########ee..",
    "....#oo##oo#....",
    "....########....",
    ".....oooooo.....",
    ".....######.....",
    ".....oooooo.....",
    ".....######.....",
    "......####......",
    ".......oo.......",
    "................",
    "................",
    "................",
    "................",
]


PETS = {
    # season -> (grid, palette, filename)
    "autumn": (FOX, {"#": "#E0762A", "o": "#2A1608", "w": "#F7E6D2",
                     "+": "#5A3418", "f": "#F7E6D2", "e": "#F79A3C"},
               "autumn_fox.gif"),
    "winter": (GOLEM, {"#": "#E0894A", "o": "#3A1F0A", "w": "#EAF2F8",
                       "+": "#8A4A1E", "f": "#EAF2F8", "e": "#CFE6F5"},
               "winter_golem.gif"),
    "spring": (BEE, {"#": "#E4B23C", "o": "#241A06", "w": "#FFFDF2",
                     "+": "#FFFFFF", "f": "#FFFDF2", "e": "#CFE9F5"},
               "spring_bee.gif"),
}


def _render(grid, palette, offset, scale):
    """One frame: the grid drawn `offset` pixels up/down, then upscaled."""
    from PIL import Image

    rows = len(grid)
    cell = 4
    canvas = Image.new("RGBA", (16 * cell, 16 * cell), (0, 0, 0, 0))
    px = canvas.load()
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            color = palette.get(ch)
            if not color:
                continue
            rgba = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
            ty = y + offset
            if not 0 <= ty < rows:
                continue
            for dy in range(cell):
                for dx in range(cell):
                    px[(x * cell + dx, ty * cell + dy)] = rgba
    return canvas.resize((16 * scale, 16 * scale), Image.NEAREST)


def main(argv):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("PIL is required (pip install pillow)")

    for grid, _palette, _name in PETS.values():
        widths = {len(r) for r in grid}
        if widths != {16} or len(grid) != 16:
            raise SystemExit(f"grid must be exactly 16x16, got {len(grid)} rows "
                             f"of widths {sorted(widths)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    sheet_rows = []
    for season, (grid, palette, filename) in PETS.items():
        frames = [_render(grid, palette, off, SCALE) for off in FRAME_OFFSETS]
        path = os.path.join(OUT_DIR, filename)
        frames[0].save(
            path, save_all=True, append_images=frames[1:],
            duration=list(FRAME_MS), loop=0, disposal=2, transparency=0,
        )
        print(f"wrote {path}  ({os.path.getsize(path)} bytes, "
              f"{16 * SCALE}x{16 * SCALE})")
        sheet_rows.append((season, frames))

    if "--sheet" in argv:
        sheet_path = argv[argv.index("--sheet") + 1]
        w, h = sheet_rows[0][1][0].size
        sheet = Image.new("RGBA", (w * 4, h * len(sheet_rows)), (12, 12, 14, 255))
        for row, (_season, frames) in enumerate(sheet_rows):
            for col, fr in enumerate(frames):
                sheet.paste(fr, (col * w, row * h), fr)
        sheet.save(sheet_path)
        print(f"wrote {sheet_path} (review sheet: one row per pet, one column "
              f"per hop frame)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))