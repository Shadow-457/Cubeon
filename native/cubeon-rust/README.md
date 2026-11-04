# Cubeon Rust beta

Cubeon maintains this source snapshot of [Horizon](https://github.com/horizon-rust/horizon),
pinned at `33816de710f3c14632ee10be5915fca7240b9754` (Minecraft Java Edition 26.3).
The original MIT copyright and license remain in `LICENSE`; patched library
licenses and attributions remain in `THIRD_PARTY_NOTICES.md` and `third_party/`.

The workspace contains the client's local dependency closure and original Java
exporter sources. The upstream launcher and hosted server applications are excluded.
Packages, internal namespaces, bundled translations, runtime icons and UI palettes
use Cubeon branding. Cubeon owns the binaries, patches and releases.

Cubeon's changes remove account/session loading, chat credentials, account HTTP,
heartbeat and telemetry collection, default server injection and world sharing.
Cosmetics services are disabled. Local identity is supplied by Cubeon and applied
only to the owner's in-memory connection; remote offline servers keep their own
standard identity rules. Original protocol and gameplay parity tests remain.
Optional game systems intertwined with rendering retain passive types, but no
upstream launcher, release, renewal or service is required at runtime.

Build using `tools/build_rust_engine.py` from the Cubeon checkout, with JDK 25 and
verified 26.3 client/server inputs. The tool packages original compiled exporter
classes, their source fingerprints, the two executables and license notices.
It never packages Minecraft jars, textures, sounds or generated game resources.
Players obtain those from official Mojang downloads or their own cache and
prepare them locally. Java 25 is needed for preparation, not gameplay.

The launcher uses `build/rust-engine/<platform>/` during source development and
Cubeon's own pinned GitHub release manifest for distributed builds. Installation,
worlds, settings and logs live below Cubeon's private `rust/` folder, separately
from Java instance staging. Linux and Windows x64 are the initial build targets.
1000 FPS is a development target, not a measured performance guarantee.
