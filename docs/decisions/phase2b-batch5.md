# Cubeon Phase 2b - Batch 5

Implemented 2026-08-23.

## Large P2P session sync batch

- Added a second pre-flight manifest for shared session assets.
- Resource packs are synchronized automatically when the joiner is missing or has a different SHA-256 copy.
- Allowlisted loader configuration files under `.minecraft/config` are synchronized as part of the P2P session.
- Existing local resource/config files are backed up before replacement and restored when the session ends.
- Peer-supplied asset files are removed on teardown; global mod cache content remains untouched.
- Added SHA-256 verification, per-file 32 MB limit, aggregate 128 MB limit, 1000-file limit, and a 256 KB manifest limit.
- Asset chunks are bounded and reassembled out of order, with a 120-second inactivity timeout.
- P2P joining now waits for three prerequisites: direct transport, mod sync, and shared-asset sync.
- Asset requests are handled asynchronously so the Friends WebSocket thread remains responsive.
- Session bookkeeping now records asset additions and backups alongside mod links/disabled mods.

## Validation

- Python compileall: PASS
- Worker JavaScript syntax checks: PASS
- P2P transport loopback: PASS
- P2P transport stress: PASS
- P2P session cleanup: PASS
- Isolated P2P asset sync test with resourcepack + config files: PASS

The full launcher suite still cannot be runtime-verified in this environment when `minecraft_launcher_lib` is unavailable.
