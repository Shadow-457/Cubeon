# Cubeon Workers

Three Cloudflare Workers, all on the free tier, no VPS, no card:

| Worker | Job | Status |
|---|---|---|
| `cubeon-skins.js` | identity + skins: UUID-anchored skins, username pointers, the Cubeon cape | **live** |
| `cubeon-invites.js` | short invite codes → a host's tunnel address | **not deployed yet** |
| `cubeon-friends.js` | Friends tab: presence, chat, groups, voice signalling | **not deployed yet** |

The skins Worker is fully live - the read path (the `/skins/<name>.json`
CustomSkinAPI lookup) *and* the write routes (`POST /api/heartbeat`,
`POST /api/skin`, `POST /report`). Its write surface stays narrow on purpose:
all three are POST-only (405 otherwise) and matched before any read route.
They're three separate Workers because the friends one needs a **Durable Object**
for its live WebSocket hub, so unlike the other two it is deployed with
`wrangler`, not the dashboard editor (see its section below).

---

# Cubeon skin/cape API

Cloudflare Worker that makes Cubeon players see each other's skins - and the
Cubeon cape - in-game, on **any** server, including vanilla ones.

- **Live at:** `https://cubeon-skins.hamza-457-shahbaz.workers.dev/`
- **Protocol:** CustomSkinAPI Revision 2, spoken by the client-side
  CustomSkinLoader (CSL) mod
- **Cost:** free tier, no VPS, no card

That `workers.dev` URL is fine permanently: it only ever appears inside a CSL
config file, so no human ever reads it. `cubeon.run.place` is a free DNSExit
subdomain and *cannot* be added to Cloudflare (their free plan only accepts a
registrable apex domain, and `run.place` belongs to DNSExit). The domain is for
Phase 3 tunneling, where the address genuinely is user-facing.

## Files

| File | What it is |
|---|---|
| `cubeon-skins.js` | the Worker - paste this into the dashboard editor |
| `test-worker.mjs` | tests, `node worker/test-worker.mjs`, no deps needed |
| `cubeon-invites.js` | the invite-code Worker (see below) |
| `test-invites.mjs` | its tests, `node worker/test-invites.mjs` |
| `../tools/make_cape.py` | regenerates the cape **and** patches the Worker's constants |
| `../tools/test_invites.py` | the launcher side of invite codes, incl. format parity with `cubeon-invites.js` |

## Deploy

No `wrangler` or npm needed - the dashboard editor is enough.

1. **Create the KV namespace.** Cloudflare dashboard → *Storage & databases* →
   *KV* → **Create namespace**, name it `SKINS`.
2. **Bind it to the Worker.** *Compute* → *Workers & Pages* → `cubeon-skins` →
   *Bindings* → **Add binding** → KV namespace. Variable name **must be**
   `SKINS`; pick the namespace from step 1.
3. **Deploy the code.** Open *Edit code*, replace everything with the contents
   of `cubeon-skins.js`, **Deploy**.
4. **Check it.** Visit `/health` - it should return `cubeon-skins ok`.

Re-run step 3 after any change to `cubeon-skins.js`, including after
`make_cape.py` patches the cape into it.

## Routes

| Route | Auth | What it does |
|---|---|---|
| `POST /api/heartbeat` | `Authorization: Bearer <secret_token>` | claim/verify a UUID, repoint `<username>` at it |
| `POST /api/skin` | `Authorization: Bearer <secret_token>` | publish a skin sheet against the caller's UUID |
| `GET /skins/<name>.json` | none | CustomSkinAPI lookup for CSL: name → UUID → texture ids |
| `GET /skins/textures/<id>` | none | the PNG CSL fetches for one content id (`root + "textures/" + <id>`) |
| `GET /textures/<id>` | none | the same PNG bytes, alias kept for hand-seeding / old records |
| `POST /report` | none | flag a published skin for human review |
| `GET /health` | none | plain-text OK |

