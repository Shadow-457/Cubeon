# Cubeon Friends API

The realtime backend for the **Friends tab**: unique Cubeon names, presence
(online/offline + which game version), direct chat, groups, and voice-call
signalling - all over one WebSocket.

- **Deployed 2026-09-14** (wrangler-friends.toml). The launcher defaults to
  `https://cubeon-friends.hamza-457-shahbaz.workers.dev` - same account as the
  other two. Set `CUBEON_FRIENDS_API` to point elsewhere while testing.
- **Launcher side:** `cubeon/friends.py` (identity + client),
  `cubeon/friends_service.py` (headless owner of the callbacks + P2P state),
  `cubeon/local_api.py` (the bridge the in-game `mod/` UI talks to),
  `cubeon/voice.py` (optional audio). There is no Friends tab - the UI is the
  in-game mod.
- **Tests:** `python3 tools/test_friends.py` - pure client logic **and** format
  parity with this Worker (message types, name regex, reserved names).
  `python3 tools/test_friends_service.py` - the service and the bridge, plus a
  contract check that the launcher serves every endpoint the mod calls.

## Why It's a Durable Object, Not KV

Presence is a heartbeat: every online friend's status changes several times a
session. On KV that's a **write per change**, and the free tier allows only
~1000 writes/day *globally* - a handful of active users would exhaust it by
lunch. A **Durable Object** holds every live WebSocket in one place, derives
presence straight from the open sockets (no writes at all), and keeps the friend
graph + recent chat in its own SQLite DB, which is **not** write-metered like
KV. One DO instance (`idFromName("global")`) is the whole hub.

Two things make this fit the free tier, both already in the code:

- **SQLite storage class.** The `new_sqlite_classes` migration in
  `wrangler-friends.toml` is what puts the DO on the free-tier storage backend.
  Without it `ctx.storage.sql` doesn't exist and every query throws.
- **WebSocket Hibernation.** `ctx.acceptWebSocket()` lets the DO evict from
  memory while sockets stay open, so idle connections don't rack up duration
  billing. Per-socket identity survives hibernation via `serializeAttachment`,
  which is also where presence is read back from.

## Deploy

This one **does** need `wrangler` - the dashboard editor can't apply a Durable
Object migration. Same Cloudflare account as the other Workers.

```
cd worker
npx wrangler deploy -c wrangler-friends.toml
```

1. **Check it.** The printed URL + `/health` returns `cubeon-friends ok`.
2. **Match the URL.** It must equal `DEFAULT_API_ROOT` in `cubeon/friends.py`
   (or override with `CUBEON_FRIENDS_API`).
3. **Local run:** `npx wrangler dev -c wrangler-friends.toml`, then
   `export CUBEON_FRIENDS_API=http://127.0.0.1:8787` before starting the
   launcher.

Nothing is stored server-side that identifies a person: a name maps to the
**SHA-256 of a client-generated secret**, never the secret itself - the same
capability-secret model as invites. Whoever holds the secret owns the name;
there is no password to leak because there is no account.

## Format Parity Is Enforced by a Test

`cubeon/friends.py` and `cubeon-friends.js` have to agree on three things or the
launcher talks to the server in a dialect it rejects - and only in production,
since nothing local would notice: the **message-type strings** (27 of them), the
**name regex** (`[A-Za-z0-9_]{3,16}`), and the **reserved names**.
`tools/test_friends.py` reads this Worker's source and asserts all three match.

## What's Still Missing

The protocol, client, and UI are built and the offline tests pass. Not yet
verified against a **live deploy**: the DO has never run on real Cloudflare, so
the WebSocket handshake, hibernation behaviour, and SQLite queries are only
proven by the JS parser and the parity test. Voice **audio** is an optional
dependency (`sounddevice` + `numpy`); without it, calls still ring, connect, and
carry text - there's just no sound.