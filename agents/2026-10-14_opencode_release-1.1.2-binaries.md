# 2026-10-14 — Release build: bump to 1.1.2, rebuild all binaries

## What the user asked for
"create new binaries bumb version to 1.1.2 and clobber everything". Clarified
scope via question: rebuild + replace `dist/` artifacts only (no `~/.cache`/GitHub
release clobber), covering Windows (zip + setup .exe) and Linux (AppImage, deb,
setup).

## Version bump
- `cubeon/updater.py`: `APP_VERSION = "1.0.4"` → `"1.1.2"`.
- Confirmed every other ref reads from `APP_VERSION` (deb name via
  `build_deb.py`, installer `DISPLAY_VERSION`/`APP_VERSION` via
  `build_windows_installer.py`, `cubeon/paths.py`). Updated the example version
  in the `cubeon-downloads.js` comment too.
- Mod jars kept `mod_version: "1.0.0"` — a separate mod-release line; this is a
  launcher release, not a mod release.

## Disk
`/home` was 99% full (2.3 GB free). Cleared the 35 G `~/.cache/yay` (AUR build
cache) and 5.3 G `~/.cache/uv` (uv cache) → 30 GB free. Both are regenerable.

## Builds
- **Linux**: host is Python 3.14 + flet 1.0.3 (wrong per `requirements.txt`
  `flet>=0.86,<0.87`). Created `.venv-build` with flet 0.86.5 + pyinstaller
  6.22.3, then `build_appimage.sh` + `build_linux_installers.py`. Output:
  `Cubeon-x86_64.AppImage`, `cubeon_1.1.2_amd64.deb`, `Cubeon-Linux-x86_64-Setup.sh`.
- **Windows**: built via wine + WinPython 3.11.9 (already provisioned: flet
  0.86.5, pyinstaller 6.22.2). `build_windows.py` → onedir + zip. NSIS installer
  via `build_windows_installer.py`; had to copy electron-builder's cached NSIS
  into the wine prefix (`~/.wine/drive_c/nsis/`) because wine's Python
  `Path.home()` resolves to `C:\users\fuckarch`, not the Linux home. Ran
  makensis directly with the same args the script computes (did not edit the
  tracked script). Output: `Cubeon-Windows-x64-Setup.exe`.
- Removed the stale `dist/cubeon_1.0.4_amd64.deb` as part of "clobber".

## Verification
- Extracted the frozen PYZ from `dist/Cubeon-x86_64.AppImage` and
  `dist/Cubeon-Windows-x64.zip` (`Cubeon/Cubeon.exe`); `cubeon.updater` bytecode
  contains exactly `1.1.2` in both.
- Core suite green: mega_smoke 20, versions_profile_key 13, friends_service
  372, web_download_count 73.

## Notes / gotchas
- `tools/build_mod_jars.py` + `tools/test_mod_compile.py` now carry the
  `YggdrasilSessionServiceMixin` registration fix (was the pre-existing gap from
  `95b33b3`). `test_mod_compile` is green. The 1.20-1.21 jar contains the mixin
  class; the `mc26` jar (Oct 5) does NOT — rebuilding it needs JDK 25, which is
  not installed here. Pre-existing, not introduced this cycle.
- `Cubeon.spec` was rewritten by the Windows PyInstaller run but is byte-identical
  (no diff). Build dirs (`build/`, `dist/Cubeon/`, `.venv-build/`) are gitignored.
- Nothing committed/pushed. Live site + worker deploy still pending from the
  earlier bug-fix cycle.
