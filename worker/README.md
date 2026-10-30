[Documentation](../docs/README.md) / Backend

# Cubeon Workers

Cloudflare Workers provide Cubeon's online services. Each service has its
own source and deployment configuration in this directory. Repository
configuration is not proof of deployment health; verify the intended
environment after deploying.

| Worker | Responsibility | Configuration |
|---|---|---|
| `cubeon-skins.js` | Skin identity, username pointers, textures, and the Cubeon cape | `wrangler-skins.toml` |
| `cubeon-invites.js` | Invite codes for tunnel addresses | `wrangler-invites.toml` |
| `cubeon-friends.js` | Presence, chat, groups, and voice signaling | `wrangler-friends.toml` |
| `cubeon-downloads.js` | Release lookup and installer downloads | `wrangler-downloads.toml` |
| `cubeon-waitlist.js` | Website email signup | `wrangler-waitlist.toml` |

The downloads Worker also serves launcher update metadata at `/updates/stable`
and `/updates/beta`, with per-file routes under each channel. These expose
version, size and GitHub's SHA-256 asset digest, never repository credentials or
private notes. A file request must include the version offered by the metadata;
if the cached release changed it returns 409. Both channel lookups share the
existing download throttle and have separate five-minute caches. Deploy this
Worker before shipping a launcher that uses the startup update prompt.

The skins Worker provides the `/skins/<name>.json` CustomSkinAPI lookup
and the write routes (`POST /api/heartbeat`,
`POST /api/skin`, `POST /report`). Its write surface stays narrow on purpose:
all three are POST-only (405 otherwise) and matched before any read route.
They're separate Workers because the friends one needs a **Durable Object**
for its live WebSocket hub, so unlike the KV-only ones it is deployed with
`wrangler`, not the dashboard editor (see its section below).

---

# Abuse protection (what a fork can and cannot do)

**A fork cannot touch your Cloudflare account.** Forking gives nobody your
secrets, your token, or the ability to deploy to your account - a forker who
runs `wrangler deploy` deploys to *their own* account, on their own
`*.workers.dev` subdomain.

**But a fork does not need to.** Every Worker URL is hardcoded in the launcher
(`cubeon/csl.py`, `cubeon/friends.py`, `cubeon/invites.py`) and in the site
(`web/vercel.json`), because a client-side launcher has nowhere to hide them.
So the real question is not "can a forker reach my Workers" - **anyone on the
internet can, by design** - but "what can someone holding the URL cost me".
That is what the Workers themselves have to answer:

| Worker | Who can write | The scarce resource | Protection |
|---|---|---|---|
| `cubeon-skins.js` | only the holder of a per-machine secret, **after** first contact | KV writes (1k/day) | SHA-256 secret at rest, constant-time compare, write budget, **per-IP throttle on all write routes, name-keyed displacement cooldown** |
| `cubeon-invites.js` | only a host holding the code's secret | KV writes | hashed bearer secret, constant-time compare, per-IP throttle (`RATE_LIMITER` **plus** an always-on in-isolate fallback, keyed to the IP and not the attacker-chosen code), write budget |
| `cubeon-friends.js` | only the holder of a name's secret | WebSocket + DO time | SHA-256 secret at rest, constant-time compare, secret sent in the first frame (never the URL, so never a request log), sliding-window limiter per IP and per action, reserved names |
| `cubeon-downloads.js` | nobody - it is read-only | **the GitHub token's API budget**, and the account's shared 100k/day requests | edge-cached release lookup, per-IP throttle (`RATE_LIMITER` + an always-on in-isolate fallback) |
| `cubeon-waitlist.js` | anyone (it *is* a public signup form) | KV writes, **shared with the tally and the skins Worker** | per-IP throttle on POST (`RATE_LIMITER` + an always-on in-isolate fallback) |

*How much that throttle is actually worth was measured from one IP on
2026-10-17: 8 and then 25 rapid POSTs drew zero 429s, 120 drew 95 passes and
then 25 refusals. The binding is the gate that works, and it works **late**.
See "The measured cost" below before you trust a number in that table.*

Two Workers were genuinely exploitable, and **neither needed a fork, a stolen
secret, or an authenticated write**:

**`cubeon-skins.js`** (the identity/skin backend) had two holes on its
*first-contact* path, which is unauthenticated by design, the identity model is
trust-on-first-use, so the first request from anyone claims a UUID.

1. **Write amplification**, a random uuid and a random secret are both
   well-formed, so validation cannot help, and each POST cost **2 KV writes**
   against the account-wide 1k/day budget. 500 anonymous POSTs emptied it, after
   which *every* user's skin upload fails until the day rolls over. Now: a
   per-IP throttle (`20/min`) on all four write routes, running before any
   handler. The `RATE_LIMITER` binding is used when bound, and the in-isolate
   fallback always runs as well - but it is best-effort, so treat the binding as
   the protection (see "The measured cost" below).
2. **Name displacement** (the worse one, because it needs no flood at all), the
   name pointer is last-writer-wins by design, and the only guard was a cooldown
   keyed to the **identity**. An attacker mints identities for free, so four
   successive attempts with a fresh uuid each all succeeded: the victim's name
   flipped to an identity with no skin record, so **every friend saw them as
   cape-only, their skin gone**, and the victim's rename back was itself
   cooldown-throttled for an hour. Now the cooldown is keyed to the **name**
   too, and the previous holder is exempt, so a victim reclaims instantly while
   an attacker's next identity waits an hour. Deliberate consequence: renaming
   *onto* a name taken from someone else within the last hour now 429s.

