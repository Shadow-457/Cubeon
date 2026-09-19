# 2026-09-12 - Worldgate: the optional password on a P2P LAN world

## Ask
"when the user opens local lan and cubeon client is on, cubeon client shows a
password entering thing after they open it, then they get a minekube free
address; the friend who joins needs to type the pass. Cubeon tries P2P first
and only uses Minekube if P2P fails."

## What existed already
watch_for_lan_port (LAN detect -> invite), HybridSession (UDP punch with
relay fallback), _switch_to_minekube (host's fallback to their public
connect-spigot server), gate.py (passwords the DEDICATED Paper server only).
The gap: a LAN world handed its connection target to anyone who accepted.

## Design (user confirmed: password is OPTIONAL, Skip allowed)
- New `cubeon/worldgate.py`: in-memory only salt+PBKDF2 hash (same constants
  as CubeonGate). Nothing on disk, joiner never stores the password past one
  proof.
- The password gates the OFFER, not the invite: host flow
  hosting_wait_port -> gate_wait (mod's password prompt; empty box = skip) ->
  ringing_out -> verifying (challenge) -> connected. The p2p_offer carries
  the LAN port and relay session token, so sending it to an unproven peer
  would make the gate decorative - it is withheld until gate_proof verifies.
- Protocol over the E2EE signal channel: gate_challenge {nonce, salt,
  iterations} -> gate_proof {HMAC(PBKDF2(pw,salt), nonce)} -> gate_ok, or
  gate_fail {left, FRESH nonce, salt} so a retype needs no extra round trip.
  3 wrong proofs close the room; a 60s watchdog closes an unanswered one.
- Minekube fallback untouched: it happens after connected, which is already
  past the gate. (connect-spigot can only run on the dedicated Paper server,
  not inside a vanilla LAN world - that constraint is unchanged; the gate on
  that path is the address handoff, exactly as the plan said.)
- Bridge: Session gained gate_wait/verifying/password_needed states,
  needsGateChoice(), new headlines/details; Bridge.setWorldGate/sendJoinPassword
  POST /worldgate + /joinpassword (empty password string = Skip).
- Mod screen: the worldgate decision owns the footer on every tab (masked
  input was rejected: EditBox masking API differs per era - setFormatter vs
  addFormatter - and the mod compiles against the smallest stable slice).

## Verification
- tools/test_friends_service.py 240/240 (+27): the whole protocol against
  FakeClient - arming, invite-after-decision, challenge contents, wrong-proof
  re-challenge with a fresh nonce, lockout closing the room, offer release on
  the right proof, joiner proof bytes pinned exactly, stale-password refuse,
  blank refuse, gate digest joining.
- mod_bridge 119, mod_matrix 68, friends 48, ui_smoke 112, production 13,
  mod_compile clean. Both jar brackets rebuilt + redeployed to cache and
  assets/jars.

## Note for next agent
- The debug log in _send_p2p_offer's except (`log.debug ... exc_info=True`)
  is load-bearing for protocol debugging; keep it.
- test_no_flet-style headless invariants still hold: worldgate.py imports no
  GUI, no requests, nothing outside stdlib + cubeon.gate constants.
- The mod's password box is NOT masked (see above). If masking ever becomes
  a requirement it needs a per-era formatter decision, deliberately.
