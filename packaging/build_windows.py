"""
Build the Windows EXE + portable ZIP. Run from the repo root:
    python packaging/build_windows.py
Output: dist/Cubeon/ (standalone folder) and dist/Cubeon-Windows-x64.zip.

NOTE: --add-data assets is REQUIRED - assets/jars holds the Friends mod jars
and the Connect plugin, and the launcher resolves them from there when
packaged. Forgetting it produces a launcher with no friends mod.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP = ";" if os.name == "nt" else ":"  # PyInstaller path separator


def main():
    os.chdir(ROOT)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir",
        "--name", "Cubeon",
        f"--add-data=assets{SEP}assets",
        f"--add-data=templates{SEP}templates",
        f"--add-data=mod{SEP}mod",
        "--collect-all", "flet",
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
