"""
Build the Windows installer payload. Run from the repo root:
    python packaging/build_windows.py
Output: dist/Cubeon/ for build_windows_installer.py; distribute the setup executable.

NOTE: --add-data assets is REQUIRED - assets/jars holds the Friends mod jars,
and the launcher resolves them from there when
packaged. Forgetting it produces a launcher with no friends mod. Only
mod/brackets.json is bundled: Java sources and Gradle build files are release
tooling, not runtime data. Connect is downloaded during server setup, not bundled.

FLET DESKTOP CLIENT (the window itself):
--collect-submodules flet_desktop and --collect-binaries flet_desktop keep
the desktop integration in the frozen launcher. Without it the frozen exe
can't `import flet_desktop`, and flet's startup then tries to PIP-INSTALL it at
runtime - which fails inside PyInstaller (no pip, frozen) and exits before a
window ever appears. Symptom: the exe closes instantly.

The PyPI wheel lacks the client. Download and extract flet-windows.zip
during the build, then place the native files in flet_desktop/app/flet/.
The packaged launcher uses them directly. First launch needs neither a
download nor a directory rename in the user's Flet cache.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from runtime_assets import make_runtime_assets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP = ";" if os.name == "nt" else ":"  # PyInstaller path separator

# cubeon/color_templates.py loads every palette by a DYNAMIC
# importlib.import_module("templates.color_<key>"). PyInstaller cannot see a
# dynamic import, so the palette modules must be named explicitly - and NOT via
# `--collect-submodules templates`, which runs while the spec is being written,
# BEFORE Analysis adds the repo to sys.path. On the Windows build interpreter
# (WinPython runs in isolated _pth mode, so the repo is never on sys.path)
# collect_submodules("templates") returns zero modules, the palette import
# fails, and the launcher silently falls back to the built-in tokens: the
# still show (they do not touch templates) while the colours do not - exactly
# the Windows bug. Explicit --hidden-import names are resolved by Analysis via
# --paths ROOT. Adding a palette = add it in cubeon/color_templates.py AND here.
TEMPLATE_HIDDEN_IMPORTS = (
    "templates",
    "templates.color_green",
)

FLET_VERSION = "0.86.5"  # keep in sync with requirements.txt (flet>=0.86,<0.87)
FLET_CLIENT_URL = f"https://github.com/flet-dev/flet/releases/download/v{FLET_VERSION}/flet-windows.zip"


def _check_flet_client(client):
    for relative in ("flet.exe", "flutter_windows.dll", "data/icudtl.dat"):
        file = client / relative
        if not file.is_file() or file.stat().st_size == 0:
            raise FileNotFoundError(f"Windows desktop client file is missing or empty: {file}")


def _stage_flet_client(work):
    from flet.utils import safe_zip_extractall
    from flet_desktop import get_package_bin_dir

    archive = Path(get_package_bin_dir()) / "flet-windows.zip"
    if not archive.is_file():
        archive = work / archive.name
        print(f"+ downloading {FLET_CLIENT_URL}")
        urllib.request.urlretrieve(FLET_CLIENT_URL, archive)
    with zipfile.ZipFile(archive) as client_zip:
        safe_zip_extractall(client_zip, str(work))
    client = work / "flet"
    _check_flet_client(client)
    return client


def main():
    os.chdir(ROOT)
    with tempfile.TemporaryDirectory(prefix="cubeon-flet-windows-") as work:
        client = _stage_flet_client(Path(work))
        assets = make_runtime_assets(ROOT)
        try:
            _build_payload(assets, client)
        finally:
            shutil.rmtree(assets, ignore_errors=True)


def _build_payload(assets, client):
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--windowed",
        "--name", "Cubeon",
        # Shell/taskbar/Explorer icon for Cubeon.exe (and everything that
        # shortcuts to it). Omitting it shipped the generic PyInstaller
        # bootloader art as "the app icon" on Windows.
        "--icon=assets/icon.ico",
        f"--add-data={assets}{SEP}assets",
        f"--add-data=mod/brackets.json{SEP}mod",
        f"--add-data={client}{SEP}flet_desktop/app/flet",
        # NO --add-data for templates/: palettes ship as bytecode via
        # explicit hidden imports - raw .py data would put
        # readable source in the shipped exe.
        "--collect-submodules", "cubeon.lang",
        "--collect-data", "flet",

        "--collect-submodules", "flet",

        "--collect-binaries", "flet",
        "--collect-data", "minecraft_launcher_lib",

        "--collect-submodules", "minecraft_launcher_lib",

        "--collect-binaries", "minecraft_launcher_lib",
        "--collect-submodules", "flet_desktop",

        "--collect-binaries", "flet_desktop",
        "--paths", ROOT,
        *[f"--hidden-import={m}" for m in TEMPLATE_HIDDEN_IMPORTS],
        "main.py",
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)
    _check_flet_client(Path("dist/Cubeon/_internal/flet_desktop/app/flet"))

    # A windowed PyInstaller build runs without a console; main.py expects to
    # find its assets next to the executable (resolve_assets_dir handles both
    # dev and frozen layouts).

    print("Done: dist/Cubeon/ installer payload")


if __name__ == "__main__":
    main()
