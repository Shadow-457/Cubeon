#!/usr/bin/env bash
# Build the Linux AppImage. Run from the repo root: bash packaging/build_appimage.sh
#
# flet_desktop MUST be collected (and its client tarball bundled at build
# time) or the frozen app tries to pip-install/download at runtime and dies
# before a window opens. See packaging/build_windows.py for the full story.
set -e
cd "$(dirname "$0")/.."

FLET_VERSION="$(python -c 'import flet_desktop.version; print(flet_desktop.version.version)')"
CLIENT_TAR="$(python -c 'import flet_desktop; print(flet_desktop.get_artifact_filename())')"
APP_DIR="$(python -c 'import flet_desktop, os; print(os.path.join(os.path.dirname(flet_desktop.__file__), "app"))')"
mkdir -p "$APP_DIR"
if [ ! -s "$APP_DIR/$CLIENT_TAR" ]; then
  echo "+ downloading flet client $CLIENT_TAR"
  curl -fL "https://github.com/flet-dev/flet/releases/download/v${FLET_VERSION}/${CLIENT_TAR}" \
    -o "$APP_DIR/$CLIENT_TAR"
fi
echo "+ bundled flet client: $APP_DIR/$CLIENT_TAR"

python -m PyInstaller --noconfirm --clean --onedir --name Cubeon \
  --add-data "assets:assets" \
  --add-data "mod/brackets.json:mod" \
  --collect-data flet \
  --collect-submodules flet \
  --collect-binaries flet \
  --collect-data minecraft_launcher_lib \
  --collect-submodules minecraft_launcher_lib \
  --collect-binaries minecraft_launcher_lib \
  --collect-data flet_desktop \
  --collect-submodules flet_desktop \
  --collect-binaries flet_desktop \
  --collect-submodules templates \
  main.py
# NOTE: no --add-data for templates/ - the palettes ship as bytecode via
# --collect-submodules only, so the artifact contains no readable .py source.

APPDIR=dist/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mv dist/Cubeon/* "$APPDIR/usr/bin/"
rmdir dist/Cubeon
cp assets/icon_256.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/cubeon.png"
cp assets/icon_256.png "$APPDIR/cubeon.png"
cat > "$APPDIR/cubeon.desktop" <<'EOF'
[Desktop Entry]
Name=Cubeon
Exec=AppRun
Icon=cubeon
Type=Application
Categories=Game;
Comment=Minecraft launcher with a friends layer
EOF
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Cubeon" "$@"
EOF
chmod +x "$APPDIR/AppRun"
mkdir -p dist
if [ -x dist/appimagetool ] || curl -sL -o dist/appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage; then
  chmod +x dist/appimagetool
  APPIMAGE_EXTRACT_AND_RUN=1 dist/appimagetool "$APPDIR" dist/Cubeon-x86_64.AppImage
  echo "Built dist/Cubeon-x86_64.AppImage"
else
  tar -czf dist/Cubeon-Linux-x86_64.tar.gz -C dist AppDir
  echo "Built dist/Cubeon-Linux-x86_64.tar.gz"
fi

