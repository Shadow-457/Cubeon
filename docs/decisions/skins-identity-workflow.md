# Cubeon Skin Network - Architecture, Workflow & Testing Guide

How the "skins + cape that other Cubeon players can see" system actually works
end-to-end: the identity model, every network call the launcher makes, what the
Worker does with them, how to test it in-game, and how to debug it when it
doesn't show up.

Companion docs (deeper detail on specific halves):

| Doc | Covers |
|---|---|
| `docs/phase1-skins-capes.md` | original design doc, CSL ordering facts, moderation model |
| `worker/README.md` | Worker deployment, routes, KV layout, hand-seeding skins |
| `memory/customskinloader-verified-facts.md` | quick-reference fact sheet |

---

## 1. The identity model - two halves, very different jobs

Everything rests on one small file created on first launch:
`~/.cubeon_launcher/auth_key.json` (mode `0600`):

```json
{
  "public_uuid": "f47ac10b-58cc-4372-a567-3e5c2cbe0000",
  "secret_token": "sec_9a8b7c6d5e4f3a2b..."
}
```

| Half | Secret? | What it's for |
|---|---|---|
| `public_uuid` | **No** | The player's durable *account*. Passed to Minecraft via `--uuid` and used as the master key for every skin on the backend. Ends up on servers you join. |
| `secret_token` | **Yes** (`0600`, never logged) | The *password*. Every backend write must present it as an `Authorization: Bearer` header. The Worker stores only its SHA-256, never the token itself. |

Why split them?

- **Skins anchor to the UUID, never the name.** Renaming re-points a lookup at
  the same UUID - your skin follows you across renames.
- **Knowing someone's public UUID is read-only access.** It lets you *fetch*
  their skin; overwriting anything requires their secret token.
- **The username carries zero authority.** Offline ("cracked") accounts have no
  login, so a name is just a label. Trust-on-first-use on the UUID (first
  writer claims it) closes the impersonation hole.

Legacy note: installs from before this model had `{uuid, secret}` keys in
`auth_key.json`. They are migrated in place - both values preserved, only the
JSON key names change.

---

## 2. The full workflow, end to end

```
YOUR MACHINE                          CLOUDFLARE WORKER                OTHER PLAYERS' MACHINES
─────────────                         ─────────────────                ───────────────────────
auth_key.json (created once)
  public_uuid  ──┐
  secret_token ──┤
                 │
1. Launch clicked
   sync_local_skin_to_csl()
   ├─ writes .minecraft/CustomSkinLoader/
   │    LocalSkin/skins/Alex.png      (ONLY if custom skin/hat;
   │                                   what YOU see locally + offline)
   └─ background thread (best-effort):
        POST /api/heartbeat ────────► sha256(Bearer) vs owner:<uuid>
          {username:"Alex",            first write claims the UUID,
           uuid}                       then pointer:alex ──► <uuid>
        POST /api/skin ─────────────► texture:<sha256> = PNG bytes
          (ONLY if you have a          skin:<uuid> = {"url","model"}
           custom skin/hat)
                 │
2. java --username Alex --uuid <public_uuid> ...
                 │
3. In-game, EVERY client running CustomSkinLoader does:
                                      GET /skins/Alex.json
                                      ◄── pointer:alex → uuid →
                                          skin:<uuid> → URL (+cape)
        CSL loads {"textures":{...}} → skin renders on ANY server
```

### Step by step

**Step 1a - LocalSkin mirror** (`cubeon/skins.py: sync_local_skin_to_csl`).
If you have a custom skin or hat set, its composed sheet is written to
`.minecraft/CustomSkinLoader/LocalSkin/skins/<USERNAME>.png`. This is purely
local: it makes *you* see your own skin instantly and even offline. With no
skin and no hat, nothing is written - vanilla Steve stays vanilla locally.

**Step 1b - Heartbeat** (`cubeon/skins.py: _publish_skin`). Always fires (when
skin-mod management is on), even for a fully vanilla player:

```
POST /api/heartbeat
Authorization: Bearer <secret_token>      ← the token rides ONLY here
{"username": "Alex", "uuid": "<public_uuid>"}
```

