#!/usr/bin/env bash
# Build the macOS app. Run from the repo root:  bash packaging/build_macos.sh
# Output: dist/Cubeon/ (PyInstaller onedir) and dist/Cubeon-macOS.tar.gz.
# Unsigned - macOS Gatekeeper will ask users to right-click > Open on first
# run. Signing/notarization needs an Apple Developer account ($99/yr).
#
# NOTE: --add-data assets is REQUIRED - assets/jars holds the Friends mod
# jars and the Connect plugin.
set -e
cd "$(dirname "$0")/.."

python -m PyInstaller --noconfirm --onedir --windowed \
  --name Cubeon \
  --add-data "assets:assets" \
  --collect-all flet \
  main.py

tar -czf dist/Cubeon-macOS.tar.gz -C dist Cubeon
echo "Built dist/Cubeon/ and dist/Cubeon-macOS.tar.gz"
