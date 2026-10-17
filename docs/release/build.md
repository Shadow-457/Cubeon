# Building Cubeon

## Prerequisites

### Linux (AppImage)
```bash
sudo apt-get update
sudo apt-get install -y libfuse2 libgtk-3-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev
pip install pyinstaller
```

### Windows (EXE/ZIP)
- Windows 10/11
- Python 3.11+ with `pyinstaller`
- Or cross-compile from Linux via Wine (see below)

### macOS (App Bundle)
- macOS 12+
- Python 3.11+ with `pyinstaller`

## Build Commands

### Linux AppImage
```bash
chmod +x packaging/build_appimage.sh
./packaging/build_appimage.sh
# Output: dist/Cubeon-x86_64.AppImage
```

### Linux setup installer and Debian package
```bash
# Uses the AppImage/AppDir built above; no root access is needed to build.
python packaging/build_linux_installers.py
# Outputs:
#   dist/Cubeon-Linux-x86_64-Setup.sh
#   dist/cubeon_1.0.0_amd64.deb
```
The setup script installs the AppImage for the current user under
`~/.local/opt/Cubeon` and creates an application-menu entry. The `.deb`
installs the same verified launcher under `/opt/cubeon` with a system desktop
entry when installed through a Debian package manager.

### Windows EXE & ZIP (on Windows)
```bash
python packaging/build_windows.py
# Output: dist/Cubeon/ (folder) and dist/Cubeon-Windows-x64.zip
```

### Windows EXE & ZIP (cross-compile from Linux via Wine)
```bash
# Requires Wine + WinPython
# See agents/docs/wine-windows-build.md for full recipe
wine Z:\home\user\winpython\py311\python.exe -m PyInstaller \
  --noconfirm --onedir --windowed --name Cubeon \
  --add-data="assets:assets" --add-data="templates:templates" \
  --add-data="mod/brackets.json:mod" \
  --collect-all flet --collect-all flet_desktop \
  --collect-all minecraft_launcher_lib \
  --collect-submodules templates \
  main.py
```

### Windows portable single EXE (from Linux)
```bash
wine /home/user/winpython/py311/python.exe packaging/build_windows_single.py
# Output: dist/Cubeon-Windows-x64-single.exe
```
This is portable: double-click it on Windows and Cubeon runs without Python or
an installer. It does not create Start Menu shortcuts.

### Windows installer with Start Menu/Desktop shortcuts (from Linux)
```bash
wine /home/user/winpython/py311/python.exe packaging/build_windows.py
python packaging/build_windows_installer.py
# Output: dist/Cubeon-Windows-x64-Setup.exe
```
The setup EXE installs per-user under `%LOCALAPPDATA%\Cubeon`, creates
shortcuts, and includes the already-built onedir package. It does not require
administrator permission. Windows users only run the setup EXE; they do not
need Python, Wine, or a separate build step.

### macOS App Bundle
```bash
chmod +x packaging/build_macos.sh
./packaging/build_macos.sh
# Output: dist/Cubeon/ (app bundle)
```

## Build Scripts

| Script | Platform | Output |
|--------|----------|--------|
| `packaging/build_appimage.sh` | Linux | `dist/Cubeon-x86_64.AppImage` |
| `packaging/build_linux_installers.py` | Linux | setup `.sh` + `.deb` |
| `packaging/build_macos.sh` | macOS | `dist/Cubeon/` (app bundle) |
| `packaging/build_windows.py` | Windows | `dist/Cubeon/` + `dist/Cubeon-Windows-x64.zip` |
| `packaging/build_windows_single.py` | Windows | `dist/Cubeon-Windows-x64-single.exe` (onefile) |
| `packaging/build_windows_installer.py` | Windows/Linux + Wine | `dist/Cubeon-Windows-x64-Setup.exe` |

## PyInstaller Spec

The `Cubeon.spec` file controls the build:
- Bundles `assets/`, `templates/`, and only `mod/brackets.json` via `--add-data`
- `--collect-all flet --collect-all flet_desktop` (mandatory)
- `--collect-all minecraft_launcher_lib` (mandatory)
- `--collect-submodules templates` for seasonal palettes

**Important:** `--collect-all flet_desktop` is REQUIRED - without it the frozen exe tries to pip-install at runtime and exits before a window appears.

## Assets

Build-time assets (bundled into the exe):
- `assets/jars/` - both mod jars + `connect-spigot.jar`
- `assets/capes/` - cape source PNG
- `assets/fonts/` - Minecraftia-Regular.ttf
- `assets/pets/` - seasonal pet GIFs
- `assets/icons/` - app icons (16-512px + .ico)
- `assets/titleimg.jpg` - Play tab banner

## Mod Jars

