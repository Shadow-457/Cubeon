"""Build the Linux setup bundle and Debian package from dist/AppDir."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def main() -> None:
    appimage = DIST / "Cubeon-x86_64.AppImage"
    appdir = DIST / "AppDir"
    if not appimage.is_file() or not appdir.is_dir():
        raise SystemExit("Run packaging/build_appimage.sh first.")
    setup = DIST / "Cubeon-Linux-x86_64-Setup.sh"
    shutil.copy2(ROOT / "packaging" / "install_linux.sh", setup)
    setup.chmod(0o755)
    shutil.copy2(ROOT / "assets" / "icon_256.png", DIST / "cubeon.png")
    subprocess.run(["python", str(ROOT / "packaging" / "build_deb.py")], check=True)
    print(f"Built {setup}")


if __name__ == "__main__":
    main()
