#!/usr/bin/env bash
# Build the Linux AppImage. Run from the repo root:  bash packaging/build_appimage.sh
# Output: dist/Cubeon-x86_64.AppImage (falls back to a .tar.gz if appimagetool
# can't be fetched - the app still works, it just isn't a single file).
#
# NOTE: --add-data assets is REQUIRED - assets/jars holds the Friends mod jars
# and the Connect plugin, and the launcher resolves them from there when
# packaged. Forgetting it produces a launcher with no friends mod.
set -e
cd "$(dirname "$0")/.."

python -m PyInstaller --noconfirm --onedir --name Cubeon \
  --add-data "assets:assets" \
  --collect-all flet \
  main.py

APPDIR=dist/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Move the onedir payload into the AppDir
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

# AppRun just execs the bundled launcher
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Cubeon" "$@"
EOF
chmod +x "$APPDIR/AppRun"

mkdir -p dist
if [ -x dist/appimagetool ] || curl -sL -o dist/appimagetool \
     https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage; then
  chmod +x dist/appimagetool
  # FUSE is often absent in CI; appimagetool accepts --appimage-extract-and-run
  APPIMAGE_EXTRACT_AND_RUN=1 dist/appimagetool "$APPDIR" dist/Cubeon-x86_64.AppImage
  echo "Built dist/Cubeon-x86_64.AppImage"
else
  echo "appimagetool unavailable - packing a tar.gz instead"
  tar -czf dist/Cubeon-Linux-x86_64.tar.gz -C dist AppDir
  echo "Built dist/Cubeon-Linux-x86_64.tar.gz"
fi
