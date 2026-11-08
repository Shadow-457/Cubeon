"""Sync Bench's public entry and build its social card from the bundled preview."""
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / 'web/cubeon-bench'


def main():
    (BENCH / 'index.html').write_bytes((BENCH / 'landing.html').read_bytes())
    card = Image.new('RGB', (1200, 630), '#111910')
    draw = ImageDraw.Draw(card)
    font_path = str(BENCH / 'fonts/Inter.ttf')
    title = ImageFont.truetype(font_path, 55)
    subtitle = ImageFont.truetype(font_path, 26)
    small = ImageFont.truetype(font_path, 21)
    with Image.open(BENCH / 'icons/bench-logo.png') as source:
        logo = source.convert('RGBA').resize((64, 64), Image.Resampling.LANCZOS)
    card.paste(logo, (44, 42), logo)
    draw.text((126, 54), 'CUBEON BENCH', font=subtitle, fill='#dcebcf')
    draw.text((44, 172), 'Create for', font=title, fill='#f5f8f0')
    draw.text((44, 238), 'Minecraft.', font=title, fill='#b2d889')
    draw.multiline_text((46, 332), 'Textures. Skins.\nAnimation. 3D previews.',
                        font=subtitle, fill='#d0ddc5', spacing=13)
    draw.text((46, 460), 'Free. Local-first. No account.', font=small, fill='#b2d889')
    with Image.open(BENCH / 'landing-assets/editor-preview-dark.webp') as original:
        screenshot = ImageOps.contain(original.convert('RGB'), (720, 450), Image.Resampling.LANCZOS)
    position = (444, 122)
    draw.rounded_rectangle((position[0] - 2, position[1] - 2,
                            position[0] + screenshot.width + 2, position[1] + screenshot.height + 2),
                           radius=7, fill='#546648')
    card.paste(screenshot, position)
    draw.text((46, 572), 'www.ylet.online/cubeon-bench', font=small, fill='#d0ddc5')
    card.save(BENCH / 'og.png', 'PNG', optimize=True)
    namespace = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    sitemap = ROOT / 'web/sitemap.xml'
    tree = ET.parse(sitemap)
    if 'https://www.ylet.online/cubeon-bench' not in [entry.text for entry in tree.findall('.//' + namespace + 'loc')]:
        for prefix, uri in (('', namespace[1:-1]), ('xhtml', 'http://www.w3.org/1999/xhtml'),
                            ('image', 'http://www.google.com/schemas/sitemap-image/1.1')):
            ET.register_namespace(prefix, uri)
        entry = ET.SubElement(tree.getroot(), namespace + 'url')
        ET.SubElement(entry, namespace + 'loc').text = 'https://www.ylet.online/cubeon-bench'
        tree.write(sitemap, encoding='utf-8', xml_declaration=True)
    print('Prepared Bench entry and 1200 × 630 Open Graph card.')


if __name__ == '__main__':
    main()
