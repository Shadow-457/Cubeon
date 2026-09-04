# Skins worker: fixed the texture-URL vs bare-id bug (skins/capes never loaded)

The read path was serving **absolute** texture URLs in the CustomSkinAPI
profile (`/skins/<name>.json`), and `/api/skin` stored `skin:<uuid>` as
`{"url": "<origin>/textures/<id>", "model"}`. CSL resolves profile texture
values as `root + "textures/" + <value>` with root = `.../skins/` (confirmed
from the repo's own csl.py protocol notes and a real CSL log: it requested
`.../skins/textures/https://.../textures/<id>` and 404'd, silently dropping
skins AND the cape). The pre-`/skins/` archive worker stored/served bare ids,
so the `/skins/` migration introduced the break.

Fix in `worker/cubeon-skins.js`:
- profile `textures` values are now **bare content ids** (`CAPE_ID` for the
  cape), never URLs;
- `/api/skin` stores `{"id": "<sha256>", "model"}`;
- textures are served at `/skins/textures/<id>` (the path CSL actually
  requests) while `/textures/<id>` stays as an alias;
- `skinTextureId()` tolerates legacy `{"url": ...}` records (id = last path
  segment) so already-uploaded players don't lose their skin on redeploy.

Also updated `worker/test-worker.mjs` (seeds/asserts now bare ids, plus a
CSL-emulation regression that resolves every profile value under
`/skins/textures/` and expects 200 PNG, plus legacy-record and new-route 404
checks), `worker/README.md`, and the verified-facts memory.

Verified: `node worker/test-worker.mjs`, `python3 tools/test_csl.py`, and
`python3 tools/test_skins_net.py` all pass.

Next step is deploy: paste `worker/cubeon-skins.js` into the Cloudflare
dashboard (worker/README.md step 3). No KV migration needed - old-format
`skin:` records keep resolving.
