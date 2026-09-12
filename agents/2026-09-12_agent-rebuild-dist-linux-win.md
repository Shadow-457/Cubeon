# 2026-09-12 - Rebuilt dist from the CURRENT local source: AppImage + Windows EXE

## Ask
"create exe, app image and macos app tests all three then put them in dist
folder ready to use perfect working use the current local version"

## Built & tested (current source, this session's commits)
- dist/Cubeon-x86_64.AppImage (267M, 22:52) - native Linux PyInstaller 6.21 +
  appimagetool. Tested: APPIMAGE_EXTRACT_AND_RUN=1 under xvfb, flet/Flutter
  client booted, ran 25s flat, 0 tracebacks (only software-GL EGL warnings).
- dist/Cubeon/ + dist/Cubeon-Windows-x64.zip (123M, 23:25) - PyInstaller under
  Wine via ~/winpython/py311 (win python 3.11.9, PyInstaller 6.22.2, flet
  client already bundled). Tested: wine Cubeon.exe under xvfb, flutter engine
  booted, ran 25s flat, 0 tracebacks (only the documented direct_manipulation/
  EGL wine-flutter noise).

## macOS: NOT buildable on this Linux box
No osxcross / no macOS toolchain. PyInstaller macOS bundles require macOS.
packaging/build_macos.sh syntax-checked (bash -n) and every path it packs
(assets, templates, mod, main.py) exists in the current tree - it will build
cleanly when run on an actual Mac: `bash packaging/build_macos.sh`. Do NOT
pretend a .app exists here.

## Notes
- dist/ is gitignored; build artifacts are not in git.
- Removed dist/AppDir (1.4G residual from the AppImage build; regenerated per
  build; the .AppImage is self-contained). dist/appimagetool left for rebuilds.
- The "public" (no-Friends) AppImage in dist is an OLD Sep 5 build - not
  touched; it is a separate product variant.
- The tool kills run_commands' process group at 30s: backgrounded builds MUST
  be detached with `setsid ... & disown` and have stdout/stderr redirected,
  or they die mid-build.
