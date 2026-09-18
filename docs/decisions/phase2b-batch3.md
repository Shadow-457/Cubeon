# Cubeon Phase 2b - Batch 3

Implemented 2026-08-23. This batch hardens the true P2P world path and fixes a critical transport mismatch from the earlier prototype.

## Features

### 1. Real Minecraft TCP transport over the punched UDP path
Minecraft Java multiplayer traffic is TCP. The previous prototype only forwarded UDP datagrams after punching, which could not actually carry a Java LAN world. Cubeon now keeps UDP NAT traversal for discovery/hole punching, then carries Minecraft TCP bytes through a small reliable ordered transport over the punched UDP socket.

The transport provides:
- ordered delivery and cumulative acknowledgements;
- packet fragmentation/reassembly;
- retransmission of lost packets;
- session-token validation on every transport frame;
- a localhost TCP listener on the joiner;
- a localhost TCP connection to the host's actual LAN server port.

### 2. Versioned transport handshake
P2P offers now advertise `cubeon-tcp-over-udp-v1` and a per-session token. Joiners reject incompatible transport versions instead of attempting an unusable connection.

### 3. P2P lifecycle hardening
- Host sessions now enter a real `Connected` state after the transport handshake, rather than stopping at the UDP punch.
- Host Minecraft exit closes the P2P transport and updates the UI.
- Join failures close sockets, remove session-only mod links, and end the room.
- The UI now has explicit `Launching` and `Ended` states.
- Failed sessions no longer leave the local transport or temporary mod links running.

## Validation

- Python compileall: PASS
- Worker JavaScript syntax checks: PASS
- P2P TCP-over-UDP loopback integration test: PASS
- Existing Worker test suite: PASS

### 4. Host-profile compatibility and extra-mod isolation
The joiner now rejects a mismatched Minecraft version/loader profile before starting a session. Extra enabled mods that are not present in the host's mod hash set are temporarily renamed to `.jar.disabled`, then restored on teardown. Host-provided/cache-resolved mods remain session-owned and are removed on leave.
