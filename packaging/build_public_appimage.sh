#!/usr/bin/env bash
# Public Linux build: normal launcher, Friends feature disabled.
set -e
cd "$(dirname "$0")/.."
PUBLIC_ASSETS=$(python -c 'import importlib.util; s=importlib.util.spec_from_file_location("public_assets", "packaging/public_assets.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.make_public_assets("."))')
trap 'rm -rf "$PUBLIC_ASSETS"' EXIT
python -m PyInstaller --noconfirm --clean --onedir --name Cubeon \
  --add-data "$PUBLIC_ASSETS:assets" \
  --add-data "templates:templates" \
  --collect-all flet --collect-submodules templates main.py
APPDIR=dist/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mv dist/Cubeon/* "$APPDIR/usr/bin/"; rmdir dist/Cubeon
cp "$PUBLIC_ASSETS/icon_256.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/cubeon.png"
cp "$PUBLIC_ASSETS/icon_256.png" "$APPDIR/cubeon.png"
cat > "$APPDIR/cubeon.desktop" <<'EOF'
[Desktop Entry]
Name=Cubeon
Exec=AppRun
Icon=cubeon
Type=Application
Categories=Game;
Comment=Minecraft launcher
EOF
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Cubeon" "$@"
EOF
chmod +x "$APPDIR/AppRun"
if [ -x dist/appimagetool ] || curl -sL -o dist/appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage; then
  chmod +x dist/appimagetool
  APPIMAGE_EXTRACT_AND_RUN=1 dist/appimagetool "$APPDIR" dist/Cubeon-public-x86_64.AppImage
else
  tar -czf dist/Cubeon-public-Linux-x86_64.tar.gz -C dist AppDir
fi
echo "Built public Cubeon in dist/ (Friends disabled)"
