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

Update `cubeon/updater.py`:
```python
APP_VERSION = "1.2.3"  # Bump per release!
```

## Release Artifacts

| Platform | Artifact | Upload Name |
|----------|----------|-------------|
| Linux | `dist/Cubeon-x86_64.AppImage` | `Cubeon-Linux-x86_64-AppImage` |
| Windows | `dist/Cubeon/` | `Cubeon-Windows-x64-Folder` |
| Windows | `dist/Cubeon-Windows-x64.zip` | `Cubeon-Windows-x64-ZIP` |
| macOS | `dist/Cubeon/` | `Cubeon-macOS` |

## CI Build

`.github/workflows/build.yml` runs on push to main/master and tags `v*`:
1. **Test suite** - runs all `tools/test_*.py` with fresh game dirs
2. **Build Linux AppImage** - Ubuntu latest
3. **Build Windows EXE** - Windows latest
4. **Build macOS** - macOS latest
5. **Upload artifacts** - named by platform

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