KV layout:

```
pointer:<lowercase-username> -> uuid                        (ephemeral name pointer)
skin:<uuid>                  -> {"id":"<sha256>","model":"default"|"slim"}
owner:<uuid>                 -> sha256(secret_token)        (TOFU ownership lock)
texture:<sha256>             -> base64 PNG
report:<uuid>                -> pending moderation report   (self-expiring)
blocked:<uuid>               -> presence = moderation kill-switch
```

`skin:` stores the bare content **id**, never a URL. CSL resolves profile texture
values as `root + "textures/" + <value>` with root = `.../skins/`, so the value
must be just the id - a URL makes CSL fetch `.../skins/textures/https://…` and
silently drop the texture. (`skin:` records written by older builds stored an
absolute `{"url": "<origin>/textures/<id>"}` instead; reads still accept that
form and use the id from the last path segment.)

## Verify by hand

```bash
curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/health
```

An unknown username is a hard 404 - the pointer gate is the branding boundary,
so non-Cubeon players are never dressed in the cape. A heartbeated player who
never uploaded a skin gets a **cape-only** profile (this is "cape for every
Cubeon user": vanilla-Steve Cubeon players are visible as Cubeon players, with
no Steve-as-a-skin upload):

```bash
curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/skins/HeartbeatedOnly.json
```

```json
{"username":"HeartbeatedOnly","textures":{"cape":"c9124188d636edfeaa78b07cdb123dd22026dad435330fdd2c6ef3497f4be789"}}
```

Texture values are **bare content ids** - CustomSkinLoader resolves them as
`<root>textures/<id>` with root = `.../skins/`, i.e. it fetches
`/skins/textures/<id>` for the PNG bytes. (They are *not* URLs: a URL value
made CSL request `.../skins/textures/https://…` and silently drop the skin.)

A player who has heartbeated *and* uploaded gets skin + cape:

```bash
curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/skins/AnyName123.json
```

```json
{"username":"AnyName123","textures":{"default":"<sha256>","cape":"c9124188d636edfeaa78b07cdb123dd22026dad435330fdd2c6ef3497f4be789"}}
```

Both forms of the PNG endpoint return the same bytes - the `/skins/textures/`
one is what CSL uses, `/textures/` is the alias:

```bash
curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/skins/textures/c9124188d636edfeaa78b07cdb123dd22026dad435330fdd2c6ef3497f4be789 | file -
```

The cape PNG should be a 269-byte 64x32 image:

```bash
curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/textures/c9124188d636edfeaa78b07cdb123dd22026dad435330fdd2c6ef3497f4be789 | file -
```

## Seed a test skin by hand

The launcher publishes automatically (see *How writes are authorized* below).
To seed a skin without it - e.g. to check the read path against a fixed
texture - write three KV keys directly.

Get the base64 and hash of a skin PNG:

```bash
python -c "import base64,hashlib,sys; d=open(sys.argv[1],'rb').read(); print('sha256:', hashlib.sha256(d).hexdigest()); print(base64.b64encode(d).decode())" myskin.png
```

Then in the KV dashboard, add:

| Key | Value |
|---|---|
| `pointer:<lowercase-username>` | any UUID v4, e.g. one from `python3 -c 'import uuid;print(uuid.uuid4())'` |
| `texture:<sha256>` | the base64 string |
| `skin:<that uuid>` | `{"id":"<sha256>","model":"default"}` |

Use `"model":"slim"` for a 3px-arm (Alex) skin. Textures are stored as base64
*text* precisely so they can be pasted in the dashboard like this.

To test moderation, add a key `blocked:<uuid>` (the UUID from the pointer key,
any value) - that player immediately falls back to vanilla Steve/Alex, and a
rename doesn't dodge it.

## In-game setup (shipped - `cubeon/csl.py`)

