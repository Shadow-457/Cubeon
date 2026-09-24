# Modpack providers (Modrinth + CurseForge)

Date: 2026-08-30. The Modpacks tab originally had ONE provider: Modrinth's
public search API. That's why RLCraft, SkyFactory, DawnCraft etc. never
appeared - they are CurseForge (and/or FTB) exclusives and will never show up
on Modrinth.

## What's plugged in now
- **Modrinth** (no auth) - unchanged, primary. Search hits now carry
  `"source": "modrinth"`.
- **CurseForge** (official API, key-gated) - merged into the same browse and
  search lists (`cubeon/modpacks.py`), hits tagged `"source": "curseforge"`.
  Key lookup order: `CURSEFORGE_API_KEY` env var → `curseforge_api_key` in
  `~/.cubeon_launcher/config.json` → first line of
  `~/.cubeon_launcher/curseforge_api_key`. WITHOUT a key the provider is
  dormant and the tab is exactly as before; the browse status line explains
  why RLCraft/SkyFactory are missing.

## Hard-won facts
- CurseForge API key is free: create an account at console.curseforge.com,
  add a package, copy the `$2a$...` key. Client id is not needed for search.
- Key endpoints: `GET /v1/mods/search?gameId=432&classId=4471&searchFilter=...`
  (classId 4471 = modpacks; sortField 2 = popularity), `GET /v1/mods/{id}/files`,
  batch `POST /v1/mods/files` with `[{"projectID":..,"fileID":..}]` (max 50).
- CF search hits have NO single versions list - approximate from
  `latestFilesIndexes[].gameVersion` (mirrors the UI's mismatch hint).
- File download URLs: `downloadUrl` from the API is `mediafilez.forgecdn.net/...`
  (sometimes null for old files → fall back to the keyless
  `https://www.curseforge.com/api/v1/mods/{id}/files/{fileId}/download`
  redirect). Both hosts were added to `ALLOWED_DOWNLOAD_DOMAINS`.
- **Routing between platforms:** Modrinth project ids are base32 strings,
  CurseForge ids are purely numeric. `get_modpack_file()` routes numeric ids
  to CF (when enabled) - that's how a merged search result resolves back.
- **CF packs are NOT `.mrpack`** - they're zips with `manifest.json`
  ({projectID, fileID} pairs) + `overrides/`. `_cf_manifest_to_mrpack()`
  converts: resolves every file's real URL + SHA-1 via the batch endpoint,
  writes a standard `modrinth.index.json`, repacks `overrides/` members (with
  a per-member traversal guard) and reuses `_install_from_zip` - so the
  existing allowlist/zip-slip/hash checks all still apply. Removed/broken
  files in the CF manifest are skipped, not fatal.
- FTB's public API (`api.feed-the-beast.com/v1/modpacks/...`) is dead (404
  "Cannot GET") as of this date - FTB integration isn't possible without it.
- The curseforge.com *website* search endpoint is Cloudflare-blocked for
  non-browser clients (`_cf-lb_` body) - scraping it is not viable.
- Install routing in `ui/modpacks_tab.py`: `file_info["source"] ==
  "curseforge"` → `core.install_modpack_from_cf(project_id, file_id)`;
  otherwise the usual `install_modpack_from_url`. `run_install()` gained a
  `cf_file=` parameter for this.
- Verified: `tools/test_modpacks.py` still 45/45 (Modrinth path untouched);
  offline conversion test produces a valid mrpack (index + overrides);
  CF provider correctly dormant without a key and live-gated with one.

## UPDATE (2026-08-30, later): CurseForge now works KEYLESS - no API key
- CFWidget (api.cfwidget.com) can't search, only resolve a project id or a
  website path, so keyless browse/search uses a CURATED list of the famous
  CurseForge packs (CURATED_CF_SLUGS: rlcraft, skyfactory-4, dawncraft, atm9,
  aof7, medieval-minecraft, big-chad-guys-plus, prominence-2-rpg, ...) plus
  slug-probing whatever the user typed.
