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

The companion mod jars in `assets/jars/` are bundled runtime assets. The platform
scripts stage assets through `packaging/runtime_assets.py`, which excludes only
`connect-spigot.jar`, which is also ignored by Git: Paper setup downloads that plugin from its developer's
GitHub release and caches a verified copy for later servers. Keep the desktop
client, companion jars and other launcher assets bundled. If you change the
mod, rebuild its jars before packaging:

```bash
python tools/build_mod_jars.py
```

Current jar assembly needs Gradle and JDK 25 or newer. The script reads
`mod/brackets.json` and verifies the bracket-specific contents. A Java stub
compile test is not equivalent to rebuilding these jars.

Forge 1.8.9 uses a separate Java 8/SRG companion build:

```bash
python tools/build_forge189_client.py
python tools/test_forge189_client.py --targets --download-csl
```

The target check needs cached Minecraft/Forge inputs and checks the transformed
runtime hooks. The CSL check installs the compatible published release in an
isolated test home. Forge 1.8.9 gameplay and installation require exact Java 8;
this version is available with Legacy disabled. Native Rust build/package steps
are in [Rust integration](../development/horizon-integration-plan.md).

On Linux, `python tools/test_forge189_client.py --download-csl --native` also
verifies Java 8 startup, CSL skin hooks and Cubeon Client loading without
screenshots. It needs an installed Forge 1.8.9 profile, Java 8 and Xvfb;
use `--java8` and `--forge-version` for alternate cached runtime/profile paths.

## Linux

Release builds use **Ubuntu 22.04**, not `ubuntu-latest`: a rolling runner can
bundle a Python runtime that requires AVX2 and crashes on older x86-64 CPUs
before launcher code runs. `tools/check_linux_runtime.py` exercises the frozen
runtime and its native libraries before packing. CI installs `qemu-user` and
sets `CUBEON_REQUIRE_CPU_CHECK=1`, requiring the probe to pass with a Nehalem CPU
(no AVX). Local builds without QEMU check the host CPU only.

```bash
bash packaging/build_appimage.sh
```

For an isolated local build, set absolute `CUBEON_BUILD_DIST` and
`CUBEON_BUILD_WORK` paths. Building on a newer distribution can increase the
required glibc version; a successful local CPU probe does not certify the
release's distribution compatibility. The hidden `--cubeon-runtime-check`
argument runs offline without initializing the UI or accessing player data.

With `dist/appimagetool` available, the script produces
`dist/Cubeon-<version>-Linux-x86_64.AppImage`. Otherwise it produces
`dist/Cubeon-<version>-Linux-x86_64.tar.gz` containing the AppDir.

Build the offline shell installer from that AppImage:

```bash
python packaging/build_linux_installers.py
```

The output is `dist/Cubeon-<version>-Linux-x86_64-Setup.sh`. Run it with `bash`
using the downloaded filename. It installs for the current user under
`~/.local/opt/Cubeon`, includes the AppImage and icon, verifies its payload,
and adds a menu launcher with a fallback for systems without FUSE. Installation
works offline; AppImages still need Flet's system libraries. Set
`CUBEON_INSTALL_DIR` to select another installation folder.

Releases ship the regular AppImage and shell setup. The graphical setup
AppImage and Debian package are no longer built or published. The historical
graphical helper remains for verification of already shipped installers.
Old `/linuxinstaller` and `/linuxdeb` download links redirect to `/linuxsetup`.

## Windows

Run in the project's Windows Python environment:

```powershell
python packaging/build_windows.py
```

This produces `dist/Cubeon/`, the internal payload for the installer.
Distribute the setup executable; Windows portable builds have been removed.

To build the setup executable from that payload, run:

```powershell
python packaging/build_windows_installer.py
```

This produces `dist/Cubeon-<version>-Windows-x64-Setup.exe` and needs NSIS.

Windows Python can also run the build scripts under Wine. Use a configured
Windows Python environment, not Linux Python with a Windows output name.
A successful Wine launch does not replace testing on Windows; follow the
[Windows smoke test](windows-smoke-test.md).

## macOS

```bash
bash packaging/build_macos.sh
```

The script produces `dist/Cubeon.app` and native
`dist/Cubeon-<version>-macOS-{arm64,x64}.dmg` installers, with ZIP copies also retained.
Each DMG contains Cubeon.app and an Applications shortcut for drag-and-drop installation. CI builds on native `macos-15` and `macos-15-intel` runners, verifies
the bundle and bundled Flet architecture/signatures, and checks that the
packaged launcher reaches its first desktop frame and stays open for 15 seconds
through both direct executable and Finder/LaunchServices startup before uploading.
The smoke check follows the actual Cubeon and native Flet processes; macOS's
`open -W` helper can exit while the application is still starting or running.

Bundles are ad-hoc signed. Developer ID signing and Apple notarization need
separate credentials; these builds may require Gatekeeper approval. Desktop
startup verification does not certify every Minecraft version on macOS.
Mac preview downloads use `/macosarm64download` and `/macosx64download`, which
follow the newest published release. Windows/Linux website routes keep the
stable channel. A release remains private until both Mac DMGs/ZIPs and all existing
Windows/Linux assets are present.