Nothing here is a manual step for the user. On every launch Cubeon downloads
CustomSkinLoader from Modrinth into the active mod profile and registers two
sources with it; `cfg["manage_skin_mod"] = false` is the opt-out.

**Why registration is mandatory, not a nicety.** CSL orders its sources by
ascending priority: Mojang `100` → LittleSkin `200` → BlessingSkin `300` → …
→ LocalSkin `710` → OptiFine `810` → CloakPlus `840`. Mojang resolves skins by
*username* and does not care that the player is offline, and CSL's `mix()` only
fills empty fields (first-source-wins per texture slot). So by default a cracked
player named `Dream` gets the real Dream's skin and their own local skin is
silently discarded - the impersonation risk flagged above, confirmed from
source. Registering Cubeon ahead of Mojang is what fixes it.

Registration writes one JSON file per source into
`.minecraft/CustomSkinLoader/ExtraList/`, which CSL **prepends** to the load
list and then deletes. That's the supported extension point, so the user's
hand-tuned `CustomSkinLoader.json` is never rewritten:

```json
// ExtraList/cubeon-api.json          -> the cape + uploaded skins, from this Worker
{ "name": "Cubeon", "type": "CustomSkinAPI", "root": "<worker root, trailing slash>" }

// ExtraList/cubeon-localskin.json    -> the player's own skin/cape/elytra, local
{ "name": "CubeonLocalSkin", "type": "Legacy",
  "skin": "LocalSkin/skins/{USERNAME}.png",
  "cape": "LocalSkin/./capes/{USERNAME}.png",
  "elytra": "LocalSkin/./elytras/{USERNAME}.png",
  "model": "auto", "checkPNG": false }
```

Two of CSL's rules constrain those files, and both are asserted in
`tools/test_csl.py` against comparators copied out of CSL's source:

