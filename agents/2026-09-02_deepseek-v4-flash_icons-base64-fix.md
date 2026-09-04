# Icons broken everywhere — Flet can't load absolute cache paths

## What was wrong (two bugs stacked)
1. `get_mod_icons` was missing from `launcher_core.py`'s `cubeon.mods` import
   list → installed-mod icon patch always hit `AttributeError`. (Fixed earlier
   same session.)
2. Bigger one: the disk icon cache returns an **absolute local path**
   (`~/.cubeon_launcher/cache/icons/<sha>.webp`), and `ft.Image.src` in this
   Flet (0.86) only loads URLs or assets-dir-relative strings — a prior agent
   documented this exact finding in `ui/skin_tab.py` (~line 136) and worked
   around it with base64 for skin previews. So EVERY cached icon (browse rows,
   modpacks, resource packs/shaders, installed mods once art landed) rendered
   blank. Uncached icons still worked via remote URL, which is why the failure
   looked partial/random.

## Fix
Added `icons.src(url)` to `cubeon/icons.py`: returns the cached bytes
base64-encoded (the proven skin-preview pattern) when on disk, else the
original remote URL. Updated all icon call sites to use it:
- `ui/mods_tab.py`: `_icon_image()` (installed rows) + browse/recommended row
  (shared `build_browse_row`, covers mods + resource packs + shaders).
- `ui/modpacks_tab.py`: modpack browse row.
- `ui/server_tab.py`: plugin-market `_plugin_icon()` — was raw remote URL with
  no cache and no `error_content`; now prefetches, uses `icons.src()`, and has
  a glyph fallback.

## Notes for next agent
- Restart `python main.py` to pick it up. Already-downloaded icons (28 files in
  the cache dir) show instantly as base64; uncached ones show the remote URL on
  first view, then base64 after `prefetch()` files them.
- If the user STILL reports missing icons after this (specifically on a first
  view before any cache file exists), that would prove remote CDN URLs don't
  render in the client at all — then the fix is to swap icons in from prefetch
  like installed rows do (placeholder → async art), never pointing src at a
  network URL.
