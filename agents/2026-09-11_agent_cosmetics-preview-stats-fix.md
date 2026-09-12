# 2026-09-11 - cosmetics preview stage + stats playtime fix

## What I changed
Two user reports plus a self-review.

- **Stats "Time in game" always 0 (bug)**: `main.py`'s `on_exit` called
  `core.add_play_seconds(...)`, but `launcher_core` re-exports the function
  as `milestones_add_play_seconds` - so every session raised
  `AttributeError`, silently swallowed by `except Exception: pass`.
  Fixed the call site to `core.milestones_add_play_seconds(...)`.
- **Cosmetics pane, less text / more preview**: `ui/skin_tab.py` now leads
  the pane with a big live stage (`hat_preview` + `hat_preview_caption`,
  painted by `render_hat_stage()` through `core.preview_composed_body`),
  same two-column shape as Skin/Cape. Locked tiles gained a mini
  `ft.ProgressBar` (`hat_progress()`) instead of only a text tooltip; the
  tooltip uses the shortened `hat_earn_hint`. Dropped the always-on
  "Wearing X." line - `hat_status` hides unless it holds a real message.
- **Tests**: `tools/test_ui_smoke.py` gained the playtime-re-export checks,
  a real 3661s accumulation check, and a "cosmetics pane is preview-based"
  check (stage image + locked progress bars). 82 -> 86.

## Verification
- `test_ui_smoke` 86/86, `test_gallery` 38/38, `test_capes` 14/14,
  `test_milestones` 41/41, `test_net` 19, `test_mod_store` 21,
  `test_modpacks` 51, `test_skins_net` PASS.
- `py_compile` clean on `main.py ui/skin_tab.py`.
- Manually confirmed `core.preview_composed_body` renders real bytes in a
  sandbox home.
- module-map.md Follow-up 21 + the Stats tab note updated with the playtime
  re-export gotcha and the preview-based cosmetics anatomy.

## Note for next agent
I could not find a checked checklist / TODO file in the repo - the "todos"
the user mentioned are almost certainly the live session todo list. Kept the
session list accurate; if there is meant to be a persistent task list, it
needs a home.
