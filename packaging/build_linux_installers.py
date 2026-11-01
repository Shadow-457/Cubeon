"""Build offline graphical/shell Linux installers and a Debian package."""
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

INSTALLER_RUN = '''#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export CUBEON_APPIMAGE_PATH="${APPIMAGE:-${CUBEON_APPIMAGE_PATH:-}}"
if [ "${CUBEON_LAUNCH_INSTALLED:-}" = 1 ]; then
  exec "$HERE/usr/bin/Cubeon" "$@"
fi
exec "$HERE/usr/bin/Cubeon" --cubeon-installer "$@"
'''


def build_graphical_setup(appdir: Path, tool: Path, output: Path) -> None:
    """Reuse the runtime without nesting a second full AppImage payload."""
    with tempfile.TemporaryDirectory(prefix="cubeon-graphical-setup-") as tmp:
        stage = Path(tmp) / "CubeonSetup.AppDir"
        shutil.copytree(appdir, stage, copy_function=shutil.copy2)
        (stage / "AppRun").write_text(INSTALLER_RUN)
        (stage / "AppRun").chmod(0o755)
        (stage / "cubeon.desktop").write_text(
            '[Desktop Entry]\nName=Cubeon Setup\nExec=AppRun\nIcon=cubeon\n'
            'Type=Application\nCategories=Game;\nComment=Install Cubeon for this user\n')
        import os
        env = dict(os.environ, APPIMAGE_EXTRACT_AND_RUN="1", ARCH="x86_64")
        subprocess.run([str(tool.resolve()), str(stage), str(output.resolve())], env=env, check=True)


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
    graphical = DIST / "Cubeon-Linux-x86_64-Setup.AppImage"
    build_graphical_setup(appdir, DIST / "appimagetool", graphical)
    subprocess.run([sys.executable, str(ROOT / "packaging" / "build_deb.py")], check=True)
    print(f"Built {setup}")
    print(f"Built {graphical}")


if __name__ == "__main__":
    main()
