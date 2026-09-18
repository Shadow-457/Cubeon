# Cubeon Invite API

Turns `bluefox-1234.gl.joinmc.link:52341` into `CUBE-7F4K-9QMN`.

- **Deployed 2026-09-14** (wrangler-invites.toml, KV namespace INVITES). The launcher defaults to
  `https://cubeon-invites.hamza-457-shahbaz.workers.dev` - same account as the
  skins Worker. Nothing calls it until the host UI lands.
- **Launcher side:** `cubeon/invites.py`
- **Tests:** `node worker/test-invites.mjs` and `python3 tools/test_invites.py`

## Why a Code and Not Just the Address

Three reasons, in order of how much they matter:

1. **A tunnel address is unsayable.** The pitch is "send a link"; a random
   subdomain with a five-digit port is something you can only copy-paste.
2. **playit's free tier changes the port on reconnect.** The code stays put, so
   a friend group saves it once and it keeps working.
3. **The provider stays invisible.** Swapping playit for a VPS later changes
   only a value in KV - no user ever learns what playit is.

## Routes

| Route | Auth | What it does |
|-------|------|--------------|
| `PUT /i/<CODE>` | `Authorization: Bearer <secret>` | claim a free code, or repoint one you own |
| `GET /i/<CODE>` | none | resolve to `host:port` (+ version, loader, age) |
| `DELETE /i/<CODE>` | `Authorization: Bearer <secret>` | unpublish when the host stops |
| `GET /health` | none | plain-text OK |

Codes are case-insensitive; the launcher also strips dashes, spaces and a pasted
URL prefix before sending, so `cube7f4k9qmn` works.

## Ownership Without Accounts

Skin uploads (above) answer *"who may write this player's skin?"* with
UUID ownership + trust-on-first-use. Invite codes have it
even easier: **a freshly minted code has no rightful owner to impersonate**, so
ownership can be *created* at claim time instead of raced for at all.

The launcher generates a 256-bit secret locally, sends it with the claim, and
the Worker stores only its SHA-256. Later writes must present the same secret.
That's a capability, not an account - no signup, nothing to phish, and a KV dump
leaks nothing replayable.

The **code** is not a secret; it's meant for group chats. Guessing one reveals
an address the player was going to be given anyway. The **secret** is what would
let someone redirect a host's friends, and it never leaves the host's machine
except in an `Authorization` header.

On disk it lives in `~/.cubeon_launcher/invites.json`, mode `0600`.

## The Write Budget Is the Real Constraint

KV free tier: **~1000 writes/day**, 100k reads/day. Reads are a non-issue (one
read = one friend joining). Writes are scarce, so the Worker avoids them:

- entries carry a **24h `expirationTtl`**, so an abandoned code cleans itself up
  - expiry costs no write, unlike a delete
- `PUT` **reads before writing** and skips the write when nothing changed and the
  entry is still young, so a host restarting three times spends one write
- **no heartbeat, deliberately.** A 30-second keepalive is 2880 writes/day from
  a single host - it would exhaust the budget for every Cubeon user combined
  before lunch. Liveness comes from the TTL instead: less precise, and free.

One exposure worth naming: without rate limiting, anyone who finds the endpoint
can burn the day's writes in a minute and stop everyone from hosting. Bind
Cloudflare's Rate Limiting binding as `RATE_LIMITER` to close it.

## Deploy

1. **Create the KV namespace.** *Storage & databases* → *KV* → **Create
   namespace**, name it `INVITES`.
2. **Create the Worker** as `cubeon-invites`, then *Bindings* → **Add binding**
   → KV namespace, variable name **must be** `INVITES`.
3. **Deploy the code** from `cubeon-invites.js` via *Edit code*.
4. **Check it.** `/health` returns `cubeon-invites ok`.

Point the launcher elsewhere for testing without editing shipped code:

```bash
CUBEON_INVITE_API=http://127.0.0.1:8787 python3 main.py
```

## Verify by Hand

Claim a code (any 43-char secret works - the Worker only hashes it):

```bash
curl -X PUT https://cubeon-invites.hamza-457-shahbaz.workers.dev/i/CUBE-7F4K-9QMN -H "Authorization: Bearer $(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" -H 'Content-Type: application/json' -d '{"address":"example.gl.joinmc.link:52341","version":"1.21.11","loader":"fabric"}'
```

Resolve it - this is what a joining friend's launcher does, and it needs no auth:

```bash
curl -s https://cubeon-invites.hamza-457-shahbaz.workers.dev/i/cube-7f4k-9qmn
```

To test moderation, add a KV key `blocked:CUBE-7F4K-9QMN` (upper-case, any
value): the code stops resolving and can't be re-published, same 404-not-message
stance as a reported skin.

## Format Parity Is Enforced by a Test

The alphabet lives in `cubeon/invites.py` and is **mirrored** in
`cubeon-invites.js`'s `CODE_RE`. A silent divergence would mean the launcher
mints codes the server rejects - and only in production, since nothing local
would notice. `tools/test_invites.py` reads the Worker source and asserts the
two agree, including that the Worker's bearer pattern accepts the `-` and `_`
that `secrets.token_urlsafe` emits.

## What's Still Missing

The Worker is complete and tested; the launcher side has codes, storage and the
network client. Not built yet: **the tunnel that produces an address in the
first place** (playit agent download, one-time claim, start/stop tied to
`cubeon/server.py`'s lifecycle) and the host/join UI. Those need real network
access to verify against playit's actual CLI output.