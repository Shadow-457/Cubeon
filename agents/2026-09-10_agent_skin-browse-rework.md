# 2026-09-10 — Skin/Cape Browse rework: recommendations, fuzzy search, Installed fix

## What I did
Refined the real-player gallery shipped earlier today (Follow-up 21) after the
user reported: "Installed shows nothing", two search bars, no ready-made
recommendations, and uploads/previews feeling broken.

### The real bug: Installed never appeared
`_view_tabs`' `switch_view` (ui/skin_tab.py) updated `view_state` and the tab
underline but **never flipped the two columns' `.visible`**. The Browse and
Installed columns were both mounted at build; clicking "Installed" moved the
highlight and left Browse on screen — so users saw "nothing". Fixed with a
`view_panes` registry populated in `_view_pane` and `_apply_view(pane_id)`
called from `switch_view`. test_ui_smoke §5d pins it.

### One search box per pane
Skin and Cape Browse each had TWO TextFields: "Search …" + a separate "Load a
real player …" that only one of which actually resolved names. Merged into a
single field: typing fuzzy-filters the cached grid instantly; Enter / "Get
player" looks the typed name up on Mojang (worker thread, never UI thread) and
wears it. Old `skin_load_*` / `cape_load_*` controls deleted.

### Recommended players
- `cubeon/remotes.py`: `FEATURED_PLAYERS` (20 real accounts; ~14 verified cape
  owners) + `featured_names/tags/cape_names/cached_count/count` and
  `prefetch_featured` (network, best-effort, never raises).
- `cubeon/gallery.py`: catalogs take fuzzy `query`/`limit`; featured players
  sort first with no query; `suggest_player` is the fuzzy "did you mean"
  wrapper (Mojang only resolves EXACT names); `prefetch_featured` passthrough.
- `ui/skin_tab.py`: `_ACTIVE_GALLERY_REFRESH` + `refresh_active_galleries()` let
  a background prefetch repaint the grids; `_start_featured_prefetch` runs on
  build (gated off when `remotes.TEST_HANDLER` is set so tests never touch the
  network).

### Fuzzy search
Network-free `_norm` (lower + alnum only) + `_match_score` (exact 100 > prefix
85 > substring 70 > subsequence 45 > tag 35). "realplayr" still finds
"RealPlayer"; "captain_sparklez" == "CaptainSparklez".

### "Why does searching show only 1 suggestion?"
Follow-up: `_catalog` only listed players ALREADY in the cache, so on a fresh
install a search matched at most the one prefetched player (or nothing). Two
fixes:
- With a `query`, `_catalog` now also appends not-yet-cached featured players
  (`cached: False`, `preview_path: None`). The tile shows a placeholder icon;
  its GET fetches on demand on a worker thread. The no-query Recommended view
  stays cached-only so it's never a wall of blanks. Cape queries only offer
  featured names in `FEATURED_CAPE_NAMES`.
- `_start_featured_prefetch` now fetches in batches of 5, repainting after
  each, until all featured are cached or a pass makes no progress (offline /
  dead name) - the old gate stopped after ~6 and left search thin.

### Preview rendering
`_ensure_previews` now renders the skin body at scale=3 (48x96) and the cape
back at scale=6 (60x96) — exactly the tile sizes the grid draws — so Flet stops
rescaling pixel art and tiles read crisp. Cache paths are `_v2`. Also
`set_active`/`set_active_cape` now refresh the grid so uploads immediately show
as Installed.

## Verification
- `tools/test_gallery.py` 42/42 (added: fuzzy, suggest, featured tags, uncached
  search suggestions, cape-search cape-owner filtering).
- `tools/test_ui_smoke.py` 79/79 (added: one-search-box, pane flip, uncached
  recommendation renders).
- `tools/test_capes.py` 14/14, `test_net.py` 19, `test_mod_store.py` 21,
  `test_modpacks.py` 51 — all green. py_compile on every edited file.

## Gotchas
- Keep `list_gallery_*` network-free; only `prefetch_featured`/`load_player`
  hit the network, and only off the UI thread.
- `_ACTIVE_GALLERY_REFRESH["fn"]` is replaced on every rebuild — anything
  holding a stale closure is a leak.
- The Mojang name API is exact-match; always go through `suggest_player` before
  showing a hard "not found".
