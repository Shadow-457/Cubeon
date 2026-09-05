"""
Build the Windows EXE + portable ZIP. Run from the repo root:
    python packaging/build_windows.py
Output: dist/Cubeon/ (standalone folder) and dist/Cubeon-Windows-x64.zip.

NOTE: --add-data assets is REQUIRED - assets/jars holds the Friends mod jars
and the Connect plugin, and the launcher resolves them from there when
packaged. Forgetting it produces a launcher with no friends mod.

FLET DESKTOP CLIENT (the window itself):
--collect-all flet_desktop is REQUIRED. Without it the frozen exe can't
`import flet_desktop`, and flet's startup then tries to PIP-INSTALL it at
runtime - which fails inside PyInstaller (no pip, frozen) and exits before a
window ever appears. Symptom: the exe closes instantly.

The flet-desktop wheel normally carries the client binary in
flet_desktop/app/, but the PyPI wheel ships it EMPTY and flet downloads
flet-windows.zip from GitHub Releases on first run. That download fails
offline and confuses first impressions, so the client zip is downloaded at
BUILD time here and bundled via --collect-data. At runtime
ensure_client_cached() finds it at get_package_bin_dir()/flet-windows.zip
(frozen: _MEIPASS/flet_desktop/app/) and extracts it locally - no network
needed, ever.
"""
import os
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP = ";" if os.name == "nt" else ":"  # PyInstaller path separator

FLET_VERSION = "0.86.5"  # keep in sync with requirements.txt (flet>=0.86,<0.87)
FLET_CLIENT_URL = f"https://github.com/flet-dev/flet/releases/download/v{FLET_VERSION}/flet-windows.zip"


def _fetch_flet_client() -> str:
    """Download flet-windows.zip into flet_desktop/app/ inside the site
    packages of THIS interpreter, so --collect-data flet_desktop picks it up.
    Returns the path it was saved to; skips silently if already present."""
    try:
        import flet_desktop
        pkg_dir = os.path.dirname(flet_desktop.__file__)
    except ImportError:
        raise SystemExit("flet-desktop is not installed in this environment")
    app_dir = os.path.join(pkg_dir, "app")
    os.makedirs(app_dir, exist_ok=True)
    dest = os.path.join(app_dir, "flet-windows.zip")
    if os.path.isfile(dest) and os.path.getsize(dest) > 1_000_000:
        print(f"+ flet client already bundled: {dest}")
        return dest
    print(f"+ downloading {FLET_CLIENT_URL}")
    urllib.request.urlretrieve(FLET_CLIENT_URL, dest)
    size = os.path.getsize(dest) // (1024 * 1024)
    print(f"+ bundled flet client ({size} MB) -> {dest}")
    return dest


def main():
    os.chdir(ROOT)
    _fetch_flet_client()
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir",
        "--windowed",
        "--name", "Cubeon",
        f"--add-data=assets{SEP}assets",
        f"--add-data=templates{SEP}templates",
        f"--add-data=mod{SEP}mod",
        "--collect-all", "flet",
        "--collect-all", "flet_desktop",
        "--collect-submodules", "templates",
        "main.py",
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)

    # A windowed PyInstaller build runs without a console; main.py expects to
    # find its assets next to the executable (resolve_assets_dir handles both
    # dev and frozen layouts).

    zip_path = os.path.join(ROOT, "dist", "Cubeon-Windows-x64.zip")
    if os.path.exists(zip_path):
        os.unlink(zip_path)
    base = os.path.splitext(zip_path)[0]
    print(f"+ zipping dist/Cubeon -> {zip_path}")
    shutil.make_archive(base, "zip", os.path.join(ROOT, "dist"), "Cubeon")
    print("Done: dist/Cubeon/ and dist/Cubeon-Windows-x64.zip")


if __name__ == "__main__":
    main()
