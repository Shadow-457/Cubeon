# CurseForge modpack rows + "new packs never show" (2026-09-24)

- **Agent:** Cline
- **Date:** 2026-09-24
- **Task:** "I want CurseForge mod packs too in the modpacks area correctly shown -
  they are hardcoded so new modpacks don't show. Is the API free?"

## What the screenshot actually showed
Five CurseForge rows with a blank square icon and "0 downloads". Not a Flet
rendering bug - the hit dicts were built empty: `_cfwidget_to_hit()` hardcoded
`icon_url=None` / `author=None` and read `downloads` as a scalar while cfwidget
sends `thumbnail`, `members[0].username` and `downloads={"monthly":N,"total":N}`.

## Fixed (keyless, immediate)
- Real thumbnail, real total downloads, real author, MC versions from the
  grouped `versions{}` map (loader tags filtered; legacy flat `files[]` still
  parses). A payload with no `id` is dropped instead of emitting `"None"`.
- The curated fallback is now `CURATED_CF_PROJECTS` - PROJECT IDS, because
  CurseForge renames slugs (that silently 404'd 5 of 12 entries and dropped the
  browse from 12 to 7). 9 entries verified live: RLCraft 30,174,116 dl,
  SkyFactory 4, ATM9, BMC1/2, Craft to Exile 2, AOF7, FantasyCraft, Ages of Time.

## The honest answer on "new packs"
Not fixable keyless, and I measured every route instead of guessing: CF's own
search page / RSS feed / sitemap = Cloudflare 403; api.curseforge.com = 403
without a key; cfwidget resolves a project but has NO list/search endpoint;
FTB 404, ATLauncher 403, Prism's featured-instances feed 404. The key itself is
FREE (console.curseforge.com, request one for a project).
So the app had everything needed EXCEPT a way to SET a key - it could read one
from env/config/key-file but nothing could write it.
- Added `modpacks.set_curseforge_api_key()` / `check_curseforge_api_key()`
  (re-exported via launcher_core): validate with one real API call, report a
  bad key instead of silently degrading, then store it.
- Added an "Add free CurseForge key" button + dialog in the Modpacks tab header.
- `search_modpacks_curseforge()`'s cache key gained `keyed`, so swapping
  providers doesn't serve the other one's cached page for a day.

## Verification
- tools/test_modpacks_cf_keyless.py 47/0 (19 new: row mapping, id catalogue,
  key round-trip - `_cf_request` faked so it stays offline), test_modpacks.py
  70/0, test_ui_smoke.py 170/0, test_mega_smoke --static 15/0.
- Live keyless browse re-run: 9 packs, every row with art + real count + author.

## For the next agent
- The artifacts in dist/ + ~/.local/opt/Cubeon/Cubeon.AppImage were built BEFORE
  this work - rebuild them if the shipped app should show the fixed rows.
- Docs: docs/decisions/modpack-providers.md (UPDATE 2026-09-24) and the
  module-map's "CurseForge modpacks in the Modpacks tab" invariants.
