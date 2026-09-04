# Phase 1 - Skins + Capes that other Cubeon players can see

Status: **superseded by the identity API (2026-08-25).** The name-keyed
`POST /upload` scheme described below was replaced by a dual-layer identity
model: skins are anchored to the machine's persistent `public_uuid`
(`auth_key.json`), usernames are ephemeral pointers, and every write is
Bearer-authorized by the private `secret_token` (Worker stores only its
SHA-256). Current contract - `POST /api/heartbeat`, `POST /api/skin`,
`GET /skins/<name>.json` in `worker/cubeon-skins.js`; client half in
`cubeon/skins.py` `_publish_skin()`; CSL root is now
`<worker>/skins/`. The CSL ordering work, LocalSkin mirror, cape pipeline,
moderation model, and everything else below are unchanged and still accurate;
where this doc says "keyed by username", read "keyed by UUID with a username
pointer".

Earlier status: implemented + tested 2026-08-24; `/upload` live since
2026-08-25. The launcher-side upload/report client (`cubeon/skins.py`), the
Worker endpoints (`worker/cubeon-skins.js` `POST /upload` + `/report`), and the
CSL ordering (`cubeon/csl.py`) are built and covered by `tools/test_skins_net.py`,
`worker/test-worker.mjs`, and `tools/test_csl.py`.

Goal: an uploaded skin (and cape) shows up in-game **for other Cubeon players, on
any server** - not just locally. Zero manual steps for the user, zero servers to
run, no Java.

Build order for the project overall: **Phase 1 skins+capes → Phase 2 Fabric
server hosting + mod-sync → Phase 3 tunneling.**

---

## 0. Verified facts this design rests on

Checked 2026-08-21 against CustomSkinLoader's (CSL) own repo/wiki and the
CustomSkinAPI spec (`xfl03/CustomSkinLoaderAPI`, spec is zh_CN):

1. **CSL is CLIENT-ONLY.** Its own docs say explicitly: do not install it
   server-side. → skins work on *any* server the user joins, which is exactly why
   Phase 1 comes before hosting.
2. **`LocalSkin` "won't be seen by others"** - CSL's docs state this outright.
   This is decisive: the local-file approach in today's `cubeon/skins.py` can
   *never* deliver "other Cubeon players see my skin." A **network skin API is
   mandatory**, not a nice-to-have.
3. **CustomSkinAPI protocol** (CSL implements Revision 2 since **v14.5**):
   - Lookup: `GET {ROOT}/{USERNAME}.json` - ROOT must end in `/`,
     username lookup is case-insensitive.
   - Response: `{"username": "<properly-cased>", "textures": {...}}` where keys
     are `default`, `slim`, `cape`, `elytra` → each a texture id string.
     Dict order = preference order. (A shorthand `skin`/`cape`/`elytra` form also
     exists; `textures` wins if both are present. Any entry may be omitted/null.)
   - Textures: `GET {ROOT}/textures/{id}` - id is any unique string, **SHA-256
     recommended**.
   - `200` = found, `404` = not found, on both endpoints.
   - Redirects and GZIP allowed. Should honor `If-Modified-Since`, return
     `Content-Length`/`Last-Modified`, and `Cache-Control` beats `Expires`.
4. **Capes come free from the same endpoint** - the `cape` key. No extra
   mechanism. (`elytra` is available too, as a later bonus.)
5. **`ExtraList` is the designed extension point.** Skin servers ship a JSON file
   users drop into `.minecraft/CustomSkinLoader/ExtraList` to register
   themselves in the load list - so Cubeon does **not** have to clobber the
   user's `CustomSkinLoader.json`.
6. **License: GPL-3.0-only** (source). Binaries: the *unmodified official jar*
   may be shipped in modpacks, but **CSL must be listed in the mod list**, and
   *reposting elsewhere requires permission*.
   → Cubeon **downloads the official jar from Modrinth at runtime** and never
   rehosts it, and **credits CSL visibly in the Skin tab**. Because Cubeon only
   downloads a jar and writes a config file (no linking, separate process), GPL
   copyleft does **not** propagate to Cubeon's Python code.

### Still unverified - check during implementation
- The exact **`ExtraList` JSON schema** (fallback plan in §3).
- **Cape texture dimensions** CSL accepts (classic is 64×32; CSL supports HD, so
  likely any 2:1). Validate empirically before enforcing limits.
- Minimum CSL version to require. Spec R2 landed in 14.5 → require ≥14.5, or
  emit the shorthand form for older clients.

---

## 1. Architecture

