# Discord presence avatar — own skin face instead of Steve

## What the user reported
Discord presence showed "a shit ass Steve" (and in a circle):
- **Circle**: Discord renders all presence art as circles — can't change.
- **Steve**: my first attempt used `minotar.net/avatar/<name>`, which only
  resolves Mojang accounts. Offline names get the Steve placeholder.

## The fix (commit 5569619)
1. **Worker** (`worker/cubeon-skins.js`):
   - `POST /api/skin` accepts an optional `face` field (128×128 PNG,
     base64). Stored content-addressed (`texture:<sha256>`), recorded as
     `record.face` in the `skin:<uuid>` record. Zero extra writes when the
     face is unchanged; absent field = old launchers keep working.
   - New `GET /faces/<username>.png`: pointer → uuid → record.face →
     texture. Falls back to the full 64×64 sheet id if the record predates
     face uploads (verified live: `Shadoww___4577.png` → 200, sheet bytes).
   - `isSkinPng` refactored to `isPngWithSize(bytes, w, h)` — faces are
     128×128 and would have been **silently rejected** by the old 64×64/32
     guard. Gotcha for any future non-64×64 texture.
2. **Launcher** (`cubeon/skins.py`): `_compose_face_png(cfg, size=128)` —
   crops (8,8)-(16,16) base head + (40,8)-(48,16) hat layer from
   `compose_skin_with_hat(cfg)`, nearest-neighbor upscale, never raises
   (returns None → upload omits face). `_sync_publish` adds it to the
   upload payload only when the sheet changed (rides the same request).
3. **main.py**: `_discord_avatar()` now returns
   `<CUBEON_API_BASE>/faces/<name>.png` (was minotar). Big image = logo,
   small = player's face, tooltip = username; refreshed on launch/exit.

## Verification
- Pixel-perfect: served `/faces/` bytes == local `_compose_face_png` render.
- End-to-end against `wrangler dev --local`: heartbeat 200 → upload 200 →
  face fetch 200 (128×128 RGBA). Local KV writes don't burn quota.
- `tools/test_ui_smoke.py` 41/41, `tools/test_skins_net.py` all pass.
- Worker deployed to production (version c1ab6c9b).

## Gotchas hit
- **Live face was 404 for `Light_314`**: the publish state still had the old
  username + an armed retry cooldown from the KV quota storm. The quota was
  still exhausted (429 at 22:10 UTC; resets 00:00 UTC) so the production
  re-publish couldn't run yet. Cleared the cooldown + invalidated the hash
  in `~/.cubeon_launcher/skin_net.json`; the next launcher sync after
  00:00 UTC will point `Light_314` at the uuid and upload the face.
  **Check `https://cubeon-skins.../faces/Light_314.png` after reset.**
- `auth_key.json` schema: keys are `public_uuid` / `secret_token` (not
  `uuid`/`secret`).

## Question for the next agent
None — but if the user reports the presence face is still Steve/blank after
00:00 UTC, check `skin_net.json` first (username + cooldown), then whether
Discord cached the old minotar URL (it can cache aggressively; toggling
presence off/on in Discord settings forces a refetch).
