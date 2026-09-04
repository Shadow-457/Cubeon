#!/usr/bin/env python3
"""
Generates the placeholder Cubeon cape texture.

    python tools/make_cape.py

Writes:
    assets/capes/cubeon_cape.png       the real 64x32 cape texture
    assets/capes/cubeon_cape_preview.png   16x-scaled, just to look at

...and rewrites the CAPE_B64 / CAPE_ID constants inside
worker/cubeon-skins.js so the deployed Worker always serves exactly the PNG
that was just generated. That patching is not a convenience: hand-copying
base64 into source silently corrupted one character the first time it was
done by hand, which serves a broken PNG that only shows up in-game.

So: edit the grid, run this, redeploy. Nothing to transcribe.

WHY THIS IS A SCRIPT AND NOT A PNG
The visible part of a Minecraft cape is only 10x16 pixels. At that size you
are placing individual pixels, not drawing - so the design lives below as an
ASCII grid where one character is one pixel. Edit the grid, re-run, done.
No image editor, and the diff stays readable.

CAPE TEXTURE LAYOUT (64x32)
Only a small corner of the file is the cape; the rest is padding (and the
elytra region, see ELYTRA below). Regions, in pixels:

    (1,0)  10x1    top edge
    (11,0) 10x1    bottom edge
    (0,1)  1x16    left edge
    (1,1)  10x16   OUTSIDE  <- the face other players see
    (11,1) 1x16    right edge
    (12,1) 10x16   inside   <- seen when the cape swings

Everything else stays transparent.
"""
import base64
import hashlib
import os
import re

from PIL import Image

# --- Palette (matches assets/icon.svg and main.py's design tokens) ---------
BG      = (0x12, 0x14, 0x0F, 255)   # near-black, faint olive undertone
ACCENT  = (0x7F, 0xB2, 0x44, 255)   # signature grass green - used for the border
TOP     = (0xA6, 0xD0, 0x65, 255)   # cube top face  (lit)
LEFT    = (0x62, 0x8A, 0x38, 255)   # cube left face (mid)
RIGHT   = (0x3E, 0x5A, 0x22, 255)   # cube right face (shaded)
NONE    = (0, 0, 0, 0)              # transparent

CHARS = {
    "o": ACCENT,
    "#": BG,
    "T": TOP,
    "L": LEFT,
    "R": RIGHT,
    ".": NONE,
}

# --- The design: 10 wide x 16 tall, one char per pixel --------------------
# The isometric cube from the launcher icon, reduced to the fewest pixels
# that still read as a cube at real size: a lit top diamond, a mid-tone
# left face, a shaded right face. Framed by a 1px accent border so the
# cape has a defined silhouette against any terrain.
OUTSIDE = [
    "oooooooooo",
    "o########o",
    "o########o",
    "o###TT###o",
    "o##TTTT##o",
    "o#TTTTTT#o",
    "o#LTTTTR#o",
    "o#LLTTRR#o",
    "o#LLLRRR#o",
    "o#LLLRRR#o",
    "o#LLLRRR#o",
    "o##LLRR##o",
    "o###LR###o",
    "o########o",
    "o########o",
    "oooooooooo",
]

# The inner face. Plain dark with an accent border - a busy inside just
# reads as noise when the cape lifts.
INSIDE = (
    ["oooooooooo"]
    + ["o########o"] * 14
    + ["oooooooooo"]
)

# Rendered as the cape's 1px-deep sides. Solid accent keeps the edge crisp.
EDGE_COLOR = ACCENT

# If the cube's shading looks mirrored in-game (light on the wrong side),
# flip this and re-run rather than rewriting the grid. Minecraft's cape
# rendering has flipped between versions, so verify in-game once.
FLIP_OUTSIDE = False

# Elytra wings share this texture file in vanilla. Cubeon does not ship an
# elytra design yet, so that region is left transparent - an elytra worn
# with this cape renders invisible. Harmless for now (elytra needs End-game
# progression); revisit if it ever looks broken to players.
CAPE_W, CAPE_H = 64, 32


