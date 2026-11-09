#!/usr/bin/env python3
"""Generate our original grass-block game icon; contains no Minecraft assets."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / "native/cubeon-rust"


def artwork():
    image = Image.new("RGBA", (32, 32))
    faces = (
        ([(3, 9), (16, 15), (16, 30), (3, 23)], (124, 83, 49)),
        ([(16, 15), (29, 9), (29, 23), (16, 30)], (89, 59, 36)),
        ([(3, 9), (16, 2), (29, 9), (16, 16)], (105, 156, 65)),
    )
    for polygon, color in faces:
        mask = Image.new("L", image.size)
        ImageDraw.Draw(mask).polygon(polygon, fill=255)
        for y in range(32):
            for x in range(32):
                if mask.getpixel((x, y)):
                    shade = ((x // 2 * 17 + y // 2 * 29) % 5 - 2) * 5
                    image.putpixel((x, y), (*[v + shade for v in color], 255))
    draw = ImageDraw.Draw(image)
    draw.polygon([(3, 9), (16, 16), (16, 20), (12, 17), (10, 17),
                  (10, 15), (7, 15), (7, 13), (3, 12)], fill=(80, 126, 47))
    draw.polygon([(16, 16), (29, 9), (29, 12), (26, 14), (26, 16),
                  (23, 16), (23, 18), (20, 19), (16, 20)], fill=(60, 99, 36))
    return image


def main():
    image = artwork()
    image.resize((64, 64), Image.Resampling.NEAREST).save(
        ROOT / "crates/cubeon-theme/icons/game64.png")
    image.resize((256, 256), Image.Resampling.NEAREST).save(
        ROOT / "packaging/icons/game.ico", sizes=[(16, 16), (32, 32), (64, 64), (256, 256)])


if __name__ == "__main__":
    main()
