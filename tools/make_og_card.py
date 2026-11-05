"""Build the 1200×630 Open Graph image from the public Play screenshot.

Preserve the complete launcher window on the website's dark background.
All content pages use web/assets/og.png; PNG supports social preview crawlers.
Requires Pillow, without a browser or new screenshots.
"""
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SIZE = (1200, 630)


def main():
    source = ROOT / 'web/assets/cubeon-play.png'
    target = source.with_name('og.png')
    with Image.open(source) as original:
        pixels = Image.frombytes('RGB', original.size, original.convert('RGB').tobytes())
    shot = ImageOps.contain(pixels, SIZE, Image.Resampling.LANCZOS)
    card = Image.new('RGB', SIZE, '#090d07')
    card.paste(shot, ((SIZE[0] - shot.width) // 2, (SIZE[1] - shot.height) // 2))
    card.save(target, 'PNG', optimize=True)
    print(f'Prepared {target.name}: {target.stat().st_size:,} bytes ({SIZE[0]}×{SIZE[1]}).')


if __name__ == '__main__':
    main()
