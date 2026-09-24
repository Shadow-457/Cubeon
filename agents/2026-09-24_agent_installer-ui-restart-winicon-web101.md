# Restart button on Linux, Windows icon & installer UI polish, Web 1.0.1 (2026-09-24)

- **Agent:** Antigravity
- **Date:** 2026-09-24
- **Task:** Fix restart button on Linux, fix app crash on `flet.ImageFit`, update Windows installer UI to remove technical look, fix Windows icon, and show version 1.0.1 on the web.

## What was done
1. **Linux Seasonal Restart Button**:
   - The user runs `~/.local/opt/Cubeon/Cubeon.AppImage` invoked via `~/.local/share/applications/cubeon.desktop`.
   - Rebuilt the Linux AppImage (`packaging/build_appimage.sh`) bundling all the latest fixes and updated `~/.local/opt/Cubeon/Cubeon.AppImage`.
2. **Crash on `AttributeError: module 'flet' has no attribute 'ImageFit'`**:
   - Fixed `ui/chat_tab.py` lines 490 & 527: replaced `ft.ImageFit.COVER` with `ft.BoxFit.COVER` (the correct Flet 0.86 enum).
3. **Windows Icon**:
   - Added `icon='assets/icon.ico'` into `Cubeon.spec`'s `EXE` block, complementing the `--icon=assets/icon.ico` in the build scripts so Windows executables and shortcuts always display the official icon.
4. **Windows Installer UI Overhaul**:
   - Upgraded `packaging/Cubeon.nsi` to use Modern UI 2 with custom branded sidebar (`packaging/graphics/wizard.bmp`) and header (`packaging/graphics/header.bmp`).
   - Cleaned up titles and text ("Welcome to Cubeon", "Play Minecraft with friends easily. No technical setup, no port forwarding", "Launch Cubeon").
   - Hidden raw technical file extraction scroll (`ShowInstDetails hide`).
   - Wired bitmap options into `packaging/build_windows_installer.py`.
5. **Website Version 1.0.1**:
   - Bumped `APP_VERSION = "1.0.1"` in `cubeon/updater.py`.
   - Updated `web/index.html` and `web/download.html` download buttons and metadata badges to display version 1.0.1.

## Verification
- `python tools/test_ui_smoke.py`: 160 passed, 0 failed.
- AppImage verified and installed at `~/.local/opt/Cubeon/Cubeon.AppImage`.
- No lingering `ImageFit` in repository.