## Public builds

A separate script produces Linux builds with Friends disabled:

```bash
bash packaging/build_public_appimage.sh
```

They use a curated asset set and a no-Friends marker. The normal source and
development builds enable Friends by default. See `cubeon/features.py`
before changing that policy.

## Packaging requirements

- Bundle the Flet desktop client at build time. A frozen app must not depend
  on installing or downloading its window client on first launch.
- Include the staged `assets/` and `mod/brackets.json`, including the required
  companion jars but not the on-demand Connect plugin.
- Collect the Python modules and binaries used by Flet and
  `minecraft_launcher_lib`.
- Include dynamically loaded color templates. The Windows script lists
  them explicitly; update that list when adding a palette.

`Cubeon.spec` is a generated local build file, not the maintained packaging entry
point. Use the platform scripts so asset filtering and desktop-client preparation
remain intact. Do not replace their collection options with a generic command
without checking the resulting artifact.

## Versions and releases

`APP_VERSION` in `cubeon/updater.py` is the application version. Release
tooling stamps the app and, for stable releases, the website:

```bash
python tools/release_version.py next
python tools/release_version.py stamp 1.4.0
```

`next` is a preview. `stamp` modifies files. Current channel policy treats
versions with a zero patch component as stable and nonzero patches as beta,
except explicit maintainer promotions in `STABLE_PROMOTIONS` (v1.3.27, v1.3.28,
v1.3.38, v1.3.45, v1.4.20 and v1.4.50). Stable stamps update English and localized website version labels.
Promoting a published build preserves its tag and binaries. Commit promotion
metadata and website stamps with `[skip ci]` so the push does not create another
beta. Do not rerun an older workflow commit that predates the promotion policy;
use the current workflow if a rebuild is needed.

The [release workflow](../../.github/workflows/build.yml) creates a draft,
builds the platform assets from its tag, and verifies the assets before
publishing. Betas are prereleases and must not replace the stable download.
Tag reservation retries failed GitHub writes up to five times at the same commit
and version. A tag already pointing at that commit counts as success; only a
confirmed different target advances the version. Permission failures still stop
the release, and no existing tag is overwritten.
The test jobs run separately; successful publishing does not imply that
every test passed.

Installed Windows copies and user-owned Linux AppImages can check GitHub
release metadata through `cubeon/auto_update.py`; both versioned and historical
asset names are supported. Mac upgrades use the downloaded DMG or ZIP.
An older installed updater that only recognizes fixed filenames may need one
manual upgrade when release assets first switch to versioned names.
Windows packaging verifies the real NSIS installation, upgrade and rollback
transactions before building the installer. Helper fixtures use an explicit
starting version so a release stamp cannot invalidate them.

The download Worker depends on these release asset names:

| Platform | Release assets |
| --- | --- |
| Linux | `Cubeon-<version>-Linux-x86_64.AppImage`, `Cubeon-<version>-Linux-x86_64-Setup.sh` |
| Windows | `Cubeon-<version>-Windows-x64-Setup.exe` |
| macOS | `Cubeon-<version>-macOS-arm64.dmg`, `Cubeon-<version>-macOS-x64.dmg`, matching `.zip` alternatives |
| Update metadata | `update-<version>.json` covering all seven binaries |

Every release-producing push to `main`/`master` or a version tag generates
the combined JSON after all platform uploads succeed. `[skip ci]` commits
and manual `full_tests` dispatches do not create releases. The publish job reads
the draft using `gh release view --json apiUrl`, verifies exact versioned names,
upload state, nonempty size, download URLs and GitHub SHA-256 digests, then
attaches the manifest before making the draft public. A missing binary or
digest keeps the release private.
Draft assets may have GitHub's temporary `untagged-...` download URLs. The
generator accepts those only when they match the same draft's trusted GitHub
page, repository and filename. The manifest always records the final version
tag URLs that become available when publication finishes.

`tools/release_version.py manifest <version> --release-json <api-response.json>
--repository <owner/repo> --channel <stable-or-beta>` reproduces generation
locally. Its `assets` map uses `windows`, `linux`, `linux-setup`, `macos-arm64`,
`macos-x64`, `macos-arm64-zip` and `macos-x64-zip`; each entry contains `name`,
`url`, `size` and `sha256`. The shared Python filename contract lives in
`cubeon/updater.py`. The Worker resolves the selected release's versioned name
first, falling back to an exact historical name for older releases.
The Mac DMG repair workflow refreshes an existing manifest after both images
are replaced, keeping its checksums aligned with the repaired assets.

Renaming an asset requires corresponding changes to the workflow and
`worker/cubeon-downloads.js`.

## Verify the artifact

Launch the packaged app outside the source checkout. Confirm that a window
appears, assets load, the expected feature set is present, and a game can
launch. Check `~/.cubeon_launcher/cubeon.log` for errors.

Record the actual platform tested. A successful build, a headless test, and
a working desktop app are separate results. Continue with the
[release checklist](release-checklist.md) before publishing.
