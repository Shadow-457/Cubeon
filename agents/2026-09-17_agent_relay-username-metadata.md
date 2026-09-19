# 2026-09-17 — Relay username metadata (plan step 2)

## What I did
Implemented plan step 2 (`Publish separate username metadata`) strictly inside
my assignment: `worker/cubeon-friends.js`, `cubeon/friends.py`,
`tools/test_friends.py`, plus two new focused worker tests.

- **Worker**: `names.minecraft_username` nullable TEXT column, added via a
  PRAGMA-guarded ALTER (repeatable, no unique index — duplicates legal).
  `T_METADATA` frame: validates case-preserving `[A-Za-z0-9_]{3,16}`, writes
  ONLY that column (`UPDATE names SET minecraft_username=?` — handles/UIDs
  immutable), skips unchanged writes, and fans out `{name, uid,
  minecraft_username}` to self + friends + **pending-request counterparts** +
  group co-members. Hello accepts an optional username (replay), hello_ok /
  presence / `/name/` / `/uid/` carry full identity; `sendTo` enriches
  identity-bearing frames with `from_/to_/peer_uid` + `..._minecraft_username`.
  Roster keeps legacy string arrays and adds `requests_in_details`,
  `requests_out_details` (presence objects) and `member_details` on groups.
- **Client (`cubeon/friends.py`)**: `minecraft_username(value) -> valid str or
  ''` (case-preserving, no reserved-name restriction); `FriendsClient.
  set_minecraft_username()` — nonblocking (background thread, lock-guarded,
  dedupes, pending-resend while a publish is in flight), hello carries it for
  reconnect replay. Roster handler caches `peer_metadata` keyed by canonical
  handle (`{uid, minecraft_username}` only when known) and merges T_METADATA
  events BEFORE callbacks; invalid/missing fields can never clear last-known.
  The roster cache is now written via `atomicio.write_json` — it was a direct
  `open(path, "w")`, the crash-corruption class the module map forbids.

## How I verified
- `tools/test_friends.py`: 89 passed / 0 failed (new sections: username
  validation helper, T_METADATA send/dedupe/replay, roster peer_metadata
  caching incl. duplicate usernames distinct by handle, older-payload
  tolerance, and worker parity pins for the new behavior).
- `worker/test-friends-metadata.mjs` (new, node:test): hello persists +
  returns metadata with stable UID; invalid values ignored; unchanged skip;
  change echoes full identity; 50 distinct usernames on one account; pending-
  request counterpart notified; repeat Hub construction idempotent.
- `worker/test-friends-sql.mjs` (new): real SQLite semantics — triple
  migration, nullable column, duplicate usernames coexist, NULL rows legal,
  routing identity untouched by metadata edits.
- `node worker/test-worker.mjs` still ALL PASSED; `test_mega_smoke --static`
  12/0; `test_production.py` 50/0 across 5 runs.

## Contracts other agents can build on
- `cubeon.friends.minecraft_username(value)` (the service agent's edits call it).
- `client.roster["peer_metadata"]` keyed canonical handle.
- T_METADATA event carries `{t, name, uid, minecraft_username}`.

## Caveats
- `tools/test_friends_service.py` is 287/7 — every failure is in
  service-agent-owned surfaces (event-feed wording, REST fallback for
  unclaimed names, P2P join text, DM status line); coordination posted on the
  board. Not my files.
- Not deployed (explicit release step, owned by main), no commits made.
