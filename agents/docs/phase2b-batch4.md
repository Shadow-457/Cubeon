# Cubeon Phase 2b - Batch 4

Implemented 2026-08-23.

## Transport hardening

- Added a bounded retransmission window and retry ceiling to the custom
  `cubeon-tcp-over-udp-v2` transport.
- Added heartbeat PING/ACK traffic and a 30-second peer-idle timeout so a dead
  peer does not leave a Minecraft client stuck forever.
- Added bounded receive buffering and a failure state for overflow.
- Fixed a TCP-to-UDP data-loss bug where TCP bytes could be read while the UDP
  send window was full and then discarded.
- Moved local TCP delivery and TCP outbound pumping off the UDP transport loop,
  so TCP backpressure cannot stall ACKs, heartbeats, or retransmission work.
- Added graceful FIN signalling and clearer transport failure reasons.

## Session lifecycle hardening

- Added stale P2P session-state cleanup for launcher crashes/forced exits.
- Cleanup restores temporarily disabled local mods through the existing guarded
  teardown path and never deletes global cache content.
- Registered best-effort process-exit cleanup.
- Added a UI transport watchdog so a session that dies after becoming
  connected is surfaced as a failed P2P session instead of remaining visually
  connected.

## Mod sync hardening

- Added a bounded mod-sync timeout so unanswered peer requests cannot leave
  the join flow stuck indefinitely.
- Progress timestamps are refreshed as mod chunks arrive.
- Existing SHA-256 verification and cache-first linking remain unchanged.

## Validation

- Python compileall: PASS
- Worker JavaScript syntax checks: PASS
- P2P transport loopback: PASS
- P2P session cleanup: PASS
- P2P 180 KB bidirectional transport stress test: PASS
- Broader launcher tests requiring `minecraft_launcher_lib` could not run in
  this environment because that dependency is not installed here.
