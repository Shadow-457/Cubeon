"""Build a branded 1200×630 social card using only public launcher assets."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SIZE = (1200, 630)


def main():
    source = ROOT / 'web/assets/cubeon-play.webp'
    target = source.with_name('og.png')
    font_path = str(ROOT / 'assets/fonts/Inter.ttf')
    heading = ImageFont.truetype(font_path, 48)
    label = ImageFont.truetype(font_path, 26)
    body = ImageFont.truetype(font_path, 21)
    badge = ImageFont.truetype(font_path, 17)
    card = Image.new('RGB', SIZE, '#0b110c')
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((20, 20, 1179, 609), radius=24, outline='#2c3d2b', width=2)
    with Image.open(source.with_name('favicon.png')) as original:
        logo = original.convert('RGBA').resize((62, 62), Image.Resampling.LANCZOS)
    card.paste(logo, (48, 44), logo)
    draw.text((128, 55), 'CUBEON LAUNCHER', font=label, fill='#ecf5e8')
    draw.text((939, 62), 'WINDOWS + LINUX', font=badge, fill='#afd889')
    draw.line((48, 128, 1152, 128), fill='#2c3d2b', width=2)
    draw.text((48, 175), 'Your Minecraft.', font=heading, fill='#f5f8f0')
    draw.text((48, 235), 'Your launcher.', font=heading, fill='#afd889')
    draw.multiline_text((50, 338), 'Mods. Modpacks. Skins.\nMultiple instances, one window.',
                        font=body, fill='#c9d8c2', spacing=12)
    draw.rounded_rectangle((48, 459, 298, 497), radius=19, fill='#20351c')
    draw.text((65, 469), 'FREE + OPEN SOURCE', font=badge, fill='#c6efa6')
    with Image.open(source) as original:
        shot = ImageOps.contain(original.convert('RGB'), (668, 420), Image.Resampling.LANCZOS)
    position = (488, 151)
    draw.rounded_rectangle((position[0] - 3, position[1] - 3,
                            position[0] + shot.width + 3, position[1] + shot.height + 3),
                           radius=10, fill='#516749')
    card.paste(shot, position)
    draw.text((50, 565), 'www.ylet.online', font=body, fill='#c9d8c2')
    draw.text((888, 565), 'Minecraft Java Edition', font=body, fill='#c9d8c2')
    card.save(target, 'PNG', optimize=True)
    print(f'Prepared {target.name}: {target.stat().st_size:,} bytes ({SIZE[0]}×{SIZE[1]}).')


if __name__ == '__main__':
    main()
