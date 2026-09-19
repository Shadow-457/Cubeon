# 2026-09-11 - smooth Browse search, no dead-end button

## What I changed
- **Removed the "Look up ... on Mojang" button** from both skin and cape Browse
  grids (deleted `_lookup_hint`). Empty results now just say
  `No match for "<q>" - press Enter to look it up on Mojang.` in a dedicated
  `skin_empty_hint` / `cape_empty_hint` Text (not the status line, so install
  messages aren't clobbered).
- **Search no longer rebuilds the grid.** `refresh_skin_gallery` /
  `refresh_cape_gallery` now build every tile once, stash `{"skin_gid"/"cape_gid"}`
  on the tile's `.data`, and each keystroke only flips `.visible` using the new
  network-free `gallery.matches_query`. This kills the old per-keystroke
  `controls.clear()` + preview re-render + base64 re-encode (the jank) and the
  image reload/flicker.
- **`cubeon/gallery.py`**: added a memoized catalog (`_cached_catalog`, keyed by
  `remotes.cached_player_ids()`) + `all_gallery_items(kind)` (cached + uncached
  recommended) + `matches_query(item, query)`. `list_gallery_skins/capes` now
  read the same memo. `_apply_query` still hides uncached items when there's no
  query, so the Recommended view stays cached-only.
- **Memoized `_img_b64`** at module level by path+mtime.
- Forced a single rebuild on install/upload/delete by resetting the
  `{skin,cape}_tiles_sig` dict so the INSTALLED pill updates.
- Added `overflow=ELLIPSIS` + fixed width to gallery tile names.

## Verification
- `python tools/test_gallery.py` -> 42/42
- `python tools/test_ui_smoke.py` -> 82/82 (added section 5e: no dead-end
  button; search does not rebuild tile objects; matching shown / non-matching
  hidden)
- `test_capes` 14/14, `test_net` 19, `test_mod_store` 21, `test_modpacks` 51
- `py_compile` on gallery.py, skin_tab.py, launcher_core.py, main.py
- module-map.md Follow-up 21 updated.

## Q for the next agent
The recommended list now renders uncached featured players as hidden tiles in
the no-query view (they only become visible once cached, via the background
prefetch). On a fresh install the grid therefore shows the "load in the
background" hint until the prefetch lands. If you touch the prefetch gating
(`start_prefetch` / `remotes.TEST_HANDLER`), make sure `refresh_active_galleries`
still forces the sig rebuild or new tiles will stay invisible.
