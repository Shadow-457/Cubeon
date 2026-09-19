# 2026-09-11 - removed the real-player-head hat fetching system

## What I changed
The Cosmetics pane had a "Wear a real player's head as a hat (Minecraft
username)" fetch row. Removed the whole feature (hats themselves - the
earnable pixel hats - are untouched).

- `ui/skin_tab.py`: deleted `hat_real_field` / `wear_real_head` /
  `hat_real_btn` / `hat_real_row` and its entry in the cosmetics pane. The
  pane is now just the hat search + earnable hat grid + status.
- `cubeon/gallery.py`: removed `install_gallery_hat`, `list_gallery_hats`,
  `_build_head_hat`; `load_player` no longer returns `has_head`/`head_preview`
  and `_ensure_previews` no longer emits a head preview. Dropped the now-unused
  `_cosmetics` import (and a dead `os.makedirs` line after a `return`).
- `cubeon/cosmetics.py`: removed `add_image_hat` + `HATS_IMAGES_DIR` and the
  image branch in `hat_template` - hats are drawn pixel art only now.
- `cubeon/remotes.py`: removed `MC_HEADS` and the mc-heads.net download;
  profiles/snapshots no longer carry `has_head`/`head_path`.
- `launcher_core.py`: dropped the `list_gallery_hats`/`install_gallery_hat`
  re-exports.
- `tools/test_gallery.py`: dropped the head fixture/handler + hat-wearing
  checks (42 -> 38 checks).

## Verification
- `test_gallery` 38/38, `test_ui_smoke` 82/82, `test_capes` 14/14,
  `test_net` 19, `test_mod_store` 21, `test_modpacks` 51, `test_skins_net`
  PASS, `test_milestones` 41/41.
- `py_compile` on all edited modules.
- Repo-wide grep: no `install_gallery_hat` / `add_image_hat` / `head_path` /
  `has_head` / `mc-heads` / `hat_real` references left outside docs.
- module-map.md Follow-up 21 updated (remotes source list, cosmetics note,
  tests count, hat honest-limit).
