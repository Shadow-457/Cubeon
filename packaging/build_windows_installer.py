"""Build the per-user Windows installer from Linux or Windows.

The onedir package must be built first with build_windows.py. On Linux this
script uses Wine plus NSIS (makensis.exe) and emits one setup executable that
creates Start Menu/Desktop shortcuts without requiring administrator rights.

What it passes to Cubeon.nsi beyond SOURCE_DIR/OUTPUT_DIR:
  ICON_FILE        assets/icon.ico - the setup/uninstaller window icon (was
                   missing entirely, so the installer shipped NSIS's default).
  APP_VERSION      four-part numeric version for the exe's Properties dialog,
                   read from cubeon/updater.py's APP_VERSION.
  DISPLAY_VERSION  the human "1.0.0" shown in Programs and Features.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dist" / "Cubeon"
SCRIPT = ROOT / "packaging" / "Cubeon.nsi"
OUTPUT = ROOT / "dist"
ICON = ROOT / "assets" / "icon.ico"
DEFAULT_NSIS = Path.home() / ".cache/electron-builder/nsis/nsis-3.0.4.1/makensis.exe"


def _app_version() -> tuple[str, str]:
    """(four-part numeric version, display version) from cubeon/updater.py.
    Falls back to 1.0.0.0 / 1.0.0 if the file can't be read - a version
    resource is polish, never a build blocker."""
    try:
        src = (ROOT / "cubeon" / "updater.py").read_text(encoding="utf-8")
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
        display = m.group(1) if m else "1.0.0"
    except OSError:
        display = "1.0.0"
    parts = re.findall(r"\d+", display)
    parts = (parts + ["0", "0", "0"])[:4]
    return ".".join(parts), display



def _wine_path(path: Path) -> str:
    winepath = shutil.which("winepath")
    if winepath:
        result = subprocess.run(
            [winepath, "-w", str(path)], check=True, capture_output=True, text=True
        )
        return result.stdout.strip()
    return str(path)


def _compiler() -> tuple[list[str], Path]:
    native = shutil.which("makensis")
    if native:
        return [native], Path(native)
    nsis = DEFAULT_NSIS if DEFAULT_NSIS.is_file() else None
    if nsis is None:
        raise SystemExit(
            "NSIS not found. Install makensis, or install NSIS under Wine."
        )
    wine = shutil.which("wine")
    if not wine:
        raise SystemExit("Wine is required to run the Windows NSIS compiler on Linux.")
    return [wine, _wine_path(nsis)], nsis


def main() -> None:
    if not SOURCE.is_dir() or not (SOURCE / "Cubeon.exe").is_file():
        raise SystemExit(
            "Missing dist/Cubeon/Cubeon.exe. Run packaging/build_windows.py first."
        )
    if not ICON.is_file():
        raise SystemExit(f"Missing {ICON}. The installer needs the Cubeon icon.")
    command, _ = _compiler()
    numeric_version, display_version = _app_version()
    command += [
        f"/DSOURCE_DIR={_wine_path(SOURCE)}",
        f"/DOUTPUT_DIR={_wine_path(OUTPUT)}",
        f"/DICON_FILE={_wine_path(ICON)}",
        f"/DAPP_VERSION={numeric_version}",
        f"/DDISPLAY_VERSION={display_version}",
    ]
    wizard_bmp = ROOT / "packaging" / "graphics" / "wizard.bmp"
    header_bmp = ROOT / "packaging" / "graphics" / "header.bmp"
    if wizard_bmp.is_file():
        command.append(f"/DWIZARD_IMAGE={_wine_path(wizard_bmp)}")
    if header_bmp.is_file():
        command.append(f"/DHEADER_IMAGE={_wine_path(header_bmp)}")
    command.append(_wine_path(SCRIPT))
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)
    result = OUTPUT / "Cubeon-Windows-x64-Setup.exe"
    print(f"Done: {result} ({result.stat().st_size // (1024 * 1024)} MB installer)")


if __name__ == "__main__":
    main()
