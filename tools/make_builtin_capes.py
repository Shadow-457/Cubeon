"""Generate original pixel-art capes and existing-format animation sidecars."""
from __future__ import annotations

import argparse
import colorsys
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DESIGNS = (
    ("verdant_crest", "Verdant Crest", False, (77, 208, 139)),
    ("ember_sigil", "Ember Sigil", False, (246, 104, 61)),
    ("lunar_veil", "Lunar Veil", False, (158, 187, 246)),
    ("royal_chevron", "Royal Chevron", False, (238, 196, 102)),
    ("aurora_flow", "Aurora Flow", True, (87, 224, 197)),
    ("prism_cascade", "Prism Cascade", True, (188, 126, 248)),
    ("ender_rift", "Ender Rift", True, (186, 95, 244)),
    ("solar_pulse", "Solar Pulse", True, (255, 183, 79)),
)
FRAME_COUNT = 16
FRAME_MS = 100


def blend(first, second, weight):
    weight = max(0.0, min(1.0, weight))
    return tuple(round(start + (finish - start) * weight)
                 for start, finish in zip(first, second))


def diamond(draw, center, radius, color, fill=None):
    horizontal, vertical = center
    draw.polygon([(horizontal, vertical - radius), (horizontal + radius, vertical),
                  (horizontal, vertical + radius), (horizontal - radius, vertical)],
                 fill=fill, outline=color)


def star(draw, horizontal, vertical, color, radius=1):
    draw.line((horizontal - radius, vertical, horizontal + radius, vertical), fill=color)
    draw.line((horizontal, vertical - radius, horizontal, vertical + radius), fill=color)