- `LegacyLoader.compare()` ANDs skin, cape **and** elytra. The Legacy entry has
  to declare its cape (so a player's custom local cape can win the cape slot), but
  the built-in LocalSkin already claims the plain `LocalSkin/capes/...` path - so
  ours carries a `./` segment (`LocalSkin/./capes/...`). It resolves to the same
  file but compares unequal, so the entry survives dedupe instead of being dropped
  as a duplicate and leaving LocalSkin stranded behind Mojang at 710. (The two
  entries are also queued in a deliberate order - Worker first, local second - so
  the local source is prepended last and sits ahead of the Worker; see the ORDER
  CONTRACT in `cubeon/csl.py`.)
- `CustomSkinAPI.toJsonUrl` is bare `root + username + ".json"` with no
  normalization, so the root's **trailing slash is load-bearing**.

Verified in-game on Minecraft 1.21.11 (2026-08-22): CSL consumes the ExtraList
files Cubeon writes, the cape renders with the logo upright - so
`FLIP_OUTSIDE` in `tools/make_cape.py` is correct as shipped - and the local
skin loads alongside it, which is the first-source-wins merge working as
described above.

## How writes are authorized

Offline/cracked accounts have **no authentication whatsoever** - a username is
just a string typed into a text field. The identity API therefore splits the
player into two layers:

- a **public UUID** (`auth_key.json`'s `public_uuid`) - the master key every
  skin is anchored to and the same UUID Minecraft is launched with;
- a **private secret token** (`secret_token`, `sec_` + 64 hex) that never
  leaves the machine except as an `Authorization: Bearer` header.

Every write route hashes the Bearer token and compares against `owner:<uuid>`:
the **first** writer claims the UUID (trust-on-first-use), and every later
write must present the same secret or get `403 not_yours`. So knowing someone's
public UUID - which is on every server they join - lets you *read* their skin
but never *overwrite* it. Only the SHA-256 is stored, so a KV dump leaks
nothing replayable.

The username itself carries no authority at all: `/api/heartbeat` just repoints
`pointer:<name>` at the caller's UUID, which is how renames propagate without
touching the skin.

This is best-effort, not a hard guarantee: a UUID's first writer wins it, and
an unclaimed name can be pointed anywhere by whoever heartbeats first. That's
exactly what `/report` and the `blocked:<uuid>` kill-switch (above) are for -
and why LocalSkin still shows *you* your own skin no matter what the network
says. Design notes: `agents/docs/phase1-skins-capes.md`.

The read path for players who haven't uploaded anything is a hard 404, which
is also what makes CSL fall through cleanly to LocalSkin when offline.

---

# Cubeon invite API

Turns `bluefox-1234.gl.joinmc.link:52341` into `CUBE-7F4K-9QMN`.

- **Not deployed yet.** The launcher defaults to
  `https://cubeon-invites.hamza-457-shahbaz.workers.dev` - same account as the
  skins Worker. Nothing calls it until the host UI lands.
- **Launcher side:** `cubeon/invites.py`
- **Tests:** `node worker/test-invites.mjs` and `python3 tools/test_invites.py`

## Why a code and not just the address

Three reasons, in order of how much they matter:

1. **A tunnel address is unsayable.** The pitch is "send a link"; a random
   subdomain with a five-digit port is something you can only copy-paste.
2. **playit's free tier changes the port on reconnect.** The code stays put, so
   a friend group saves it once and it keeps working.
3. **The provider stays invisible.** Swapping playit for a VPS later changes
   only a value in KV - no user ever learns what playit is.

## Routes

| Route | Auth | What it does |
|---|---|---|
| `PUT /i/<CODE>` | `Authorization: Bearer <secret>` | claim a free code, or repoint one you own |
| `GET /i/<CODE>` | none | resolve to `host:port` (+ version, loader, age) |
| `DELETE /i/<CODE>` | `Authorization: Bearer <secret>` | unpublish when the host stops |
| `GET /health` | none | plain-text OK |

Codes are case-insensitive; the launcher also strips dashes, spaces and a pasted
URL prefix before sending, so `cube7f4k9qmn` works.

## Ownership without accounts

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

## The write budget is the real constraint

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

## Verify by hand

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

## Format parity is enforced by a test

The alphabet lives in `cubeon/invites.py` and is **mirrored** in
`cubeon-invites.js`'s `CODE_RE`. A silent divergence would mean the launcher
mints codes the server rejects - and only in production, since nothing local
would notice. `tools/test_invites.py` reads the Worker source and asserts the
two agree, including that the Worker's bearer pattern accepts the `-` and `_`
that `secrets.token_urlsafe` emits.

## What's still missing

The Worker is complete and tested; the launcher side has codes, storage and the
network client. Not built yet: **the tunnel that produces an address in the
first place** (playit agent download, one-time claim, start/stop tied to
`cubeon/server.py`'s lifecycle) and the host/join UI. Those need real network
access to verify against playit's actual CLI output.

---

# Cubeon friends API

The realtime backend for the **Friends tab**: unique Cubeon names, presence
(online/offline + which game version), direct chat, groups, and voice-call
signalling - all over one WebSocket.

- **Not deployed yet.** The launcher defaults to
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

## Why it's a Durable Object, not KV

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

## Format parity is enforced by a test

`cubeon/friends.py` and `cubeon-friends.js` have to agree on three things or the
launcher talks to the server in a dialect it rejects - and only in production,
since nothing local would notice: the **message-type strings** (27 of them), the
**name regex** (`[A-Za-z0-9_]{3,16}`), and the **reserved names**.
`tools/test_friends.py` reads this Worker's source and asserts all three match.

## What's still missing

The protocol, client, and UI are built and the offline tests pass. Not yet
verified against a **live deploy**: the DO has never run on real Cloudflare, so
the WebSocket handshake, hibernation behaviour, and SQLite queries are only
proven by the JS parser and the parity test. Voice **audio** is an optional
dependency (`sounddevice` + `numpy`); without it, calls still ring, connect, and
carry text - there's just no sound.
