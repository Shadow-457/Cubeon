"""Release version metadata.

The historical filename is retained for packaging and release stamping.
The automatic update controller lives separately in auto_update.py.
"""

APP_VERSION = "1.4.79"

# Public release filenames. Installed executables keep their existing names.
RELEASE_ASSETS = {
    "windows": "Cubeon-{version}-Windows-x64-Setup.exe",
    "linux": "Cubeon-{version}-Linux-x86_64.AppImage",
    "linux-setup": "Cubeon-{version}-Linux-x86_64-Setup.sh",
    "macos-arm64": "Cubeon-{version}-macOS-arm64.dmg",
    "macos-x64": "Cubeon-{version}-macOS-x64.dmg",
    "macos-arm64-zip": "Cubeon-{version}-macOS-arm64.zip",
    "macos-x64-zip": "Cubeon-{version}-macOS-x64.zip",
}


def release_asset_name(kind: str, version: str | None = None) -> str:
    return RELEASE_ASSETS[kind].format(version=version or APP_VERSION)
