#!/usr/bin/env bash
# Install the adjacent Cubeon AppImage for the current user.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APPIMAGE="${1:-$SCRIPT_DIR/Cubeon-x86_64.AppImage}"
ICON="${CUBEON_ICON:-$SCRIPT_DIR/cubeon.png}"
PREFIX="${CUBEON_INSTALL_DIR:-$HOME/.local/opt/Cubeon}"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

if [[ ! -f "$APPIMAGE" ]]; then
  echo "Cubeon AppImage not found: $APPIMAGE" >&2
  echo "Place Cubeon-x86_64.AppImage beside this installer or pass its path." >&2
  exit 1
fi
if [[ ! -f "$ICON" ]]; then
  echo "Cubeon icon not found: $ICON" >&2
  exit 1
fi

install -d "$PREFIX" "$APP_DIR" "$ICON_DIR"
install -m 0755 "$APPIMAGE" "$PREFIX/Cubeon.AppImage"
install -m 0644 "$ICON" "$ICON_DIR/cubeon.png"

cat > "$APP_DIR/cubeon.desktop" <<DESKTOP
[Desktop Entry]
Name=Cubeon
Comment=Minecraft launcher with a friends layer
Exec=$PREFIX/Cubeon.AppImage
Icon=$ICON_DIR/cubeon.png
Terminal=false
Type=Application
Categories=Game;
StartupNotify=true
DESKTOP

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

echo "Cubeon installed for $USER. Launch it from your application menu or run:"
echo "  $PREFIX/Cubeon.AppImage"
