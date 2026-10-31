"""Build lightweight docs previews from the already-redacted public SEO images."""
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
TARGET = WEB / 'assets/screenshots/previews'


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    images = ET.parse(WEB / 'sitemap.xml').findall(
        './/{http://www.google.com/schemas/sitemap-image/1.1}loc')
    original_bytes = preview_bytes = 0
    for item in images:
        source = WEB / urlsplit(item.text).path.lstrip('/')
        with Image.open(source) as original:
            # Copy pixels only, retaining the existing public redactions.
            preview = Image.frombytes('RGB', original.size, original.convert('RGB').tobytes())
        preview.thumbnail((900, 900), Image.Resampling.LANCZOS)
        target = TARGET / (source.stem + '.webp')
        preview.save(target, 'WEBP', quality=84, method=6)
        original_bytes += source.stat().st_size
        preview_bytes += target.stat().st_size
    print(f'Prepared {len(images)} docs previews: {preview_bytes:,} bytes '
          f'(originals: {original_bytes:,} bytes).')


if __name__ == '__main__':
    main()
