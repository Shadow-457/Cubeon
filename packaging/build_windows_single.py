"""Build one stand-alone Cubeon.exe (PyInstaller --onefile) that carries the
whole runtime + the flet client, so the shipped artifact IS the executable.

Run under wine with the Windows interpreter (see build_windows.py / the wine
diary). Output: dist/Cubeon-Windows-x64-single.exe -- one file, nothing else.
Runtime first-launch is slower (self-extracts ~150MB to a temp dir) and
antivirus heuristics flag self-extracting exes more often, but there is
nothing to install or keep together.
"""
import os
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fetch_flet_client() -> str:
    """flet_desktop must be collected + its client zip bundled, or the frozen
    exe pip-installs/downloads at runtime and dies instantly (see
    build_windows.py for the full story)."""
    import flet_desktop
    pkg_dir = os.path.dirname(flet_desktop.__file__)
    app_dir = os.path.join(pkg_dir, "app")
    os.makedirs(app_dir, exist_ok=True)
    dest = os.path.join(app_dir, "flet-windows.zip")
    if os.path.isfile(dest) and os.path.getsize(dest) > 1_000_000:
        print(f"+ flet client already bundled: {dest}")
        return dest
    url = (f"https://github.com/flet-dev/flet/releases/download/"
           f"v{flet_desktop.version.version}/flet-windows.zip")
    print(f"+ downloading {url}")
    urllib.request.urlretrieve(url, dest)
    return dest


def main() -> None:
    os.chdir(ROOT)
    _fetch_flet_client()
    sep = os.pathsep  # ";" under wine
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", "Cubeon",
        # The single exe IS the product - it must carry the Cubeon icon, not
        # PyInstaller's default artwork.
        "--icon=assets/icon.ico",
        f"--add-data=assets{sep}assets",
        f"--add-data=templates{sep}templates",
        f"--add-data=mod/brackets.json{sep}mod",
        "--collect-all", "flet",
        "--collect-all", "flet_desktop",
        "--collect-all", "minecraft_launcher_lib",
        "--collect-submodules", "templates",
        "main.py",
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)

    src = os.path.join(ROOT, "dist", "Cubeon.exe")
    out = os.path.join(ROOT, "dist", "Cubeon-Windows-x64-single.exe")
    if os.path.exists(out):
        os.unlink(out)
    os.replace(src, out)
    print(f"Done: {out} ({os.path.getsize(out) // (1024 * 1024)} MB, single file)")


if __name__ == "__main__":
    main()