def panel(design, accent, phase):
    image = Image.new("RGBA", (20, 32), (11, 16, 27, 255))
    draw = ImageDraw.Draw(image)
    for row in range(32):
        draw.line((0, row, 19, row), fill=blend((10, 14, 25), accent, 0.035 + row / 420))
    if design == "verdant_crest":
        draw.line((4, 25, 15, 8), fill=accent, width=2)
        draw.polygon([(10, 15), (5, 8), (4, 14), (8, 18)], fill=(52, 143, 106))
        draw.polygon([(10, 15), (14, 7), (16, 13), (11, 18)], fill=(130, 241, 169))
        draw.polygon([(7, 21), (3, 16), (3, 22), (6, 24)], fill=(84, 188, 121))
        draw.polygon([(8, 20), (15, 16), (13, 23), (7, 24)], fill=(93, 223, 152))
        diamond(draw, (10, 16), 8, (36, 93, 71))
        star(draw, 14, 5, (193, 255, 209))
    elif design == "ember_sigil":
        draw.polygon([(10, 5), (16, 17), (10, 26), (4, 17)], fill=(105, 37, 35), outline=accent)
        draw.polygon([(10, 10), (13, 18), (10, 23), (7, 18)], fill=(255, 199, 106))
        draw.line((3, 5, 3, 12), fill=(158, 70, 47))
        draw.line((16, 23, 16, 28), fill=(158, 70, 47))
        for horizontal, vertical in ((5, 8), (14, 7), (5, 25), (14, 27)):
            draw.point((horizontal, vertical), fill=(255, 169, 97))
    elif design == "lunar_veil":
        draw.ellipse((4, 9, 15, 22), fill=(211, 226, 255))
        draw.ellipse((8, 6, 18, 19), fill=(17, 25, 44))
        for horizontal, vertical, radius in ((5, 5, 1), (15, 24, 1), (13, 7, 1), (5, 26, 0)):
            star(draw, horizontal, vertical, (135, 168, 230), radius)
        draw.line((4, 28, 15, 28), fill=(64, 88, 139))
    elif design == "royal_chevron":
        draw.rectangle((3, 3, 16, 28), fill=(40, 24, 61))
        draw.polygon([(4, 9), (7, 13), (10, 7), (13, 13), (16, 9), (14, 17), (6, 17)],
                     fill=accent, outline=(255, 231, 160))
        draw.line((4, 21, 10, 26, 16, 21), fill=accent, width=2)
        draw.line((5, 25, 10, 29, 15, 25), fill=(112, 79, 131))
        draw.point((10, 13), fill=(151, 80, 187))
    elif design == "aurora_flow":
        for row in range(3, 29):
            for ribbon, color in ((0, (62, 205, 184)), (1, (91, 118, 229)), (2, (184, 106, 228))):
                horizontal = round(5 + ribbon * 4 + 2 * math.sin(phase + row * 0.23 + ribbon))
                draw.line((horizontal, row, horizontal + 1, row), fill=color)
        for horizontal, vertical in ((5, 6), (14, 24), (8, 18)):
            star(draw, horizontal, vertical, (197, 251, 238), 0)
    elif design == "prism_cascade":
        for row in range(3, 29):
            for column in range(3, 17):
                hue = (phase / math.tau + row * 0.022 + column * 0.035) % 1
                color = tuple(round(channel * 205) for channel in colorsys.hsv_to_rgb(hue, 0.62, 1))
                draw.point((column, row), fill=color)
        diamond(draw, (10, 16), 6, (246, 244, 255))
        draw.line((10, 10, 10, 22), fill=(246, 244, 255))
    elif design == "ender_rift":
        for row in range(3, 29):
            for column in range(3, 17):
                distance = abs(column - 9.5) + abs(row - 15.5) * 0.63
                brightness = (0.5 + 0.5 * math.cos(distance * 0.95 - phase)) ** 3
                draw.point((column, row), fill=blend((28, 16, 47), (166, 69, 224), brightness))
        diamond(draw, (10, 16), 5, (232, 184, 255))
        draw.line((8, 13, 8, 19), fill=(20, 12, 36))
        draw.line((12, 13, 12, 19), fill=(20, 12, 36))
    else:
        for radius in (5, 9, 13):
            glow = 0.5 + 0.5 * math.sin(phase - radius * 0.6)
            color = blend((33, 54, 67), (226, 146, 55), glow)
            draw.ellipse((10 - radius, 16 - radius, 10 + radius, 16 + radius), outline=color)
        draw.ellipse((7, 13, 13, 19), fill=(255, 208, 117))
        for ray in range(8):
            angle = ray * math.tau / 8 + phase / 8
            horizontal = round(10 + math.cos(angle) * 6)
            vertical = round(16 + math.sin(angle) * 6)
            star(draw, horizontal, vertical, accent, 0)
    draw.rectangle((0, 0, 19, 31), outline=blend(accent, (0, 0, 0), 0.56))
    draw.line((2, 1, 17, 1), fill=accent)
    draw.line((2, 30, 17, 30), fill=accent)
    return image


def cape_sheet(outside, accent):
    sheet = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
    sheet.paste(outside, (2, 2))
    inside = Image.new("RGBA", (20, 32), blend((11, 16, 27), accent, 0.08) + (255,))
    draw = ImageDraw.Draw(inside)
    draw.rectangle((0, 0, 19, 31), outline=blend(accent, (0, 0, 0), 0.5))
    draw.line((5, 24, 10, 28, 15, 24), fill=blend(accent, (0, 0, 0), 0.3))
    sheet.paste(inside, (24, 2))
    edge = blend(accent, (0, 0, 0), 0.2) + (255,)
    draw = ImageDraw.Draw(sheet)
    for rectangle in ((2, 0, 21, 1), (22, 0, 41, 1), (0, 2, 1, 33), (22, 2, 23, 33)):
        draw.rectangle(rectangle, fill=edge)
    return sheet


