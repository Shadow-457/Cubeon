#!/usr/bin/env bash
# Build the macOS app. Run from the repo root:  bash packaging/build_macos.sh
# Output: dist/Cubeon.app and dist/Cubeon-macOS-{arm64,x64}.{dmg,zip}.
# Ad-hoc signed, without Apple notarization. Gatekeeper requires user approval.
# Developer ID signing/notarization needs separate Apple credentials.
#
# NOTE: --add-data assets is REQUIRED - assets/jars holds the Friends mod
# jars. Connect is downloaded during server setup, not bundled.
#
# flet_desktop MUST be collected: without it the frozen app can't import it,
# flet tries to pip-install at runtime (fails frozen), and the app dies
# before a window opens. The client tarball is fetched at BUILD time so the
# app never needs to download it on first run (see build_windows.py).
set -euo pipefail
cd "$(dirname "$0")/.."
case "$(uname -m)" in
  arm64) ARCH=arm64; TARGET_ARCH=arm64 ;;
  x86_64) ARCH=x64; TARGET_ARCH=x86_64 ;;
  *) echo "Unsupported macOS architecture" >&2; exit 1 ;;
esac
RUNTIME_ASSETS="$(python packaging/runtime_assets.py)"
trap 'rm -rf "$RUNTIME_ASSETS"' EXIT

FLET_VERSION="$(python -c 'import flet_desktop.version; print(flet_desktop.version.version)')"
CLIENT_TAR="$(python -c 'import flet_desktop; print(flet_desktop.get_artifact_filename())')"
APP_DIR="$(python -c 'import flet_desktop, os; print(os.path.join(os.path.dirname(flet_desktop.__file__), "app"))')"
mkdir -p "$APP_DIR"
if [ ! -s "$APP_DIR/$CLIENT_TAR" ]; then
  echo "+ downloading flet client $FLET_VERSION"
  curl --retry 3 -fL "https://github.com/flet-dev/flet/releases/download/v${FLET_VERSION}/${CLIENT_TAR}" \
    -o "$APP_DIR/$CLIENT_TAR"
fi
echo "+ bundled flet client: $APP_DIR/$CLIENT_TAR"

mkdir -p build
python - <<'PYICON'
from PIL import Image
Image.open("assets/icon_512.png").save("build/cubeon.icns")
PYICON

python -m PyInstaller --noconfirm --onedir --windowed \
  --name Cubeon \
  --icon build/cubeon.icns \
  --target-arch "$TARGET_ARCH" \
  --osx-bundle-identifier online.ylet.cubeon \
  --add-data "$RUNTIME_ASSETS:assets" \
  --add-data "mod/brackets.json:mod" \
  --collect-data flet \
  --collect-submodules flet \
  --collect-binaries flet \
  --collect-data flet_desktop \
  --collect-submodules flet_desktop \
  --collect-binaries flet_desktop \
  --collect-submodules cubeon.lang \
  --collect-submodules templates \
  main.py
# Only brackets.json from mod/ (rest is Java source) + templates as
# bytecode: shipped artifacts must carry no readable source files.

python - <<'PYINFO'
import plistlib
from pathlib import Path
from cubeon.updater import APP_VERSION
path = Path("dist/Cubeon.app/Contents/Info.plist")
info = plistlib.loads(path.read_bytes())
info.update(CFBundleShortVersionString=APP_VERSION, CFBundleVersion=APP_VERSION,
            NSHighResolutionCapable=True)
path.write_bytes(plistlib.dumps(info))
PYINFO
codesign --force --deep --sign - dist/Cubeon.app
codesign --verify --deep --strict dist/Cubeon.app
ditto -c -k --sequesterRsrc --keepParent dist/Cubeon.app "dist/Cubeon-macOS-${ARCH}.zip"
bash packaging/build_macos_dmg.sh dist/Cubeon.app "dist/Cubeon-macOS-${ARCH}.dmg"
echo "Built dist/Cubeon.app and the ${ARCH} DMG/ZIP"
