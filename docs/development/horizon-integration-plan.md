# Cubeon Rust beta integration

Status updated 2026-11-21. The Linux runtime and original resource exporters
are built and packaged. Native terrain rendering, save/reopen and persistent
local identity are verified on Linux. Linux and Windows runtime packages are
published as `rust-26.3-beta.2`; Windows gameplay and FPS benchmarking remain
unverified.

## Product behavior

Use the existing Play Instances/version panel:
**New instance → engine/mod loader → Rust · Beta → 26.3 → icon → Download & Play**.
Rust has exactly one version, including when the Java catalogue is unavailable.
The installed instance is `cubeon-rust-26.3`, labeled Rust · Beta. There is no
additional sidebar destination.

Selecting Rust disables Servers navigation and hosting setup/start/restart.
Selecting Java restores those controls. A Java server already running remains
running and retains its stop path. Native singleplayer keeps the integrated
world simulation that gameplay needs.

Rust uses Cubeon's local name and stable UUID. Account/session activation,
Microsoft sign-in, premium-session renewal, upstream chat credentials, telemetry,
default server injection and upstream hosted cosmetics are disabled. This
beta retains the essential game engine, renderer, input, audio and local storage.
Java mod JARs cannot run in the native engine.

Select the Rust instance on Play and open **Mods** to browse Horizon content
mods inside the launcher. Search by name or paste a `playhorizon.dev/mods/…`
link, open details and select **Install** or a specific release under
**Versions**. **Import mods** accepts local `.hmod` packages. **Installed**
provides enable/disable and remove controls; changes apply on the next launch.
New mods start enabled and updates preserve an existing disabled choice.

This integration supports API 0.2 content mods for 26.3. Native-code mods and
retired WebAssembly mods remain unavailable, with their compatibility reason.
It does not upgrade the engine. Some content packages supply assets for a
separate native mod; their project description explains that requirement.

Native appearance reads Cubeon's CSL-compatible LocalSkin mirrors first, then
public Cubeon skins/capes, with explicit slim models and transparent hidden capes.
It honors the launcher's skin-management preference. This implements the native
appearance loader; it does not install or execute the Java CustomSkinLoader JAR.

The native Cubeon Client opens with **K** or the pause-menu button; **Right Shift**
remains an alias while the menu binding is unchanged.
It provides HUD overlays, a drag/resize editor, auto sprint, enemy health,
**C** zoom, **Left Alt** freelook and a **B** emote wheel. Controls wait until
world loading finishes. HUD preferences use `config/cubeon-client-hud.json`.
Friends, messages and emotes use Cubeon's authenticated launcher loopback bridge,
and the existing native sharing screen remains available. The launcher client
preference controls the companion. Camera motion blur uses the current world image
before the HUD. Full cosmetic geometry remains outside the native implementation.

The UI labels **1000 FPS as a target**. The smoke captures establish working
native rendering, not measured FPS or a guarantee for any computer.

## Source and ownership

`native/cubeon-rust/` contains the MIT Horizon source pinned to
`33816de710f3c14632ee10be5915fca7240b9754`, its required local crate closure,
patched third-party dependencies, research pins and original Java exporter
sources. The original MIT notice and third-party notices are retained.
Horizon's separate launcher and hosted applications are excluded.

Cubeon builds `cubeon-rust` and `cubeon-rust-prepare` from this tree. Engine
acquisition uses Cubeon's pinned bundles. Optional content-mod discovery reads
Horizon's public registry through the launcher; it does not change the runtime
pin or use Horizon accounts or relay services. Internal package/type names remain where needed to preserve gameplay
and make future source patches reviewable. Intertwined optional systems retain
passive types; their service entry points are disabled.

Cubeon maintains engine fixes, platform builds, exporters and compatibility.
Future upstream patches may be reviewed manually; they are optional source
inputs. Rust libraries/toolchains and Minecraft resources retain their own
dependencies and licenses.

## Asset acquisition and preparation

| Material | Source |
| --- | --- |
| Native executables, original compiled exporters, fingerprints and notices | Verified local Cubeon bundle or Cubeon's pinned GitHub release |
| Minecraft 26.3 client/server JARs, libraries and asset objects | Verified local cache, otherwise official Mojang manifest URLs |
| Prepared engine textures, sounds and world data | Generated locally on the player's machine |

