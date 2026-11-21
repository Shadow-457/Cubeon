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
`dist/Cubeon-x86_64.AppImage`. Otherwise it produces
`dist/Cubeon-Linux-x86_64.tar.gz` containing the AppDir.

Build the offline installers and Debian package from the prepared AppDir:

```bash
python packaging/build_linux_installers.py
```

Outputs include `dist/Cubeon-Linux-x86_64-Setup.AppImage`,
`dist/Cubeon-Linux-x86_64-Setup.sh` and
`dist/cubeon_<version>_amd64.deb`. Both installers install for the current
user under `~/.local/opt/Cubeon`; it includes the AppImage and icon, verifies
its payload, and adds a menu launcher with a fallback for systems without FUSE.
The graphical AppImage lets you choose the folder and open Cubeon when setup
finishes. Mark it executable, then open it. If FUSE is unavailable, run
`APPIMAGE_EXTRACT_AND_RUN=1 ./Cubeon-Linux-x86_64-Setup.AppImage`.
The terminal alternative is `bash Cubeon-Linux-x86_64-Setup.sh`. Installation
works offline; AppImages still need Flet's system libraries. The Debian package
is a system package.

The graphical installer reuses the launcher runtime and installs its own image;
the application-menu wrapper selects launcher mode. Manual upgrades rerun the
installer for the same installation folder. The release
workflow publishes both installers. The downloads Worker adds `/linuxinstaller`
for the graphical asset; deploy it before linking that route publicly.

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

This produces `dist/Cubeon-Windows-x64-Setup.exe` and needs NSIS.

Windows Python can also run the build scripts under Wine. Use a configured
Windows Python environment, not Linux Python with a Windows output name.
A successful Wine launch does not replace testing on Windows; follow the
[Windows smoke test](windows-smoke-test.md).

## macOS

```bash
bash packaging/build_macos.sh
```

The script produces `dist/Cubeon.app` and the native architecture's ZIP:
`Cubeon-macOS-arm64.zip` on Apple Silicon, `Cubeon-macOS-x64.zip` on Intel.
It reuses the bundled Cubeon icon and stages the same companion JARs as the
other platforms. `ditto` preserves app-bundle symlinks and executable modes.

CI builds on `macos-15` (arm64) and `macos-15-intel` (x86_64), verifies native
slices in Python and the bundled universal Flet client, verifies the ad hoc
signature, and starts the packaged launcher through its existing first-paint
marker. Both jobs must succeed before the draft release is published.
These are preview distributions with manual upgrades. They are ad hoc signed;
Developer ID signing and Apple notarization require separate credentials.
The website's Mac routes use the newest published preview release. Windows
and Linux downloads retain their existing stable channel.

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
v1.3.38, v1.3.45 and v1.4.20). Stable stamps update English and localized website version labels.
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

Installed Windows x64 copies and user-owned Linux x64 AppImages check for
newer stable releases after startup. Cubeon downloads and verifies the final
installer, then preserves the existing Update now / Later confirmation and
transactional installation with rollback. macOS and Debian packages upgrade
manually. Existing installations need one full upgrade to receive resumable
and incremental downloads.

Transfers pause before and during Minecraft sessions, hosted servers, game
installation and content downloads. Activity-change signals resume them without
polling the UI or blocking Play. Pauses consume neither network retry attempts
nor the 15-minute active transfer budget. Checksum-keyed `.part` files survive
launcher closure and resume via HTTP Range; unexpected ranges are rejected,
and servers ignoring Range restart that transfer safely. Later keeps the
verified candidate and offers installation on the next startup.

Updater state remains under `~/.cubeon_launcher/updates/v1/<target-key>`.
The target lock covers cache pruning and installation preparation. Retain one
previous verified artifact, the current candidate/prefix, its manifest and one
patch/prefix. Installation recovery jobs keep their separate lifecycle.
Windows uses a cached installer as its patch base; Linux verifies its installed
AppImage. Never patch the live executable in place.

`packaging/build_updates.py` generates schema-1, SHA-256-pinned platform manifests
(maximum 64 KiB) and BSDIFF40 patches against the three newest earlier published
stable releases with valid assets. `bsdiff4==1.4.4` is installed only after
freezing and stays out of runtime dependencies. Windows uses per-file LZMA,
rather than solid compression, to retain useful unchanged patch material.
Only patches strictly smaller than 70% of the full artifact are published.
The runtime picks the smallest patch matching a verified local base. Its stdlib
streaming decoder uses 64 KiB blocks, bounded compression/control streams and
an active reconstruction time limit. The reconstructed installer must match
GitHub's full SHA-256, size and executable header. Failed reconstruction falls
back to a resumable full download while idle. An empty manifest permits that
same fallback when no worthwhile patch exists.

CI verifies manifest checksums, target metadata and all referenced uploaded
patches before publication. Linux and Windows packaging run the updater/helper
checks; Windows also executes the real NSIS install, upgrade and rollback
transactions. Version fixtures are independent of release stamps.

The download Worker depends on these release asset names:

| Platform | Release assets |
| --- | --- |
| Linux | `Cubeon-x86_64.AppImage`, `Cubeon-Linux-x86_64-Setup.AppImage`, `Cubeon-Linux-x86_64-Setup.sh`, `cubeon_<version>_amd64.deb` |
| Windows | `Cubeon-Windows-x64-Setup.exe` |
| macOS | `Cubeon-macOS-arm64.zip`, `Cubeon-macOS-x64.zip` |

Renaming an asset requires corresponding changes to the workflow and
`worker/cubeon-downloads.js`.

## Verify the artifact

Launch the packaged app outside the source checkout. Confirm that a window
appears, assets load, the expected feature set is present, and a game can
launch. Check `~/.cubeon_launcher/cubeon.log` for errors.

Record the actual platform tested. A successful build, a headless test, and
a working desktop app are separate results. Continue with the
[release checklist](release-checklist.md) before publishing.
