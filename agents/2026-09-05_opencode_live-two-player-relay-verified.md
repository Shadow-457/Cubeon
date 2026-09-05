# 2026-09-05 — Live two-player relay test: friends stack verified end-to-end

## What the user reported

"the friend thing doesnt work quite good alot glitches bugs" — no specifics.
The user couldn't say WHAT was broken; they'd lost trust in the feature.

## What I did

Wrote a live two-player harness (`/tmp/opencode/live_two_players.py`, not in
the repo) that spawns two subprocesses, each a full launcher-side stack
(identity + FriendsClient + FriendsService with .start()), sandboxed HOME
each, both talking to the REAL relay at
cubeon-friends.hamza-457-shahbaz.workers.dev. Assertions go through the same
surface the in-game mod polls: roster_payload / chat_payload / events_since.

## Findings

1. **The only real bug: the deployed Worker was stale.** The live relay
   didn't answer typo'd adds with T_SYSTEM "No Cubeon user named X." (repo
   code had it; deployment didn't). Fixed by `cd worker && npx wrangler
   deploy -c wrangler-friends.toml` — version 6b7ac883, deployed from this
   machine. This was open item #1 in the module map ("relay deployment
   pipeline") manifesting in the wild.

2. **Everything else passed against production**, twice:
   connect, add, request visible to recipient, accept, mutual friend_added,
   presence both ways, E2EE chat both directions (verified decrypted
   plaintext on both ends), typo'd-name human answer via /events.

3. **The user's morning crashes** (~03:43, 03:45 in cubeon.log) were the
   OLD AppImage missing flet icons.json — current build contains it. No
   action needed beyond "use the new build".

## Gotchas learned (test-harness level, but will bite again)

- `events_since(-1)` means "cursor only, no events" (first-sync semantics).
  Polling with after=-1 forever shows an EMPTY feed even while events land.
  The mod always passes the last cursor — a naive test must too.
- `svc.start()` REPLACES client handlers (one handler per event, `on()`
  overwrites). To observe events AND run the service, assert through the
  service's poll surface, not through extra client.on() registrations.
- The real launcher creates identity BEFORE svc.start(); reversing the
  order skips the E2EE publish thread and chat fails with "hasn't set up
  encrypted chat yet" — order matters and the failure mode is confusing.
- Sandbox HOME needs PYTHONUSERBASE=~/.local preserved or user-site
  packages (websocket-client etc.) vanish and imports crash.

## Open items this closes / changes

- Module map open item #1 (relay lags repo): the lag is now ZERO as of
  today's deploy, but the pipeline issue stands — every Worker change needs
  a manual `npx wrangler deploy -c wrangler-friends.toml`.
- Open item #2 (live two-launcher end-to-end): the LAUNCHER↔RELAY↔LAUNCHER
  half is now proven live. The remaining unproven hop is the in-game MOD
  talking to its own launcher's local bridge during a real game session.

## Verification

- /tmp/opencode/live_two_players.py: 10/11 (the 1 "failure" is the
  harness's own after=-1 bug, disproven by the direct probe: events
  cursor 2 contains both the "Friend request sent" and the relay's
  "No Cubeon user named" answer).
- Raw WS probe: hello_ok + T_SYSTEM reply for unknown add, live.
- curl /name/<known> → 200 {"name","online"}; unknown → 404.