Worker-side (`worker/cubeon-skins.js: handleHeartbeat`):
1. SHA-256 the Bearer token, compare with `owner:<uuid>` (constant-time).
   No owner yet → this write claims it. Mismatch → `403 not_yours`.
2. Write `pointer:alex → <uuid>` in KV.

This pointer is what makes renames work (next heartbeat under the new name
moves it) and what brands a player as a Cubeon user (see the cape rule below).

**Step 1c - Skin upload** - *only if there is real content* (custom skin or
hat):

```
POST /api/skin
Authorization: Bearer <secret_token>
{"uuid": "<public_uuid>", "model": "default"|"slim", "skin": "<base64 PNG>"}
```

Worker-side: same ownership check, PNG header guard (64x64 / legacy 64x32),
then content-addressed storage: `texture:<sha256-of-bytes>` holds the base64
PNG and `skin:<uuid>` holds `{"url": ".../textures/<sha256>", "model": ...}`.
A default-Steve-no-hat player uploads **nothing** - no wasted KV writes, and
the Worker never serves Steve-as-a-custom-skin.

**Step 2 - Launch.** `cubeon/launch.py` builds the Java command with
`--username <name> --uuid <public_uuid>` via minecraft-launcher-lib. CSL is
auto-downloaded into the active mod profile before mods sync, so a fresh
install gets it on the same launch.

**Step 3 - Resolution by any CSL client.** Every player running
CustomSkinLoader queries the registered sources in load-list order. Cubeon's
ExtraList entry sits ahead of Mojang, so a lookup goes to:

```
GET https://cubeon-skins....workers.dev/skins/Alex.json
```

Worker-side (`serveProfile`):
1. `pointer:alex` missing → **404**. This is the branding boundary: players
   who never launched Cubeon are never touched.
2. `blocked:<uuid>` present (moderation) → 404.
3. No `skin:<uuid>` record but pointer exists → **200 cape-only**:
   ```json
   {"username": "Alex", "textures": {"cape": "https://...workers.dev/textures/c9124188..."}}
   ```
4. Full profile otherwise - skin first, shared cape second:
   ```json
   {"username": "Alex",
    "textures": {"default": "https://.../textures/<sha256>",
                 "cape":    "https://.../textures/c9124188..."}}
   ```
   `"slim"` replaces `"default"` for 3px-arm (Alex-model) skins.

CSL merges first-source-wins per texture slot, so the skin comes from Cubeon's
network source while LocalSkin still wins local slots (cape/elytra).

### Write-frugality (KV writes ≈ 1000/day free tier are THE constraint)

Dedup state lives in `~/.cubeon_launcher/skin_net.json`:

| Scenario | Network cost |
|---|---|
| Vanilla player, first launch | 1 heartbeat |
| Vanilla launch again, unchanged | **zero calls** |
| Rename (any player) | 1 heartbeat |
| New/changed skin or hat | 1 upload (+ heartbeat if identity also moved) |
| Unchanged skin, relaunch | **zero calls** |

Failures never poison the state file - a failed call leaves the old marker so
the next sync retries.

---

## 3. Testing guide

### Step 0 - deploy the Worker first

Until the updated worker is live, cape-only profiles will 404. Deploy is a
**dashboard paste** (there is no wrangler config for this Worker):

> Cloudflare dashboard → *Workers & Pages* → `cubeon-skins` → *Edit code* →
> paste all of `worker/cubeon-skins.js` → **Deploy**

### Step 1 - offline tests (no Minecraft needed)

```bash
node worker/test-worker.mjs       # Worker logic against a stub KV (55 checks)
python3 tools/test_skins_net.py   # client↔Worker contract (50 checks)
python3 tools/test_csl.py         # CSL ExtraList ordering/stagger rules
python3 tools/test_friends.py     # friends identity shares auth_key.json
```

All four must pass before any in-game testing means anything.

### Step 2 - API sanity check by hand

```bash
curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/health
# → cubeon-skins ok
```

Then launch the launcher once with some username and check the heartbeat
landed:

```bash
curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/skins/TestName123.json
```

Expected for a player with no skin uploaded (cape-only):

```json
{"username":"TestName123","textures":{"cape":"https://cubeon-skins....workers.dev/textures/c9124188..."}}
```

