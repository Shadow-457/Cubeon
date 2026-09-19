# Wave-1 P2P security + lifecycle fixes (2026-09-17)

Scope: `cubeon/friends_service.py` (P2P/session/sync), `cubeon/p2p.py`,
`cubeon/worldgate.py` + focused checks in `tools/test_p2p_batch6.py` and
`tools/test_friends_service.py`. No commits.

## Fixes landed
- P8: STUN attr walk `(-attr_len) % 4` (p2p.py `_parse_xor_mapped_address`).
- P16: explicit per-session `gate_required`/`gate_authorized`; every
  transport-creation/fallback path (`_send_p2p_offer`, `_switch_to_relay`,
  `_run_host_punch`) enforces `_transport_allowed` before creating a transport.
- P17: gate challenge/proof/ok/fail ride the E2EE envelope (`_send_gate` /
  `_open_gate`, AES-GCM authenticated; unsealed or tampered signals are
  refused, fail closed). test_invites/test_p2p_* use FakeClient paths and
  needed no changes; test_friends_service gate tests now seal through the
  wrapper (`gate_build`/`gate_signals`).
- P18: plaintext gate password cleared in `finally` on every outcome.
- P19: sync chunk intake requires an outstanding matching request in the
  CURRENT room, per-chunk size/index/total bounds, bounded pending entries
  (`_MAX_PENDING_ROOMS`), unsolicited entries dropped.
- P20/P21/P22: `_accept_chunk` (strict int seq/total, encoded-size bound,
  base64 validation), `_mod_target` (basename + .jar + realpath containment)
  used by BOTH download and cache-hit paths, `_asset_target` extension
  allowlist + symlink-safe realpath containment + mkstemp write.
- P23: `p2p_answer` validates room, peer, role, handshake phase.
- P1# host HybridSession gets `send_signal`; P2# relay fallback keeps joiner
  "connecting" until `_maybe_finish_join`; P3# offer-prep exceptions close
  transport + room; P4# host callbacks capture session identity; P5#
  call_invite failure fails the session and returns the error; P6# journal
  hooks + cancel()/rollback for ModSync/AssetSync (atomicio journal);
  P7# sync timeouts reach the service via on_error; P9# evicted sync rooms
  closed; P10# sync replies must match the report's current `_room`.

## Verification (all green)
- tools/test_friends_service.py 354/0 (added: sync-chunk hardening, sync
  timeout->session fail, cancel rollback, relay-fallback gate, offer-gate,
  p2p_answer phase, lifecycle edges, sealed-envelope gate helpers)
- tools/test_p2p_batch6.py PASS (added: STUN padding, mod/asset filename +
  chunk-bound checks)
- test_p2p_session/hybrid/relay/transport/transport_stress PASS,
  test_invites 127/0, test_orphan_server 16/0, test_mega_smoke --static 12/0.

## Gotchas for the next agent
- `test_p2p_transport_stress.py` is flaky under load (~1 in 3 fails
  `AssertionError: 119535` on the 120k-byte pattern assert) — pre-existing,
  reproduces on a clean stash; not caused by this wave.
- `_wait_session_closed` reaches into `session._stop`; any test fake
  substituting a transport MUST provide `_stop` (and `metrics`/`close`).
- `_accept_chunk` returns True only on the FINAL chunk; two-chunk fixtures
  must assert False then True.
- Gate signals are sealed now: harnesses that fire gate frames must wrap
  them (see `gate_build`/`gate_signals` in test_friends_service.py).