def gif_bytes(frames, durations):
    indexed = []
    for frame in frames:
        image = frame.convert("RGB").quantize(colors=255)
        image.putpalette(image.getpalette()[:765] + [0, 0, 0])
        image.paste(255, mask=frame.getchannel("A").point(lambda alpha: 255 if alpha < 128 else 0))
        indexed.append(image)
    output = io.BytesIO()
    indexed[0].save(output, "GIF", save_all=True, append_images=indexed[1:],
                    duration=durations, loop=0, disposal=2, transparency=255,
                    background=255, optimize=False)
    return output.getvalue()


def preview(designs, destination, animated=False):
    fonts = sorted((ROOT / "assets/fonts").glob("*.ttf"))
    title = ImageFont.truetype(str(fonts[0]), 24) if fonts else ImageFont.load_default()
    label = ImageFont.truetype(str(fonts[0]), 17) if fonts else ImageFont.load_default()
    selected = designs[4:] if animated else designs
    frames = []
    for index in range(FRAME_COUNT if animated else 1):
        image = Image.new("RGBA", (880, 400 if animated else 724), (15, 19, 27, 255))
        draw = ImageDraw.Draw(image)
        draw.text((28, 17), "CUBEON / " + ("ANIMATED CAPES" if animated else "CAPE COLLECTION"),
                  font=title, fill=(233, 237, 246))
        for position, (entry, sheets) in enumerate(selected):
            left = 28 + position % 4 * 212
            top = 66 + position // 4 * 326
            draw.rounded_rectangle((left, top, left + 188, top + 306), radius=12,
                                   fill=(24, 30, 40), outline=(43, 51, 66))
            panel_image = sheets[index % len(sheets)].crop((2, 2, 22, 34))
            image.alpha_composite(panel_image.resize((140, 224), Image.Resampling.NEAREST), (left + 24, top + 14))
            draw.text((left + 12, top + 250), entry["name"], font=label, fill=(234, 239, 247))
            draw.text((left + 12, top + 278), "ANIMATED / 1.6s LOOP" if entry["animated"] else "STATIC",
                      font=label, fill=(140, 160, 184))
        frames.append(image)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if animated:
        destination.write_bytes(gif_bytes(frames, [FRAME_MS] * FRAME_COUNT))
    else:
        frames[0].save(destination, "PNG", optimize=True)


def generate(destination):
    destination.mkdir(parents=True, exist_ok=True)
    designs = []
    for identifier, name, animated, accent in DESIGNS:
        filename = "builtin_" + identifier + ".png"
        entry = {"filename": filename, "name": name, "animated": animated}
        sheets = [cape_sheet(panel(identifier, accent, index * math.tau / FRAME_COUNT), accent)
                  for index in range(FRAME_COUNT if animated else 1)]
        path = destination / filename
        sheets[0].save(path, "PNG", optimize=True)
        if animated:
            atlas = Image.new("RGBA", (128, 64 * FRAME_COUNT))
            for index, sheet in enumerate(sheets):
                atlas.paste(sheet, (0, index * 64))
            atlas.save(str(path) + ".frames.png", "PNG", optimize=True)
            manifest = {"schema": 1, "width": 128, "height": 64, "count": FRAME_COUNT,
                        "durations": [FRAME_MS] * FRAME_COUNT, "loop": 0}
            Path(str(path) + ".frames.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            Path(str(path) + ".gif").write_bytes(gif_bytes(sheets, manifest["durations"]))
        designs.append((entry, sheets))
    (destination / "catalog.json").write_text(
        json.dumps({"schema": 1, "capes": [entry for entry, sheets in designs]}, indent=2) + "\n",
        encoding="utf-8")
    return designs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    output = ROOT / "assets/capes/builtin"
    generated = generate(output)
    if args.preview_dir:
        preview(generated, args.preview_dir / "collection.png")
        preview(generated, args.preview_dir / "animated.gif", animated=True)
    print(f"Generated {len(generated)} original capes; {sum(path.stat().st_size for path in output.iterdir()):,} bytes")
