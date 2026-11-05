# Cubeon Rust beta integration

Status: implemented locally, 2026-11-05. The Linux runtime and original resource
exporters are built and packaged. Native terrain rendering, save/reopen and
persistent local identity are verified. Public release, Windows execution and
FPS benchmarking remain pending.

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

Native appearance reads Cubeon's CSL-compatible LocalSkin mirrors first, then
public Cubeon skins/capes, with explicit slim models and transparent hidden capes.
It honors the launcher's skin-management preference. This implements the native
appearance loader; it does not install or execute the Java CustomSkinLoader JAR.

The native Cubeon Client opens with **Right Shift** or the pause-menu button.
It provides HUD overlays, a drag/resize editor, auto sprint, enemy health,
**C** zoom, **Left Alt** freelook and a **B** emote wheel. Controls wait until
world loading finishes. HUD preferences use `config/cubeon-client-hud.json`.
Friends, messages and emotes use Cubeon's authenticated launcher loopback bridge,
and the existing native sharing screen remains available. The launcher client
preference controls the companion. Full cosmetic geometry and camera motion blur
remain outside the native implementation.

The UI labels **1000 FPS as a target**. The smoke captures establish working
native rendering, not measured FPS or a guarantee for any computer.

## Source and ownership

`native/cubeon-rust/` contains the MIT Horizon source pinned to
`33816de710f3c14632ee10be5915fca7240b9754`, its required local crate closure,
patched third-party dependencies, research pins and original Java exporter
sources. The original MIT notice and third-party notices are retained.
Horizon's separate launcher and hosted applications are excluded.

Cubeon builds `cubeon-rust` and `cubeon-rust-prepare` from this tree. Installation
and gameplay do not consult Horizon's releases, account services, relay or mod
registry. Internal package/type names remain where needed to preserve gameplay
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
JAR against its Mojang SHA-1 before downloading. First preparation requires
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
- `instances/26.3/`: isolated native worlds, settings and screenshots.
- `instance.json`: installation/discovery marker.

Removing the Rust installation clears its marker and preserves worlds/settings.
Native folders do not adopt shared Java worlds or stage Java mod JARs.
Cubeon's stable UUID applies only to its local owner connection, including
after a name change; remote offline server and guest identity rules are retained.

## Building and distribution

`tools/fetch_rust_build_inputs.py` obtains verified official build inputs.
`tools/build_rust_engine.py` builds both native binaries and packages original
compiled exporter classes, source fingerprints, research lock and licenses.
It writes per-file SHA-256 metadata, a platform ZIP and an archive-size/digest
release manifest under `build/rust-engine/`.

Source checkouts use the verified local platform bundle. A rebuilt local bundle
replaces an earlier bundle with the same beta identifier when its hashes differ.
Distributed builds use only Cubeon's pinned release assets, with no Horizon
fallback. The current release destination is
`Shadow-457/Cubeon`, tag `rust-26.3-beta.1`; it is **not published yet**.

`.github/workflows/rust-beta.yml` is manually triggered, builds Linux/Windows
x64 artifacts and merges verified platform manifests. It does not publish.
The Linux package exists locally; Windows CI/execution requires a later run.

## Verification and remaining work

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

These resolve the earlier dependency, UUID persistence and exporter-packaging
prototype questions. Interactive gameplay coverage and Windows execution remain
limited; the smoke tests do not certify every inherited game feature.
Public release and measured FPS remain pending. Benchmarking must use matched
worlds, graphics, resolution, distances, camera movement, VSync and frame limits.

## Source references

- [Pinned MIT license](https://github.com/horizon-rust/horizon/blob/33816de710f3c14632ee10be5915fca7240b9754/LICENSE).
- [Preparation and launch interface](https://github.com/horizon-rust/horizon/blob/33816de710f3c14632ee10be5915fca7240b9754/docs/api/launch.md).
- [Original account boundary](https://github.com/horizon-rust/horizon/blob/33816de710f3c14632ee10be5915fca7240b9754/docs/microsoft-account.md#the-owner-gate).
- [Resource preparer dependencies](https://github.com/horizon-rust/horizon/blob/33816de710f3c14632ee10be5915fca7240b9754/crates/horizon-prepare/Cargo.toml).
