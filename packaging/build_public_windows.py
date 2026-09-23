"""Build the Windows public/no-Friends package."""
import importlib.util
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_assets", ROOT / "packaging" / "public_assets.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _bundle_flet_client():
    """flet_desktop must be collected + its client zip bundled, or the frozen
    exe pip-installs/downloads at runtime and dies instantly. Full story in
    packaging/build_windows.py."""
    import flet_desktop
    pkg_dir = os.path.dirname(flet_desktop.__file__)
    app_dir = os.path.join(pkg_dir, "app")
    os.makedirs(app_dir, exist_ok=True)
    dest = os.path.join(app_dir, "flet-windows.zip")
    if not (os.path.isfile(dest) and os.path.getsize(dest) > 1_000_000):
        url = (f"https://github.com/flet-dev/flet/releases/download/"
               f"v{flet_desktop.version.version}/flet-windows.zip")
        print(f"+ downloading {url}")
        urllib.request.urlretrieve(url, dest)
    print(f"+ bundled flet client -> {dest}")


assets = module.make_public_assets(str(ROOT))
try:
    os.chdir(ROOT)
    _bundle_flet_client()
    sep = ";" if os.name == "nt" else ":"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--onedir", "--windowed", "--name", "Cubeon",
                    # Same as the full build: the exe must show the Cubeon
                    # logo in Explorer/the taskbar, not PyInstaller's art.
                    "--icon=assets/icon.ico",
                    f"--add-data={assets}{sep}assets",
                    f"--add-data=templates{sep}templates",
                    "--collect-all", "flet",
                    "--collect-all", "flet_desktop",
                    "--collect-all", "minecraft_launcher_lib",
                    "--collect-submodules", "templates", "main.py"],
                   check=True)
    zip_path = ROOT / "dist" / "Cubeon-public-Windows-x64.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", ROOT / "dist", "Cubeon")
    print("Built public Cubeon Windows package (Friends disabled)")
finally:
    shutil.rmtree(assets, ignore_errors=True)
