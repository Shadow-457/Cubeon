#!/usr/bin/env bash
# The release builder appends a verified AppImage + icon payload to this file.
set -euo pipefail

PAYLOAD_SHA256="@PAYLOAD_SHA256@"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PREFIX="${CUBEON_INSTALL_DIR:-$HOME/.local/opt/Cubeon}"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

TEMP_DIR="$(mktemp -d -t cubeon-setup.XXXXXX)"
trap 'rm -rf -- "$TEMP_DIR"' EXIT

if [[ "$(uname -m)" != x86_64 ]]; then
  echo "This Cubeon installer needs a 64-bit x86 Linux system." >&2
  exit 1
fi
for dependency in tar sha256sum install; do
  command -v "$dependency" >/dev/null || { echo "Setup needs $dependency." >&2; exit 1; }
done
if [[ "$PAYLOAD_SHA256" != '@PAYLOAD_SHA256@' ]]; then
  PAYLOAD_LINE="$(awk '/^__CUBEON_PAYLOAD__$/ { print NR + 1; exit }' "$0")"
  tail -n +"$PAYLOAD_LINE" "$0" > "$TEMP_DIR/payload.tar.gz"
  printf '%s  %s\n' "$PAYLOAD_SHA256" "$TEMP_DIR/payload.tar.gz" | sha256sum --check --status || {
    echo "The installer download is incomplete or damaged. Please download it again." >&2
    exit 1
  }
  tar -xzf "$TEMP_DIR/payload.tar.gz" --no-same-owner -C "$TEMP_DIR"
  APPIMAGE_SOURCE="$TEMP_DIR/Cubeon.AppImage"
  ICON_SOURCE="$TEMP_DIR/cubeon.png"
else
  APPIMAGE_SOURCE="${1:-$SCRIPT_DIR/Cubeon-x86_64.AppImage}"
  ICON_SOURCE="${CUBEON_ICON:-$SCRIPT_DIR/cubeon.png}"
fi
[[ -s "$APPIMAGE_SOURCE" && -s "$ICON_SOURCE" ]] || {
  echo "Setup is missing its AppImage or icon. Download the complete Cubeon Linux setup." >&2
  exit 1
}
case "$PREFIX$APP_DIR$ICON_DIR" in
  *$'\n'*|*$'\r'*) echo "Install paths cannot contain line breaks." >&2; exit 1 ;;
esac

install -d "$PREFIX" "$APP_DIR" "$ICON_DIR"
[[ -w "$APP_DIR" && -w "$ICON_DIR" ]] || {
  echo "Setup cannot write to your application-menu or icon folder. Check their permissions and try again." >&2
  exit 1
}
PREFIX="$(CDPATH= cd -- "$PREFIX" && pwd)"
REPLACEMENT="$(mktemp "$PREFIX/.cubeon-install.XXXXXX")"
BACKUP=""
trap 'rm -rf -- "$TEMP_DIR"; rm -f -- "$REPLACEMENT" "$BACKUP"' EXIT
install -m 0755 "$APPIMAGE_SOURCE" "$REPLACEMENT"
if [[ -f "$PREFIX/Cubeon.AppImage" ]]; then
  BACKUP="$(mktemp "$PREFIX/.cubeon-previous.XXXXXX")"
  cp -p -- "$PREFIX/Cubeon.AppImage" "$BACKUP"
  mv -f -- "$BACKUP" "$PREFIX/Cubeon.AppImage.cubeon-previous"
fi
mv -f -- "$REPLACEMENT" "$PREFIX/Cubeon.AppImage"
install -m 0644 "$ICON_SOURCE" "$ICON_DIR/cubeon.png"

# Fedora/Ubuntu without libfuse2 can use AppImage's extraction mode.
cat > "$PREFIX/cubeon" <<'LAUNCHER'
#!/usr/bin/env bash
set -e
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export CUBEON_APPIMAGE_PATH="$HERE/Cubeon.AppImage"
if [[ ! -r /dev/fuse || ! -w /dev/fuse ]] || ! ldconfig -p 2>/dev/null | grep -q 'libfuse.so.2'; then
  export APPIMAGE_EXTRACT_AND_RUN=1
fi
exec "$HERE/Cubeon.AppImage" "$@"
LAUNCHER
chmod 0755 "$PREFIX/cubeon"

# Desktop Exec has its own escaping rules, separate from shell quoting.
EXEC_PATH="$(printf '%s' "$PREFIX/cubeon" | sed 's/\\/\\\\\\\\/g; s/"/\\\\"/g; s/`/\\\\`/g; s/\$/\\\\$/g; s/%/%%/g')"

cat > "$APP_DIR/cubeon.desktop" <<DESKTOP
[Desktop Entry]
Name=Cubeon
Comment=Minecraft launcher with a friends layer
Exec=/usr/bin/env "$EXEC_PATH"
Icon=cubeon
Terminal=false
Type=Application
Categories=Game;
StartupNotify=true
DESKTOP

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
fi
echo "Cubeon is installed. Open it from your application menu, or run:"
printf '  %q\n' "$PREFIX/cubeon"
exit 0
__CUBEON_PAYLOAD__
