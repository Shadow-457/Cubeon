"""Build the per-user Windows installer from Linux or Windows.

The onedir package must be built first with build_windows.py. On Linux this
script uses Wine plus NSIS (makensis.exe) and emits one setup executable that
creates Start Menu/Desktop shortcuts without requiring administrator rights.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dist" / "Cubeon"
SCRIPT = ROOT / "packaging" / "Cubeon.nsi"
OUTPUT = ROOT / "dist"
DEFAULT_NSIS = Path.home() / ".cache/electron-builder/nsis/nsis-3.0.4.1/makensis.exe"


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
    command, _ = _compiler()
    command += [
        f"/DSOURCE_DIR={_wine_path(SOURCE)}",
        f"/DOUTPUT_DIR={_wine_path(OUTPUT)}",
        _wine_path(SCRIPT),
    ]
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)
    result = OUTPUT / "Cubeon-Windows-x64-Setup.exe"
    print(f"Done: {result} ({result.stat().st_size // (1024 * 1024)} MB installer)")


if __name__ == "__main__":
    main()
