#!/usr/bin/env bash
# Build the macOS app. Run from the repo root:  bash packaging/build_macos.sh
# Output: dist/Cubeon/ (PyInstaller onedir) and dist/Cubeon-macOS.tar.gz.
# Unsigned - macOS Gatekeeper will ask users to right-click > Open on first
# run. Signing/notarization needs an Apple Developer account ($99/yr).
#
# NOTE: --add-data assets is REQUIRED - assets/jars holds the Friends mod
# jars and the Connect plugin.
#
# flet_desktop MUST be collected: without it the frozen app can't import it,
# flet tries to pip-install at runtime (fails frozen), and the app dies
# before a window opens. The client tarball is fetched at BUILD time so the
# app never needs to download it on first run (see build_windows.py).
set -e
cd "$(dirname "$0")/.."

FLET_VERSION="$(python -c 'import flet_desktop.version; print(flet_desktop.version.version)')"
CLIENT_TAR="flet-macos.tar.gz"
APP_DIR="$(python -c 'import flet_desktop, os; print(os.path.join(os.path.dirname(flet_desktop.__file__), "app"))')"
mkdir -p "$APP_DIR"
if [ ! -s "$APP_DIR/$CLIENT_TAR" ]; then
  echo "+ downloading flet client $FLET_VERSION"
  curl -fL "https://github.com/flet-dev/flet/releases/download/v${FLET_VERSION}/${CLIENT_TAR}" \
    -o "$APP_DIR/$CLIENT_TAR"
fi
echo "+ bundled flet client: $APP_DIR/$CLIENT_TAR"

python -m PyInstaller --noconfirm --onedir --windowed \
  --name Cubeon \
  --add-data "assets:assets" \
  --add-data "templates:templates" \
  --add-data "mod:mod" \
  --collect-all flet \
  --collect-all flet_desktop \
  --collect-submodules templates \
  main.py

tar -czf dist/Cubeon-macOS.tar.gz -C dist Cubeon
echo "Built dist/Cubeon/ and dist/Cubeon-macOS.tar.gz"