```
Cubeon launcher (Python)                Cloudflare (free tier)
─────────────────────────               ──────────────────────────────
upload skin/cape  ──POST──────────────▶  Worker  ──▶  Workers KV
auto-install CSL jar (from Modrinth)     GET /{user}.json
write ExtraList/cubeon.json ───────────▶ GET /textures/{sha256}
                                         POST /upload
                                         POST /report

in-game: CSL (client-side) reads {ROOT}/{username}.json ──▶ everyone
         running Cubeon sees everyone else's skin + cape
```

No VPS.

### Hosting decision: `*.workers.dev`, not the domain

The domain is **`cubeon.run.place`** - a free DNSExit subdomain (nameservers
`ns10-13.dnsexit.com`).

**It cannot be used for the skin API, and does not need to be.** Cloudflare's
free plan only accepts a *registrable apex* domain as a zone, verified against
the Public Suffix List. Here the registrable domain is `run.place`, which
belongs to DNSExit - so `cubeon.run.place` can't be added as a free zone
(subdomain-only zones are Enterprise; CNAME/partial setup is Business). Nor can
a DNSExit `CNAME` point at `*.workers.dev`: Cloudflare rejects CNAMEs for
hostnames not configured in the owning account.

That costs nothing, because **the skin API URL is never seen by a human** - it
lives inside a CSL config file. So:

- **`ROOT = https://cubeon-skins.<account>.workers.dev/`** - free, no DNS, no card.
- **The domain's real job is Phase 3**, where the address *is* user-facing
  (`bluefox.cubeon.run.place`). DNSExit exposes a DNS API (linked in their
  dashboard sidebar), so per-host SRV records can be created dynamically there -
  Cloudflare isn't needed for that either.

### Storage: Workers KV, not R2

Use **Workers KV**. R2 generally wants a payment method on file even for its free
tier *(worth confirming - if it turns out not to, R2 is the better long-term fit)*,
whereas KV's free tier needs no card and is comfortably big enough: skins are
2–8 KB, KV gives ~1 GB, 100k reads/day, 1k writes/day, 25 MB max value.

Cap on the Workers free plan is **100k requests/day**. Immutable
`Cache-Control` on textures keeps most repeat fetches at Cloudflare's edge.

---

## 2. Worker API

`ROOT = https://skin.<domain>/`

### `GET /{username}.json`
Returns the CustomSkinAPI profile. `404` when unknown or blocked.

```json
{
  "username": "BlueFox",
  "textures": {
    "default": "<sha256>",
    "cape":    "<sha256>"
  }
}
```
- Emit `slim` instead of `default` when the skin is the Alex model - reuse the
  existing `_detect_slim_model()` in `cubeon/skins.py:83`, which already does this.
- `Cache-Control: public, max-age=60` - short, so a skin change appears fast.
- Honor `If-Modified-Since`.

### `GET /textures/{sha256}`
Raw PNG bytes. Content-addressed ⇒ immutable ⇒
`Cache-Control: public, max-age=31536000, immutable`.

*Optimization:* the spec permits redirects, so this may `302` to a public R2
custom-domain URL to keep texture traffic off the Worker entirely.

### `POST /upload`
Body: PNG bytes + `kind` (`skin`|`cape`) + `username` + device token (§4).
- **Re-validate server-side**: PNG magic bytes, allowed dimensions, size cap
  (~50 KB). Client-side validation is bypassable, so it cannot be the only gate.
- Store at `textures/{sha256}`; bind `username → {skin, cape}` in KV.
- Dedupe by hash for free.

### `POST /report`
Body: `username` + optional reason. Increments a counter for review. See §5.

---

## 3. Launcher integration

On enabling skins (or first upload):

1. **Ensure Fabric + CSL.** Reuse the existing auto-install patterns:
   `cubeon/mod_loaders.py` for the loader, `cubeon/mods.py` `download_mod()` /
   `get_mod_download()` for the jar. CSL goes into the active
   `(mc_version, loader)` profile via `get_profile_dir()`.
2. **Register Cubeon as a skin source** by writing
   `.minecraft/CustomSkinLoader/ExtraList/cubeon.json`, pointing at
   `ROOT` with type `CustomSkinAPI`.
   *Fallback if the ExtraList schema doesn't cooperate:* patch the `loadlist`
   array in `.minecraft/CustomSkinLoader/CustomSkinLoader.json`, inserting the
   Cubeon entry **first** while preserving every existing entry.
3. **Load order: Cubeon first.** CSL's default list starts with Mojang, and
   Mojang lookups work by username even offline - so a kid using the name
   "Dream" would get Dream's real skin instead of their own upload. Cubeon must
   win.
4. **Keep LocalSkin as an offline fallback** (it works with no network), but the
   UI must be honest that local-only skins are invisible to others.

### Bugs fixed in existing code (found while writing this, fixed 2026-08-21)