Runtime archives exclude Minecraft JARs, textures, sounds and generated data.
The MIT engine license does not grant rights to publish Minecraft assets.

The adapter reuses Cubeon's official version installer and verifies the server
JAR against its Mojang SHA-1 before downloading. It compares the installed
version JSON's raw SHA-1 with the bundled runtime's `research-lock.json`.
Accepted local metadata is reused. When Mojang republishes the version JSON
or another launcher rewrites it, the adapter downloads the runtime's pinned
original from Mojang, verifies its SHA-1 and caches it separately under Rust's
`inputs/`. The preparer receives that file through `--version-json`, while
libraries and asset objects still come from the shared install. The shared
Java version JSON stays current, and a verified pinned cache needs no download.

The Rust artifact CI uses `tools/fetch_rust_build_inputs.py` to seed its isolated
version directory with the verified source-pinned manifest before installing
libraries and assets. Accepted cached manifests are reused, and the manifest
and server checksums remain checked after installation.

First preparation requires
**exact Java 25** for the pinned exporters. It checks configured Java, PATH,
JAVA_HOME, managed Java 25 and bounded conventional local JDK directories,
including `~/jdks`, `~/.jdks` and SDKMAN. It probes the actual executable,
resolves symlinks to derive the correct Java home, and downloads a managed
runtime only when no compatible local JVM is found. Normal Java instance
selection still uses its existing minimum-version policy.

Java download phases have their own progress scale and explicitly identify Rust
resource preparation. Complete prepared resources are checked and cached by
Cubeon engine build; gameplay uses the native executable without Java.

## Launcher integration and recovery

`cubeon/rust_engine.py` owns native runtime verification, safe archive extraction,
official resource acquisition, preparation, instance discovery and launch.
Native routing in `paths.py`, `instances.py`, `versions.py`, `launch.py` and
`main.py` happens before Java profile validation, preflight, loader installation,
JAR staging and legacy world adoption.

The existing install/launch/run claims, cancellation, Play/Quit, detached process
watchdog, logs, playtime and exit callbacks are reused. Cancelling preparation
also terminates its exporter process tree. Runtime/resource replacements stage
and validate new files before swapping, retaining the previous files on failure.

Files live below `CUBEON_HOME/rust/`:

- `builds/<build>/<platform>/`: verified engine/exporter bundle.
- `resources/<build>/`: locally prepared resources.
- `inputs/server-26.3.jar`: verified official server input.
- `inputs/manifest-26.3-<sha1>.json`: verified version metadata pinned by the runtime.
- `instances/26.3/`: isolated native worlds, settings and screenshots.
- `instances/26.3/cubeon-mods/<id>.hmod`: adapted Horizon/local content packages.
- `instances/26.3/cubeon-mods.txt`: native mod enable settings and key bindings.
- `instance.json`: installation/discovery marker.

Removing the Rust installation clears its marker and preserves worlds/settings.
Native folders do not adopt shared Java worlds or stage Java mod JARs.
Cubeon's stable UUID applies only to its local owner connection, including
after a name change; remote offline server and guest identity rules are retained.

