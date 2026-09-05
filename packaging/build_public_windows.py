"""Build the Windows public/no-Friends package."""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_assets", ROOT / "packaging" / "public_assets.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assets = module.make_public_assets(str(ROOT))
try:
    os.chdir(ROOT)
    sep = ";" if os.name == "nt" else ":"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--onedir", "--name", "Cubeon",
                    f"--add-data={assets}{sep}assets",
                    f"--add-data=templates{sep}templates",
                    "--collect-all", "flet", "--collect-submodules", "templates", "main.py"],
                   check=True)
    zip_path = ROOT / "dist" / "Cubeon-public-Windows-x64.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", ROOT / "dist", "Cubeon")
    print("Built public Cubeon Windows package (Friends disabled)")
finally:
    shutil.rmtree(assets, ignore_errors=True)