And an unknown name must stay a hard 404 (the branding boundary):

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  https://cubeon-skins.hamza-457-shahbaz.workers.dev/skins/NobodyEverLaunchedCubeon.json
# → 404
```

### Step 3 - cape-only user in-game (single account)

1. Pick an unused username in the launcher; set **no** skin and **no** hat.
2. Select a mod loader instance (Fabric/Forge - CSL is a client mod, vanilla
   can't load it). CSL downloads automatically.
3. **Launch twice.** The first launch queues CSL's sources into ExtraList; the
   second merges them ahead of Mojang (the deliberate stagger).
4. Press F5 (third person): Steve wearing the **Cubeon cape**. Any other
   player looking at you sees it too - on any server, including vanilla ones.

### Step 4 - custom skin between two players

You need two identities: two machines, or one machine with a second
`.minecraft` directory and a different username.

1. Account A: upload a distinctive skin in the Skin tab, launch (twice, as
   above). Verify it reached the backend:
   ```bash
   curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/skins/<PlayerA>.json
   # textures.default = https://.../textures/<sha256>, plus cape
   ```
2. Account B joins the same world/server.
3. B sees A's custom skin + cape; A sees B's cape (and A's own skin locally
   even if B's view lags).

### Step 5 - rename persistence

1. Change the username in the launcher (same machine → same `auth_key.json`).
2. Launch once (fires exactly one heartbeat - check `skin_net.json`'s mtime, or
   watch KV `pointer:<newname>` appear).
3. Other players now resolve the new name to the same skin. The old pointer
   key stays until overwritten - harmless.

---

## 4. Troubleshooting

Check in this order; each step rules out a layer:

```bash
# 1. Is the Worker alive and NEW?
curl -s https://cubeon-skins.hamza-457-shahbaz.workers.dev/health

# 2. Did our publish actually happen / get recorded?
cat ~/.cubeon_launcher/skin_net.json
# has_custom=false → expect username/uuid/base but NO hash (correct!)
# has_custom=true  → expect a "hash" too after a successful upload

# 3. Did CSL consume our registration? (empty dir AFTER a game ran = good)
ls .minecraft/CustomSkinLoader/ExtraList/

# 4. Are Cubeon's sources merged, and AHEAD of Mojang?
python3 -c "import json;print(json.load(open('.minecraft/CustomSkinLoader/CustomSkinLoader.json'))['loadlist'])"
# 'Cubeon' should be near the FRONT of the list
```

| Symptom | Likely cause | Fix |
|---|---|---|
| Cape shows for you, nobody else sees your skin | You have a skin uploaded but the other player isn't running CSL, or their load list lacks `Cubeon` | Both sides need the mod + second-launch stagger |
| Nothing shows even locally | Playing a vanilla (non-mod) instance | Select a Fabric/Forge instance |
| Profile 404s for your name | Worker not redeployed yet, or heartbeat failing | Redeploy; check `skin_net.json`; try `curl` from Step 2 |
| Skin shows as default Steve online but fine locally | Upload failing (offline during launch, or 403) | Relaunch online; check `owner:<uuid>` in KV dashboard |
| Someone has your name's skin and you can't overwrite | Their install claimed that UUID first (TOFU) | Use your own identity - names are pointers, not accounts; report abuse via `/report` |
| Changed skin but others see the old one | CDN/profile cache (60 s) or they haven't reloaded | Wait ~60 s, or F5 + rejoin |
| First-ever launch shows nothing | The one-launch stagger | Launch a second time |

---

## 5. Guarantees and non-guarantees

**Guaranteed:**
- Only the machine holding `secret_token` can write under its UUID (Worker
  stores sha256 only; constant-time compare).
- Non-Cubeon players never get branded (no pointer → 404).
- Default-Steve players get the cape without any Steve texture being shipped.
- Renames never orphan a skin or reset per-UUID server data (saves,
  inventory) - everything keys off `public_uuid`.

**Not guaranteed (by design, best-effort):**
- First writer wins a UUID - a fresh install that somehow collides (practically
  impossible: v4 = 122 random bits) or a malicious claimant racing a brand-new
  identity. Moderation (`blocked:<uuid>`) is the backstop.
- Instant propagation: profiles cache for 60 s; uploads are async background
  threads, so a skin added seconds before joining may land on the next launch.
