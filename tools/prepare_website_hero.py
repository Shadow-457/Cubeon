"""Build the full-size WebP homepage image from the public launcher screenshot."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'web/assets/cubeon-play.png'
    target = source.with_suffix('.webp')
    with Image.open(source) as original:
        # Retain the public pixels, without carrying capture metadata across.
        pixels = Image.frombytes('RGB', original.size, original.convert('RGB').tobytes())
    pixels.save(target, 'WEBP', quality=85, method=6)
    print(f'Prepared {target.name}: {target.stat().st_size:,} bytes '
          f'(PNG: {source.stat().st_size:,} bytes).')


if __name__ == '__main__':
    main()