Mod jars must be built **before** packaging:
```bash
python tools/build_mod_jars.py
# Builds one jar per bracket in mod/brackets.json
# Copies to ~/.cubeon_launcher/cache/ and assets/jars/
```

The build scripts copy `assets/jars/` into the frozen app.

## Version Bumping

`cubeon/updater.py` holds the one version string (`APP_VERSION`); the release
pipeline, `packaging/build_deb.py` and `packaging/build_windows_installer.py`
all read that literal out of the source.

**You normally don't touch it.** CI stamps it on every release
(`tools/release_version.py stamp <version>`), commits the bump back to main as
`release: vX.Y.Z [skip ci]`, tags that commit and builds from the tag. The site
text in `web/index.html` / `web/download.html` is stamped in the same pass.

Setting `APP_VERSION` yourself declares a release: if `vAPP_VERSION` isn't a tag
yet, the next push releases exactly that (this is how you start a new minor
series, e.g. `APP_VERSION = "1.3.0"`). Otherwise each push bumps the patch of
the highest tag. To change a version by hand always use the tool, never a text
edit, so the tag, the app and the site can't drift apart:

```bash
python3 tools/release_version.py next          # what the next push will release
python3 tools/release_version.py stamp 1.2.3    # rewrite APP_VERSION + the site
```

## Release Artifacts

| Platform | Built file | Release asset name |
|----------|-----------|--------------------|
| Linux | `dist/Cubeon-x86_64.AppImage` | `Cubeon-x86_64.AppImage` |
| Linux | `dist/cubeon_<APP_VERSION>_amd64.deb` | `cubeon_<APP_VERSION>_amd64.deb` |
| Linux | `dist/Cubeon-Linux-x86_64-Setup.sh` | `Cubeon-Linux-x86_64-Setup.sh` |
| Windows | `dist/Cubeon-Windows-x64-Setup.exe` | `Cubeon-Windows-x64-Setup.exe` |
| Windows | `dist/Cubeon-Windows-x64.zip` | `Cubeon-Windows-x64.zip` |
| macOS | `dist/Cubeon.app` (zipped) | `Cubeon-macOS.zip` |

`worker/cubeon-downloads.js` resolves these by name (the `.deb` by
prefix+suffix, since its name carries the version), so the names are a contract.

## CI Build

`.github/workflows/build.yml` runs on every push to main/master, on `v*` tags
and on manual dispatch:

1. **release** — decides the version (`tools/release_version.py`), stamps it,
   commits the bump back (`[skip ci]`), pushes the tag (the version lock) and
   opens a **draft** release;
2. **build-linux-appimage / build-windows-exe / build-macos** — each checks out
   that tag, re-stamps, builds and uploads its assets to the draft;
3. **publish** — verifies all six assets exist, then un-drafts the release as
   the latest one.

Nothing is user-visible until step 3: `/releases/latest` feeds both the in-app
updater and the download worker, so a half-uploaded release would offer a 404.
The `test` / `test-windows` jobs run in parallel and do **not** gate the
release (the two load-flaky suites would drop releases at random).

`tools/test_release_pipeline.py` runs this whole sequence offline against a
throwaway repo + a `gh` stub, so a mistake in the plumbing fails locally rather
than in a release.

## Verifying a Build

### Linux AppImage
```bash
chmod +x dist/Cubeon-x86_64.AppImage
./dist/Cubeon-x86_64.AppImage
# Check ~/.cubeon_launcher/cubeon.log for "UI painted OK"
```

### Windows (in Wine)
```bash
# Wine prefix state is in ~/.wine/drive_c/users/<user>/.cubeon_launcher/
wine dist/Cubeon/Cubeon.exe
# Check ~/.wine/drive_c/users/<user>/.cubeon_launcher/cubeon.log
```

### Common Build Issues

| Issue | Fix |
|-------|-----|
| "flet_desktop not found" | Add `--collect-all flet_desktop` to PyInstaller |
| "minecraft_launcher_lib not found" | Add `--collect-all minecraft_launcher_lib` |
| AppImage won't run | Install `libfuse2` |
| Windows build fails in Wine | Use WinPython, not system Python |
| Mod jar missing in build | Run `python tools/build_mod_jars.py` first |
| Seasonal pets missing | Ensure `--collect-submodules templates` |

## Artifact Locations

```
dist/
├── Cubeon-x86_64.AppImage          # Linux
├── Cubeon-Windows-x64/             # Windows folder
├── Cubeon-Windows-x64.zip          # Windows zip
├── Cubeon/                         # macOS app bundle
└── Cubeon-Windows-x64-single.exe   # Windows onefile (optional)
```

Old build output in `archive/` is safe to delete (gitignored).
