"""Build the Linux setup bundle and Debian package from dist/AppDir."""
from __future__ import annotations

import shutil
import subprocess
import hashlib
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def build_setup(appimage: Path, icon: Path, setup: Path) -> None:
    """One offline installer: users never need to obtain adjacent files."""
    with tempfile.TemporaryDirectory(prefix="cubeon-setup-build-") as tmp:
        payload = Path(tmp) / "payload.tar.gz"
        with tarfile.open(payload, "w:gz", compresslevel=1) as archive:
            archive.add(appimage, arcname="Cubeon.AppImage")
            archive.add(icon, arcname="cubeon.png")
        digest = hashlib.sha256()
        with payload.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        header = (ROOT / "packaging" / "install_linux.sh").read_text()
        header = header.replace('PAYLOAD_SHA256="@PAYLOAD_SHA256@"',
                                f'PAYLOAD_SHA256="{digest.hexdigest()}"')
        with setup.open("wb") as output, payload.open("rb") as source:
            output.write(header.encode("utf-8"))
            shutil.copyfileobj(source, output)
        setup.chmod(0o755)


def main() -> None:
    appimage = DIST / "Cubeon-x86_64.AppImage"
    appdir = DIST / "AppDir"
    if not appimage.is_file() or not appdir.is_dir():
        raise SystemExit("Run packaging/build_appimage.sh first.")
    setup = DIST / "Cubeon-Linux-x86_64-Setup.sh"
    build_setup(appimage, ROOT / "assets" / "icon_256.png", setup)
    subprocess.run([sys.executable, str(ROOT / "packaging" / "build_deb.py")], check=True)
    print(f"Built {setup}")


if __name__ == "__main__":
    main()
