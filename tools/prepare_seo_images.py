"""Prepare public screenshot copies; originals stay in the ignored capture archive.

Requires Pillow. Does not alter visible website pages or publish anything.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "archive/ui-captures/seo-images"
TARGET = ROOT / "web/assets/screenshots"
SHOTS = [
    ("134440", "mods", "Cubeon Launcher mods browser", "Browse compatible Minecraft mods from Modrinth in Cubeon Launcher."),
    ("134454", "resource-packs", "Cubeon Launcher resource packs", "Find and install Minecraft resource packs in Cubeon Launcher."),
    ("134510", "shaders", "Cubeon Launcher shaders", "Browse Minecraft shaders and install Iris from Cubeon Launcher."),
    ("134646", "modpacks", "Cubeon Launcher modpacks", "Browse and install Minecraft modpacks in Cubeon Launcher."),
    ("134707", "friends-chat", "Cubeon Launcher friends and chat", "Cubeon's friends and chat screen. Account and conversation details are masked in this screenshot."),
    ("134754", "cosmetics-wings", "Cubeon Launcher cosmetics", "Preview a Minecraft skin with a shoulder companion and select Cubeon back cosmetics."),
    ("134810", "playtime-stats", "Cubeon Launcher playtime statistics", "The Cubeon Launcher Stats tab with daily Minecraft playtime."),
    ("134824", "server-console", "Cubeon Launcher server console", "Manage a Minecraft server, plugins and settings from Cubeon Launcher."),
    ("135044", "account-settings", "Cubeon Launcher account settings", "The Cubeon settings panel. Personal account details are masked in this screenshot."),
]


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(ROOT / "web/assets/fonts/Inter.ttf"), 14)
    for stamp, name, title, description in SHOTS:
        with Image.open(SOURCE / f"Screenshot_20261030_{stamp}.png") as original:
            # Copy pixels only: capture metadata and EXIF do not reach the public copy.
            image = Image.frombytes("RGB", original.size, original.convert("RGB").tobytes())
        draw = ImageDraw.Draw(image)
        draw.rectangle((int(image.width * .78), 3, int(image.width * .9), 38), fill=image.getpixel((950, 20)))

        def mask(box, label, fill):
            draw.rectangle(box, fill=fill)
            draw.text((box[0] + 8, box[1] + 8), label, font=font, fill="#9db394")

        if name == "friends-chat":
            mask((137, 135, 368, 177), "Account details hidden", "#150f08")
            mask((128, 314, 419, 517), "Friend details hidden", "#170f06")
        if name == "account-settings":
            mask((413, 192, 669, 250), "Account details hidden", "#131711")
            mask((421, 269, 650, 295), "Username hidden", "#131711")
            draw.rectangle((1119, 359, 1178, 388), fill="#070905")
        info = PngImagePlugin.PngInfo()
        info.add_text("Title", title)
        info.add_text("Description", description)
        image.save(TARGET / f"cubeon-launcher-{name}.png", pnginfo=info, optimize=True)
    with Image.open(SOURCE / "cubeon-pet-textures.png") as original:
        image = Image.frombytes("RGB", original.size, original.convert("RGB").tobytes())
    info = PngImagePlugin.PngInfo()
    info.add_text("Title", "Cubeon shoulder companion artwork")
    info.add_text("Description", "Ten Cubeon shoulder companion texture designs for Minecraft player cosmetics.")
    image.save(TARGET / "cubeon-shoulder-companion-textures.png", pnginfo=info, optimize=True)
    print("Prepared 10 public images; the existing Play and in-game cosmetics assets are reused by the sitemap.")


if __name__ == "__main__":
    main()