- _cfwidget_fetch() is cached 1 hour (cfwidget rate-limits). Without a key,
  _curseforge_search/_curseforge_get_modpack_file route to the cfwidget
  implementations; a configured key still works and is better (full search,
  master .mrpack resolution vs per-mod download at install).
- ROUTING FIX: get_modpack_file() now routes any numeric project id to the
  CurseForge provider UNCONDITIONALLY (not only when a key is set) - thanks
  to a test that caught CF hits failing to install keylessly.
- RANKING FIX: a typed search promotes a CurseForge hit whose title/slug
  contains the query ABOVE Modrinth's relevance order, so typing "rlcraft"
  now returns the RLCraft pack first (was buried under Modrinth mods named
  "RL*" / "Rising Legends").
- Keyless install: _cfwidget_manifest_to_mrpack() downloads each
  (projectID,fileID) via the keyless download redirect, records real SHA-1,
  and builds a standard .mrpack (mod jars + index) for the same installer.
  Bigger/ slower than the keyed path (redownloads every mod at install time)
  but needs no key. Verified: builds a valid mrpack from a fake manifest.

## UPDATE (2026-09-24): CF rows fixed + the key finally has a UI; new packs need a key
- **The rows were rendering empty, not "missing".** `_cfwidget_to_hit()` hardcoded
  `icon_url=None` and `author=None` and read `downloads` as a SCALAR, while
  cfwidget sends `thumbnail`, `members[0].username` and
  `downloads={"monthly":N,"total":N}` - hence the "blank square / 0 downloads"
  CurseForge rows next to normal Modrinth rows. MC versions now come from the
  grouped `versions{...}` map (loader tags like "Forge" filtered out), with the
  older flat `files[]` shape still accepted. A payload with no `id` is now
  dropped instead of producing `project_id="None"`.
- **Keyless CANNOT discover new packs - verified, don't retry this:** every
  candidate route was probed live on 2026-09-24 - curseforge.com search page,
  `/minecraft/modpacks/feed` (RSS) and `/sitemap.xml` all return Cloudflare
  403 "Just a moment..."; `api.curseforge.com/v1/mods/search` returns 403
  without a key; api.cfwidget.com resolves a project but exposes NO list or
  search endpoint (404 on every listing path); api.feed-the-beast.com is 404;
  api.atlauncher.com is 403; meta.prismlauncher.org's featured-instances feed
  is 404. The curated list is therefore a snapshot, and "new packs" are only
  reachable through the real API.
- **A payload with no `id` is dropped** ... (see above)
- **The curated list is now project-ID based** (`CURATED_CF_PROJECTS`, e.g.
  `cf/mods/285109`): CurseForge renames slags far more often than it reissues
  ids - that is exactly how 5 of the 12 original slug entries went 404 and the
  browse quietly fell to 7 packs. 9 entries verified live.
- **New `set_curseforge_api_key()` / `check_curseforge_api_key()`** in
  cubeon/modpacks.py (exported via launcher_core): the app could READ a key
  from env/config/key-file but there was no way to SET one, so the full
  catalogue was unreachable. The Modpacks tab header now carries a
  "Add free CurseForge key" button + validate-and-save dialog
  (ui/modpacks_tab.py). `search_modpacks_curseforge()`'s cache key gained
  `keyed`, so pasting/removing a key doesn't serve the other provider's page
  for a day.
- Guards: tools/test_modpacks_cf_keyless.py 47/0 (the browse-row mapping, the
  id-based catalogue, and the key round-trip with `_cf_request` faked so the
  suite stays offline). tools/test_modpacks.py 70/0, ui_smoke 170/0,
  mega --static 15/0.

## UPDATE (2026-08-30): launch-progress bar while the game runs
- main.py previously HID the progress bar the instant the game process
  started, so there was no visual that the game was running (only install
  steps showed progress). Now, right before launch_game(), it sets
  progress_bar.value = None (indeterminate pulse) + "Minecraft is running -
  this launcher stays open", visible until the game exits (on_exit hides it).