def _grid_to_image(rows: list[str]) -> Image.Image:
    """Turns an ASCII grid into an RGBA image, one char per pixel."""
    h = len(rows)
    w = len(rows[0])
    for i, row in enumerate(rows):
        if len(row) != w:
            raise ValueError(f"row {i} is {len(row)} chars, expected {w}: {row!r}")
    img = Image.new("RGBA", (w, h), NONE)
    px = img.load()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch not in CHARS:
                raise ValueError(f"unknown char {ch!r} at row {y} col {x}")
            px[x, y] = CHARS[ch]
    return img


def build_cape() -> Image.Image:
    outside = _grid_to_image(OUTSIDE)
    inside = _grid_to_image(INSIDE)

    if outside.size != (10, 16):
        raise ValueError(f"OUTSIDE must be 10x16, got {outside.size}")
    if inside.size != (10, 16):
        raise ValueError(f"INSIDE must be 10x16, got {inside.size}")

    if FLIP_OUTSIDE:
        outside = outside.transpose(Image.FLIP_LEFT_RIGHT)

    cape = Image.new("RGBA", (CAPE_W, CAPE_H), NONE)
    cape.paste(outside, (1, 1))
    cape.paste(inside, (12, 1))

    edge = Image.new("RGBA", (1, 1), EDGE_COLOR)
    for x in range(1, 11):          # top edge strip
        cape.paste(edge, (x, 0))
    for x in range(11, 21):         # bottom edge strip
        cape.paste(edge, (x, 0))
    for y in range(1, 17):          # left and right edge strips
        cape.paste(edge, (0, y))
        cape.paste(edge, (11, y))

    return cape


def _wrap_b64_as_js(b64: str, width: int = 80) -> str:
    """Formats base64 as a JS string-concat expression, one chunk per line."""
    chunks = [b64[i:i + width] for i in range(0, len(b64), width)]
    return "\n".join(
        f'  "{c}"' + (" +" if i < len(chunks) - 1 else ";")
        for i, c in enumerate(chunks)
    )


def patch_worker(png_bytes: bytes, worker_path: str) -> bool:
    """Rewrites CAPE_B64 and CAPE_ID in the Worker to match png_bytes.

    Returns False (without touching the file) if the Worker isn't there -
    the cape PNG is still perfectly usable on its own.
    """
    if not os.path.isfile(worker_path):
        return False

    b64 = base64.b64encode(png_bytes).decode("ascii")
    sha = hashlib.sha256(png_bytes).hexdigest()

    with open(worker_path, "r", encoding="utf-8") as f:
        src = f.read()

    new_src, n_b64 = re.subn(
        r"const CAPE_B64 =\n(?:.*\n)*?.*?;",
        "const CAPE_B64 =\n" + _wrap_b64_as_js(b64),
        src,
        count=1,
    )
    new_src, n_id = re.subn(
        r'const CAPE_ID = "[a-f0-9]*";',
        f'const CAPE_ID = "{sha}";',
        new_src,
        count=1,
    )
    if not (n_b64 and n_id):
        raise SystemExit(
            f"could not find CAPE_B64/CAPE_ID in {worker_path} - "
            "did the constant names change?"
        )

    with open(worker_path, "w", encoding="utf-8") as f:
        f.write(new_src)
    return True


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    project = os.path.dirname(here)
    out_dir = os.path.join(project, "assets", "capes")
    os.makedirs(out_dir, exist_ok=True)

    cape = build_cape()
    out = os.path.join(out_dir, "cubeon_cape.png")
    cape.save(out)

    preview = cape.crop((0, 0, 22, 17)).resize((22 * 16, 17 * 16), Image.NEAREST)
    preview_out = os.path.join(out_dir, "cubeon_cape_preview.png")
    preview.save(preview_out)

    with open(out, "rb") as f:
        png_bytes = f.read()

    print(f"wrote {out} ({cape.width}x{cape.height}, {len(png_bytes)} bytes)")
    print(f"wrote {preview_out} (scaled preview of the used region)")

    worker_path = os.path.join(project, "worker", "cubeon-skins.js")
    if patch_worker(png_bytes, worker_path):
        print(f"patched {worker_path}")
        print(f"  CAPE_ID = {hashlib.sha256(png_bytes).hexdigest()}")
        print("  -> redeploy the Worker for the new cape to reach players")
    else:
        print(f"skipped {worker_path} (not found)")


if __name__ == "__main__":
    main()
