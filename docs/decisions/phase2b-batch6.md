# Cubeon Phase 2b - Batch 6

Implemented 2026-08-23.

## Large session recovery/security/diagnostics batch

- Upgraded `cubeon-tcp-over-udp` from v1 to v2.
- Every transport frame now carries a truncated 128-bit HMAC-SHA256 tag keyed by the per-session token. Invalid tags and wrong session tokens are rejected before delivery to the Minecraft TCP bridge.
- Added transport telemetry: average RTT, frame/byte counts, retransmissions, dropped frames, unacked frames, and peer-idle age.
- Added a pre-Minecraft `PunchSession.reconnect()` path for rebuilding a lost NAT mapping without creating a new room/token. Once Minecraft's TCP stream is attached, the launcher deliberately requires a fresh connection instead of pretending TCP can be resumed.
- Added a joiner Retry action when the failure happens before the direct path is ready.
- Added a process-local SHA-256 cache keyed by file size and mtime_ns. This speeds repeated mod/resource/config manifest generation without weakening verification.
- Added live direct P2P RTT information to the Friends session banner.
- Added regression coverage for HMAC tampering, wrong-token rejection, hash-cache invalidation, and metrics.

## Validation

- Python compileall: PASS
- P2P transport loopback: PASS
- P2P transport stress: PASS
- P2P session cleanup: PASS
- Batch 6 security/cache/metrics regression test: PASS
- Worker JS syntax checks: PASS
- Full launcher runtime: not claimed, because this environment may not have the optional `minecraft_launcher_lib`/Flet desktop dependencies installed.
