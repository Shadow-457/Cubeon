#!/usr/bin/env bash
# Package an existing verified .app; shared by normal builds and release repair.
set -euo pipefail
APP_BUNDLE="${1:?Pass the Cubeon.app path}"
OUTPUT="${2:?Pass the output DMG path}"
if [ "$(uname -s)" != Darwin ] || [ ! -d "$APP_BUNDLE/Contents" ]; then
  echo "DMG packaging requires macOS and a built Cubeon.app" >&2
  exit 1
fi
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/cubeon-dmg.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
ditto "$APP_BUNDLE" "$STAGING/Cubeon.app"
ln -s /Applications "$STAGING/Applications"
mkdir -p "$(dirname "$OUTPUT")"
hdiutil create -volname Cubeon -srcfolder "$STAGING" -ov -format UDZO "$OUTPUT"
hdiutil verify "$OUTPUT"
echo "Built $OUTPUT"