`cubeon/rust_mods.py` verifies original package sizes, SHA-256 and optional
minisign signatures, then adapts Horizon manifest/declaration names for the
fork. Artwork is preserved. Downloads reuse the global mod cache; adapted
instance files are regular ZIPs because native folders refuse symbolic links.
Failed publication restores the package, source receipt and enable settings.
See [Mod catalogue](../architecture/mod-catalogue.md#horizon-content-mods-for-rust)
for the API, content fence, revocations and update contracts.

## Building and distribution

`tools/fetch_rust_build_inputs.py` obtains verified official build inputs.
`tools/build_rust_engine.py` builds both native binaries and packages original
compiled exporter classes, source fingerprints, research lock and licenses.
It writes per-file SHA-256 metadata, a platform ZIP and an archive-size/digest
release manifest under `build/rust-engine/`, recording `build_profile` in both
runtime and release metadata. Shipped builds use Cargo's `release` profile
(thin LTO, one codegen unit); `fast` is for iteration.

Source checkouts use the verified local platform bundle. At install or normal
Play, a rebuilt local bundle replaces an earlier bundle with the same beta
identifier when its hashes differ. Play only refreshes verified local artifacts;
it never downloads, and invalid local bundles preserve the installed runtime.
Worlds and settings are untouched.
Distributed builds use only Cubeon's pinned release assets, with no Horizon
fallback. The current release destination is
`Shadow-457/Cubeon`, tag `rust-26.3-beta.2`, published on 2026-11-09 from
CI run `42564833017` at `7490365f`. This runtime uses the production `release`
profile. Fresh profiles start Balanced, VSync off, 240 FPS and simulation
distance 8; existing settings are preserved. The earlier `rust-26.3-beta.1`
runtime used `fast`, VSync on, a 120 FPS cap and simulation distance 12.
Source edits and local rebuilds do not update the installed public release.

`.github/workflows/rust-beta.yml` runs on relevant main pushes or manual dispatch, builds Linux/Windows
x64 artifacts and merges verified platform manifests. It does not publish.
The published Linux/Windows artifacts passed CI and archive verification;
Windows gameplay remains unverified.

## Native Cubeon Client

The native client shares Fabric's menu artwork, HUD settings and client themes.
K opens its searchable feature menu and HUD editor, G opens launcher-backed
friends/chat, B opens the emote wheel, C holds zoom and Left Alt holds freelook.
These inputs can be changed in the native Controls settings; Right Shift remains
an alias for the default menu binding. Messages and friend actions wait for exact
launcher results, preserving drafts when a send fails or the account changes.
Camera motion blur uses the current world image before the HUD. Enemy health
shows a heart and rounded-up heart count beneath visible enemy names.

In-game wardrobe and additional cosmetic rendering are excluded from this change.
GUI verification of this revision is intentionally left to the user. A source push
builds CI artifacts; it does not replace the separately published Rust runtime.
The local source launcher can use a verified same-beta bundle built from this checkout.

## Verification and remaining work

The checks below include earlier native releases and content-mod integration.
This client revision has non-GUI checks only; its interactive controls and rendering
remain for the user to verify.

Completed checks:

- Focused launcher tests cover native path isolation, hashes/archive safety,
  cancellation, Java bypass, cached server/local Java reuse, same-beta replacement,
  26.3-only picker behavior and Server capability restoration.
- Real bundle installation, preparer validation, instance discovery and launch
  command generation passed in an isolated launcher home.
- Native preparer tests passed, including Java compatibility selection.
- The actual compiled profile API rejects account activation/discovery/join and
  preserves the owner's UUID across local name changes.
- An isolated Linux Vulkan game rendered terrain, saved and reopened the world
  with the same UUID after a name change, and injected no default server list.
- Offscreen native controls exercised the companion menus, saved auto sprint,
  HUD editor, zoom, freelook and emote wheel. Compiled worker checks verified
  local/public appearance, slim models, cape hiding, opt-out and authenticated
  friends/message/emote bridge behavior. No new captures were taken.
- Native Flet captures verified the existing picker flow and Server
  unavailability/restoration. Cubeon's default mega smoke gate passed.
- Horizon's live API and a verified Additional Lights 3.1.4 download passed
  the launcher adapter. The installed Linux beta.2 loaded its custom registries,
  rendered terrain and saved/reopened an isolated world with the content mod.

These resolve the earlier dependency, UUID persistence and exporter-packaging
prototype questions. Interactive gameplay coverage and Windows execution remain
limited; the smoke tests do not certify every inherited game feature.
Measured FPS comparisons remain pending. Benchmarking must use matched
worlds, graphics, resolution, distances, camera movement, VSync and frame limits.

## Source references

- [Pinned MIT license](https://github.com/horizon-rust/horizon/blob/33816de710f3c14632ee10be5915fca7240b9754/LICENSE).
- [Preparation and launch interface](https://github.com/horizon-rust/horizon/blob/33816de710f3c14632ee10be5915fca7240b9754/docs/api/launch.md).
- [Original account boundary](https://github.com/horizon-rust/horizon/blob/33816de710f3c14632ee10be5915fca7240b9754/docs/microsoft-account.md#the-owner-gate).
- [Resource preparer dependencies](https://github.com/horizon-rust/horizon/blob/33816de710f3c14632ee10be5915fca7240b9754/crates/horizon-prepare/Cargo.toml).
