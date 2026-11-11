"""Build the full-size WebP homepage image from the public launcher screenshot."""
from pathlib import Path
import argparse
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'archive/ui-captures/website-originals/cubeon-play.png',
                        help='Original PNG screenshot; defaults to the ignored local capture archive.')
    source = parser.parse_args().source
    target = ROOT / 'web/assets/cubeon-play.webp'
    with Image.open(source) as original:
        # Retain the public pixels, without carrying capture metadata across.
        pixels = Image.frombytes('RGB', original.size, original.convert('RGB').tobytes())
    pixels.save(target, 'WEBP', quality=85, method=6)
    print(f'Prepared {target.name}: {target.stat().st_size:,} bytes '
          f'(PNG: {source.stat().st_size:,} bytes).')


if __name__ == '__main__':
    main()
