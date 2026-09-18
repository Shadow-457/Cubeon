# Cubeon Skin/Cape API

Cloudflare Worker that makes Cubeon players see each other's skins - and the
Cubeon cape - in-game, on **any** server, including vanilla ones.

- **Live at:** `https://cubeon-skins.hamza-457-shahbaz.workers.dev/`
- **Protocol:** CustomSkinAPI Revision 2, spoken by the client-side
  CustomSkinLoader (CSL) mod
- **Cost:** free tier, no VPS, no card

## Files

| File | What it is |
|------|------------|
| `worker/cubeon-skins.js` | the Worker - paste this into the dashboard editor |
| `worker/test-worker.mjs` | tests, `node worker/test-worker.mjs`, no deps needed |
| `tools/make_cape.py` | regenerates the cape **and** patches the Worker's constants |
| `tools/test_invites.py` | the launcher side of invite codes, incl. format parity with `cubeon-invites.js` |

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
|-------|------|--------------|
| `POST /api/heartbeat` | `Authorization: Bearer <secret_token>` | claim/verify a UUID, repoint `<username>` at it |
| `POST /api/skin` | `Authorization: Bearer <secret_token>` | publish a skin sheet against the caller's UUID |
| `GET /skins/<name>.json` | none | CustomSkinAPI lookup for CSL: name → UUID → texture ids |
| `GET /skins/textures/<id>` | none | the PNG CSL fetches for one content id (`root + "textures/" + <id>`) |
| `GET /textures/<id>` | none | the same PNG bytes, alias kept for hand-seeding / old records |
| `POST /report` | none | flag a published skin for human review |
| `GET /health` | none | plain-text OK |

### KV Layout

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

## Verify by Hand

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

## Seed a Test Skin by Hand

The launcher publishes automatically (see *How writes are authorized* below).
To seed a skin without it - e.g. to check the read path against a fixed
texture - write three KV keys directly.

Get the base64 and hash of a skin PNG:

```bash
python -c "import base64,hashlib,sys; d=open(sys.argv[1],'rb').read(); print('sha256:', hashlib.sha256(d).hexdigest()); print(base64.b64encode(d).decode())" myskin.png
```

Then in the KV dashboard, add:

| Key | Value |
|-----|-------|
| `pointer:<lowercase-username>` | any UUID v4, e.g. one from `python3 -c 'import uuid;print(uuid.uuid4())'` |
| `texture:<sha256>` | the base64 string |
| `skin:<that uuid>` | `{"id":"<sha256>","model":"default"}` |

Use `"model":"slim"` for a 3px-arm (Alex) skin. Textures are stored as base64
*text* precisely so they can be pasted in the dashboard like this.

To test moderation, add a key `blocked:<uuid>` (the UUID from the pointer key,
any value) - that player immediately falls back to vanilla Steve/Alex, and a
rename doesn't dodge it.

## In-Game Setup (shipped - `cubeon/csl.py`)

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

## How Writes Are Authorized

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
says. Design notes: `docs/decisions/phase1-skins-capes.md`.

The read path for players who haven't uploaded anything is a hard 404, which
is also what makes CSL fall through cleanly to LocalSkin when offline.