# 2026-09-11 - skin/cape browse cleanup, installed previews, paging

## What I changed
Three user asks on the Skin/Cape panes (`ui/skin_tab.py`).

- **Removed the fetch-player flow and its copy**: deleted `fetch_player_skin` /
  `fetch_player_cape` / `_install_loaded_skin` / `_install_loaded_cape` and the
  "Get player" buttons. Search fields are now filter-only (`on_submit` gone),
  hints are just "Search skins…"/"Search capes…", captions are "Recommended
  players"/"Recommended capes", empty hints are "No match…"/"…load in the
  background.", and tile tooltips/status no longer say "fetch … from Mojang".
- **Previews in Installed**: rows used a generic `CHECKROOM_ROUNDED` chip, so
  skins/capes were indistinguishable. Added `_skin_thumb_b64` /
  `_cape_thumb_b64` + `_thumb_box`, rendering real previews into each row.
- **Paging**: Installed lists were one endless scroll. Added `_make_pager`
  (prev / "n / m" / next, wrapping) and refactored both `refresh_*_list`
  functions to show ONE row per page; `skin_pager_row`/`cape_pager_row` sit in
  the installed panes. The built-in Cubeon cape is page 1.

## Verification
- `test_ui_smoke` 90/90 (was 86). Added 5f ("installed skin row shows a real
  preview", "one row per page"), a pager-label check in 5b, and rewrote 5c to
  pin "no fetch-player copy" + "search is filter-only". 5b now drives the pager
  to reach the uploaded cape row.
- `test_gallery` 38/38, `test_capes` 14/14, `test_milestones` 41/41,
  `test_net` 19, `test_mod_store` 21, `test_modpacks` 51, `test_skins_net`
  PASS. `py_compile` clean on `ui/skin_tab.py main.py`.
- module-map.md Follow-up 21 updated (filter-only browse, new installed
  preview/paging note, 90/90).

## Note for next agent
`load_player`/`suggest_player` remain exported from launcher_core and are still
exercised by test_gallery; only the UI entry points were removed. If you ever
re-add a manual name lookup, wire `on_submit` back onto the search fields and
update ui_smoke 5c (it now asserts no `on_submit`).
