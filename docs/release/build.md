[Documentation](../README.md) / Releases

# Building Cubeon

Use the platform scripts in `packaging/`. They include the Flet desktop
client, runtime assets, and dynamic imports that a minimal PyInstaller
command can miss.

## Prerequisites

Start with the Python environment in [Development setup](../development/setup.md):

```bash
python -m pip install pyinstaller
```

Build on the target operating system where possible. Packaging can require
network access to obtain the desktop client and build tools. Linux builds
need the system libraries required by Flet; running an AppImage may also
require FUSE support.

The mod jars and plugins in `assets/jars/` are runtime assets. If you change
the mod, rebuild its jars before packaging:

```bash
python tools/build_mod_jars.py
```

Current jar assembly needs Gradle and JDK 25 or newer. The script reads
`mod/brackets.json` and verifies the bracket-specific contents. A Java stub
compile test is not equivalent to rebuilding these jars.

## Linux

```bash
bash packaging/build_appimage.sh
```

With `dist/appimagetool` available, the script produces
`dist/Cubeon-x86_64.AppImage`. Otherwise it produces
`dist/Cubeon-Linux-x86_64.tar.gz` containing the AppDir.

Build the setup script and Debian package from the prepared AppDir:

```bash
python packaging/build_linux_installers.py
```

Outputs include `dist/Cubeon-Linux-x86_64-Setup.sh` and
`dist/cubeon_<version>_amd64.deb`. The setup script installs for the current
user under `~/.local/opt/Cubeon`; the Debian package is a system package.

## Windows

Run in the project's Windows Python environment:

```powershell
python packaging/build_windows.py
```

This produces `dist/Cubeon/` and `dist/Cubeon-Windows-x64.zip`. The portable
app is the entire folder, not just `Cubeon.exe`.

For a setup executable, build the portable folder first, then run:

```powershell
python packaging/build_windows_installer.py
```

This produces `dist/Cubeon-Windows-x64-Setup.exe` and needs NSIS. An optional
single-file portable build is available through
`python packaging/build_windows_single.py`.

Windows Python can also run the build scripts under Wine. Use a configured
Windows Python environment, not Linux Python with a Windows output name.
A successful Wine launch does not replace testing on Windows; follow the
[Windows smoke test](windows-smoke-test.md).

## macOS

```bash
bash packaging/build_macos.sh
```

The local script produces `dist/Cubeon/` and
`dist/Cubeon-macOS.tar.gz`. The release workflow produces the separately
packaged `Cubeon-macOS.zip` asset. Check the workflow for its current bundle
steps rather than assuming the local script creates an identical artifact.

Code signing and notarization require their own credentials and are not
provided by a local PyInstaller build.

## Public builds

Separate scripts produce builds with Friends disabled:

```bash
bash packaging/build_public_appimage.sh
python packaging/build_public_windows.py
```

They use a curated asset set and a no-Friends marker. The normal source and
development builds enable Friends by default. See `cubeon/features.py`
before changing that policy.

## Packaging requirements

- Bundle the Flet desktop client at build time. A frozen app must not depend
  on installing or downloading its window client on first launch.
- Include `assets/` and `mod/brackets.json`, including the required jars.
- Collect the Python modules and binaries used by Flet and
  `minecraft_launcher_lib`.
- Include dynamically loaded color templates. The Windows script lists
  them explicitly; update that list when adding a palette.

`Cubeon.spec` supports a direct PyInstaller build, but the platform scripts
perform additional preparation. Do not replace their collection options
with a generic command without checking the resulting artifact.

## Versions and releases

`APP_VERSION` in `cubeon/updater.py` is the application version. Release
tooling stamps the app and, for stable releases, the website:

```bash
python tools/release_version.py next
python tools/release_version.py stamp 1.4.0
```

`next` is a preview. `stamp` modifies files. Current channel policy treats
versions with a zero patch component as stable and nonzero patches as beta;
check `tools/release_version.py` before changing this policy.

The [release workflow](../../.github/workflows/build.yml) creates a draft,
builds the platform assets from its tag, and verifies the assets before
publishing. Betas are prereleases and must not replace the stable download.
The test jobs run separately; successful publishing does not imply that
every test passed.

The download Worker depends on these release asset names:

| Platform | Release assets |
| --- | --- |
| Linux | `Cubeon-x86_64.AppImage`, `Cubeon-Linux-x86_64-Setup.sh`, `cubeon_<version>_amd64.deb` |
| Windows | `Cubeon-Windows-x64-Setup.exe`, `Cubeon-Windows-x64.zip` |
| macOS | `Cubeon-macOS.zip` |

Renaming an asset requires corresponding changes to the workflow and
`worker/cubeon-downloads.js`.

## Verify the artifact

Launch the packaged app outside the source checkout. Confirm that a window
appears, assets load, the expected feature set is present, and a game can
launch. Check `~/.cubeon_launcher/cubeon.log` for errors.

Record the actual platform tested. A successful build, a headless test, and
a working desktop app are separate results. Continue with the
[release checklist](release-checklist.md) before publishing.
