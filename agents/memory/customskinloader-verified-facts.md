# CustomSkinLoader / Cubeon skin network - verified facts

Last verified against the code 2026-08-25. This replaces the earlier version of
this file, which still described the retired name-keyed `POST /upload` API -
if you are reading claims about `/upload`, they are stale.

## Identity model (current)

- **Dual-layer identity.** `~/.cubeon_launcher/auth_key.json` (0600) holds:
  - `public_uuid` - random v4 UUID. Passed to Minecraft via `--uuid` AND used
    as the master key for skins on the backend. Not secret.
  - `secret_token` - `sec_` + 64 hex chars. Private credential; only leaves
    the machine inside an `Authorization: Bearer` header. Never logged.
- **Skins key on the UUID, never the name.** A rename is a pointer move, not
  a re-upload.
- **Usernames are ephemeral pointers.** KV: `pointer:<lowercase-name>` →
  `<uuid>`. Created/updated by the heartbeat.
- **Write auth is Bearer + TOFU per UUID.** Every write route hashes the
  Bearer token (`sha256(secret_token)`) and compares with `owner:<uuid>`
  (constant-time). First writer claims; impostors get `403 not_yours`. The
  Worker stores ONLY the hash - a KV dump leaks nothing replayable.

## Routes (worker/cubeon-skins.js)

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/heartbeat` | Bearer | claim/verify UUID; write `pointer:<name> -> uuid` |
| `POST /api/skin` | Bearer | publish `{uuid, model, skin(b64)}`; stores `texture:<sha256>` + `skin:<uuid> = {id, model}` |
| `GET /skins/<name>.json` | none | CustomSkinAPI lookup: name → UUID → texture **ids** |
| `GET /skins/textures/<id>` | none | the PNG CSL fetches (`root + "textures/" + <id>` under `.../skins/`) |
| `GET /textures/<id>` | none | same PNG bytes, alias for hand-seeding |
| `POST /report` | none | flag a published skin (stored per-UUID, self-expiring) |

KV layout:

```
pointer:<lowercase-username> -> uuid
skin:<uuid>                  -> {"id": "<sha256>", "model": "default"|"slim"}
owner:<uuid>                 -> sha256(secret_token)
texture:<sha256>             -> base64 PNG
report:<uuid>                -> pending moderation report
blocked:<uuid>               -> presence = moderation kill-switch
```

`skin:` stores the bare content **id**, never a URL. CSL resolves profile texture
values as `root + "textures/" + <value>` with root = `.../skins/` (fetches
`/skins/textures/<id>`), so a URL value makes CSL request a double-prefixed
`.../skins/textures/https://…` and silently drop the texture. Older records
stored `{"url": "<origin>/textures/<id>", ...}`; reads still accept that form
and take the id from the last path segment.

## Cape-for-every-Cubeon-user (via pointer)

- `serveProfile` gates on the POINTER: no `pointer:<name>` → hard 404. This is
  the branding boundary - non-Cubeon players are never caped.
- Pointer exists but NO `skin:<uuid>` record → **cape-only profile, 200**:
  `{"username", "textures": {"cape": "<CAPE_ID>"}}`. No Steve-as-a-skin, ever.
- With a skin record → `{default|slim: <id>, cape: <CAPE_ID>}` (skin key first;
  CSL's first-source-wins merge makes that the preference order). Values are
  bare ids, matching CSL's `root + "textures/" + <id>` texture resolution.
- Client side: `sync_local_skin_to_csl()` publishes even for vanilla players,
  but `_publish_skin` sends heartbeat ONLY when there is no custom skin/hat
  (`has_custom`). Write-frugal: vanilla = one heartbeat on first launch + one
  per rename, deduped via `~/.cubeon_launcher/skin_net.json`.
- Moderation applies to cape-only players too (`blocked:<uuid>` checked before
  the profile is built), and reports resolve name→UUID so they survive renames.

## CSL integration (unchanged, still verified)

- CSL is CLIENT-ONLY → skins work on any server, including vanilla ones.
- LocalSkin "won't be seen by others" → the network API is mandatory for
  other-player visibility; LocalSkin mirror stays for instant/offline local view.
- ExtraList entries are PREPENDED to CSL's load list, which puts Cubeon ahead
  of Mojang (priority 100) - otherwise a taken username gets Mojang's skin and
  the player's own is silently discarded.
- `CustomSkinAPI.toJsonUrl` is bare `root + username + ".json"`: the root's
  trailing slash is load-bearing. Current root:
  `https://cubeon-skins.hamza-457-shahbaz.workers.dev/skins/`
  (see `cubeon/csl.py CUBEON_SKIN_API_ROOT` = `CUBEON_API_BASE + "/skins/"`;
  do not edit by hand).
- Two-launch stagger: Worker entry queues first, LocalSkin entry only after it
  is confirmed merged (see ORDER CONTRACT in `cubeon/csl.py`). Do not touch.