- **Wrong LocalSkin path** - was `config/customskinloader/LocalSkin/skins`; CSL's
  real path is `.minecraft/CustomSkinLoader/LocalSkin/skins/`. Now centralized as
  `CSL_LOCAL_SKINS_DIR` in `cubeon/paths.py`.
- **Wrong filename** - wrote `cubeon_active_skin.png`; CSL requires
  `<USERNAME>.png`. **The local-skin feature could not have worked before this.**
- **Stale file on rename** - offline accounts are keyed off the username, so
  renaming left `<OLDNAME>.png` behind and the skin stopped resolving.
  `sync_local_skin_to_csl()` now runs from both username handlers in `main.py`.
- **Skin never un-applied** - clearing the active skin left the PNG in place
  forever, so "no skin" still showed the old one.
- **`skinlayers3d` wrongly accepted** by `skin_mod_installed()`. It renders 3D
  layers of an already-loaded skin; it does not load custom skins.

Deletion is guarded by a new `csl_synced_name` config key that records what the
launcher wrote, so a skin the user placed in `LocalSkin` by hand is never
clobbered. All five behaviors are covered by an end-to-end test run.

Cape paths (`CSL_LOCAL_CAPES_DIR`) and the `ExtraList` dir are defined in
`cubeon/paths.py`, ready for M2/M4.

---

## 4. Identity: who owns a username

Offline auth means usernames are unauthenticated - anyone can upload a skin for
any name. Full accounts are too much friction for this audience, so:

**First-claim-wins with a device secret.**
- On first run the launcher generates a random secret, stored in
  `~/.cubeon_launcher/config.json`.
- First upload for a username binds `username → hash(secret)`.
- Later uploads for that username require the same secret.

Stops casual hijacking with no signup. **Known limitation:** wiping
`~/.cubeon_launcher/` loses the claim. Acceptable for v1; document it.

---

## 5. Moderation - a launch requirement, not a follow-up

User-uploaded images served to an audience of kids. Something vile will be
uploaded in week one, and "sketchy" is the exact reputation Cubeon exists to beat
TLauncher on. Minimum viable:

- **Report button** in the Skin tab → `POST /report`.
- **Kill-switch**: a `blocked:{username}` KV entry makes `/{username}.json`
  return `404`, so CSL cleanly falls back to Steve/Alex - no crash.
- **Hash ban**: because storage is content-addressed, banning one SHA-256 blocks
  that image for everyone, forever, including re-uploads.
- **Device ban**: retain `hash(secret)` + timestamp per upload so a repeat
  offender can be cut off, not just their current name.

---

## 6. Milestones

| # | Deliverable | Why this order |
|---|---|---|
| M1 | Worker read-path only (`/{user}.json` + `/textures/*`), textures placed in R2 by hand; verify in-game | **Biggest risk first** - proves the protocol works before any UI exists |
| M2 | Auto-install CSL + write ExtraList from the launcher | Removes the manual step |
| M3 | Upload from the Skin tab + device-token claim | Real user flow |
| M4 | Capes - Cubeon cape for every user + custom uploads | The viral marker (see below) |
| M5 | Moderation: report, block, hash ban | Must land before any public release |

M1 is testable with a single client: have it render *another* username whose
textures you placed manually. That confirms cross-player visibility without
needing two machines.

---

## 7. The growth mechanic

**Every Cubeon user gets the Cubeon cape by default** (decided 2026-08-21).
This replaces the cut nametag-badge idea and is strictly better: a cape is
visible across the map, in third person, and in screenshots, whereas a nametag
badge is small and only readable up close. Because CSL is client-side, it shows
up **on any server**.

That is the "what is that cape?" → "what launcher is that?" loop that made
Feather spread - for near-zero engineering, and with no Java.

Implementation note (updated 2026-08-25 for the identity API): the cape rides
the `cape` key of any profile whose **pointer resolves** - i.e. every player
this launcher has ever heartbeated, whether or not they uploaded a skin. The
mechanics:

- `sync_local_skin_to_csl()` no longer skips the network half for vanilla
  players: with no skin/hat it still fires `POST /api/heartbeat` once on first
  launch and once per rename (write-frugal; gated by `manage_skin_mod`),
  creating `pointer:<name> -> <uuid>`.
- It also never uploads a default-Steve sheet - with no custom content the
  client sends heartbeat only, so `serveProfile` answers with a clean
  cape-only profile instead of Steve-as-a-skin.
- The pointer gate doubles as the branding boundary: a name with NO pointer
  404s, so non-Cubeon players on a server are never caped. Moderation
  (`blocked:<uuid>`) applies to cape-only players too.

A user's own uploaded cape overrides the shared one. Exclusivity was
considered and rejected - at this stage visibility matters more than scarcity.