**`cubeon-downloads.js`** was the third, the only Worker holding a credential.
It spent one GitHub API call on *every* press against a 5000/hour token, with
`Cache-Control: no-store`, so ~1.4 requests/second sustained from anyone with the
URL took the download buttons down for every user. The release lookup is now
edge-cached for 5 minutes, so a flood costs **zero** API calls. That protects
the *token*; it does not refund the request, so a per-IP throttle
(`RATE_LIMITER` + an always-on in-isolate fallback) is the second gate - every
press is otherwise one request against the account-wide 100k/day that all five
Workers share.

**`cubeon-waitlist.js`** was the fourth, and the only one still open in
production on 2026-10-17 (probed: nine rapid signups, zero 429s). Its limiter
was documented as "optional"; the code was a bare `if (env.RATE_LIMITER)` and
the binding was commented out of `wrangler-waitlist.toml`, so the live Worker
had no limit at all. Two KV writes per signup against an **account-wide**
1k/day budget meant 500 POSTs from one machine could empty it in seconds -
taking the tally, every real signup, and the skins Worker (same budget) with
it. Both gates are live now. What they are worth was then **measured** from one
fixed IP - see "The measured cost" below. The residual is honest, not hidden. A
rate limit only raises the price of abusing an unauthenticated write endpoint;
the real fix is a bot gate (Turnstile) on the form, and 00:00 UTC refilling the
budget is the backstop.

### The measured cost of a per-IP throttle (2026-10-17, production, one fixed IP)

| rapid POSTs to `/` | result |
|---|---|
| 8 | 8 × 422, **zero** 429s |
| 25 | 25 × 422, **zero** 429s |
| 120 | **95 × 422, then 25 × 429** |

Two conclusions, both of which cost me a wrong claim before I probed:

- **The binding is the gate that works, and it works *late*.** It converged only
  after roughly a hundred requests. A burst of 25 slips through untouched - so
  "5/min" describes the steady state, not the first second.
- **The in-isolate fallback is best-effort, not a safety net.** Requests for a
  cold Worker need not share an isolate, so the per-isolate `Map` may never
  accumulate at all. It is deterministic in `wrangler dev` and in the tests, and
  it fires on a warm isolate, which is why it stays - but the binding is the
  thing to reason about.

The practical effect is still the one that matters: a flood gets about **190
writes' worth** of signups through before the binding holds that IP to ~5/min,
after which the account-wide 1k writes/day is hours away rather than seconds.

Every reasoning trail lives in the header/comments of the Worker itself; the
tests are `worker/test-worker.mjs` + `worker/test-downloads.mjs` (behaviour) and
`tools/test_skins_net.py` §4 + `tools/test_web_download_count.py` §4b (source
pins, because **CI runs Python and not the Node Worker tests**).

**If you fork this:** point the launcher at your own deployments.
`CUBEON_SKIN_API`, `CUBEON_FRIENDS_API` and `CUBEON_INVITE_API` override the
baked-in URLs, so your users' traffic and quota stay yours. Otherwise their
requests land on the upstream Workers - throttled, but not yours.

Both gates degrade instead of failing, and neither is a promise. The binding
survives isolate recycling but converges late; the in-isolate fallback is
best-effort and may never accumulate live (both measured above). A broken or
absent cache means "one API call per request" - never a 500, and never a silent
hole. A protection that turns into an outage when it misbehaves is worse than
none; one that quietly stops protecting while the comments insist it works is
worse than both.

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

- **Deployed 2026-09-14** (wrangler-invites.toml, KV namespace INVITES). The launcher defaults to
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

- **Deployed 2026-09-14** (wrangler-invites.toml, KV namespace INVITES). The launcher defaults to
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

### Client emotes

The allowlist includes Wave, Dance, Bow, Salute, Shrug, Point, Clap, Laugh,
Sit and Celebrate. Durations must match `cubeon/emotes.py` and the mod
`EmoteState` catalog. Clients skip unknown names, so an older client can
continue displaying its original six emotes after the relay is updated.

Cubeon Client emotes also use this socket. `emote_room` subscribes to a hashed
server address; `emote_ready` acknowledges support. `emote` relays a fixed pose
name, player UUID and serial. The hub supplies the sender's registered Minecraft
username and sends only to live subscribers in that room. No Minecraft server
mod is needed; both clients need the updated Cubeon Client and the same server
address. UUID and username must match a player actually rendered by the client.

Room leases last 45 seconds and clients renew every 20 seconds. Room and active
pose state live in socket attachments, survive hibernation and never enter SQL
or chat history. Poses expire within six seconds; changing rooms sends a stop.
Room updates are capped at 40/min and emote frames at 20/min, below the existing
120/min total-frame budget. Fanout is bounded at 256 sockets; late-join snapshots
at 128 poses. Older clients ignore these message types. Older Workers leave
updated clients in local-preview mode until this Friends Worker is deployed.
Run `node worker/test-emotes.mjs` for relay, isolation, hibernation and expiry checks.

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
