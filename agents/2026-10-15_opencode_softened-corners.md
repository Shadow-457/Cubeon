# 2026-10-15 — Softened the corners (RADIUS 2 → 8/12)

**Asked:** "can you make those sharp edges a bit circle so they feel good."

## What I did
The whole app's corner rounding is one token family in `cubeon/theme.py`, so the
change is three numbers, not hundreds of call sites:

| token | was | now | used for |
|---|---|---|---|
| `RADIUS` | 2 | **8** | buttons, inputs, chips, nav items, small elements |
| `RADIUS_LG` | 2 | **12** | cards, dialogs, large panels |
| `RADIUS_PILL` | 2 | **999** | (defined, no live call site) |
| `RADIUS_NONE` | 0 | 0 | flush insets: progress bars, dividers, image edges |

`block()` defaults to `RADIUS`, so Flet's own controls (dialogs, buttons,
chips, cards) follow automatically through `apply_page_theme`. No call site
changed.

I deliberately left the handful of hardcoded radii that are *supposed* to be
that shape: the pixel-art confetti particles in `ui/seasonal_ui.py` (2px — they
are pixels), the connection dot in `ui/chat_tab.py` (4px on an 8px box = a
circle) and its unread badge (9px). Version art still uses its own
`ART_RADIUS = 12`.

Also updated the code comments that called the design "blocky"/"squared off"
(theme.py design preamble, `card()`, `apply_page_theme()`, the import comments
in `ui/skin_tab.py`, `ui/modpacks_tab.py`, `ui/mods_tab.py`, and the two
`ART_RADIUS` notes) so the docs don't lie. `RADIUS_PILL` is now genuinely
round instead of "blocky like everything else".

## Verified
- `.venv-build/bin/python -m py_compile main.py cubeon/theme.py ui/versions.py` → OK
- `tools/test_ui_smoke.py` → **207 passed, 0 failed**
- `tools/test_mega_smoke.py --suites` → **42 passed, 0 failed** (incl. the
  headless build-every-tab suite)
- No test anywhere pins a radius value (`grep -rn RADIUS tools/` → nothing),
  so this is a pure token change.

## Note
Subjective/visual — the numbers (8/12) are my pick for "a bit rounder, not
pill-shaped". Easy to nudge: the tokens are the only knob.
