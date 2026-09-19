# 2026-09-11 — True black + green palette, and Play card divider removal

## What I did
- **Play card dividers removed.** The Play hero card's two `pixel_divider()`
  calls (under the Mod loader, and above the action footer) are gone from
  `main.py`. The three-band structure is unchanged — the bands are just
  separated by explicit spacer heights now. The `profile` dialog still uses
  `pixel_divider()`; only the Play card lost its two.
- **Palette switched to the user's exact scheme.** Two places had to move
  together because the app's default palette comes from the *template* system,
  not `cubeon/theme.py`:
  - `templates/color_green.py` — rewritten to the exact scheme
    (`BG=#050505`, `TEXT=#DDF6D5`, `ACCENT=#46BA34`, `ACCENT_DIM=#2BAF00`,
    `ACCENT_DEEP=#052400`, ...).
  - `cubeon/theme.py` — the fallback (no-template) tokens mirror the same
    scheme, in case a build ever runs with `DEFAULT_COLOR_TEMPLATE=None`.
  - `cubeon/__init__.py` — `DEFAULT_COLOR_TEMPLATE` changed
    `"carbon"` -> `"green"`.
- **New `ACCENT_DEEP` token** (`#052400`, the user's secondary) holds the
  loader segmented-control thumb, replacing the previous `ACCENT_TINT_HI` wash.
  Added to `theme.py` (module-level only — NOT in `THEME`) and to the green
  template; `cubeon/color_templates._derive()` now derives it for templates
  that don't declare one (darkened `ACCENT_DIM`), so `--color2..7` still work.
- `ACCENT_TINT`/`ACCENT_TINT_HI` fractions aligned to 0.12/0.20 in both
  `theme.py` and the template deriver (they had drifted 0.10/0.18 vs 0.14/0.24).
- Removed the temporary `palette-preview.html` chooser after the user picked.
- **OG key-art banner under the Play card.** Added the user's
  `assets/titleimg.jpg` (2000x1000) directly beneath the hero card in
  `main.py`, full-width. Implementation note: the card is intentionally NOT
  stretched, so a bare `ft.Image` would have sized to intrinsic width; I wrapped
  it in a one-child `ft.Row` with the image Container `expand=True`, height 220,
  `BoxFit.COVER`, `ClipBehavior.ANTI_ALIAS`, 1px `CARD_BORDER`. Verified by
  screenshot tour (`tools/ux_capture.py`, xvfb): `01_tab_play.png` shows the
  banner edge-to-edge and the new palette live.

## Verification
- `python3 -m py_compile` clean on all touched files.
- Applied every template in-process and printed the ramp; all 7 derive a sane
  `ACCENT_DEEP` and green yields the exact requested hexes.
- `tools/test_ui_smoke.py` 97/97; `tools/test_friends_service.py` 213/213.
- Sweep green: test_friends 37, test_mod_bridge 119, test_mod_matrix 68,
  test_capes 14, test_invites 127, test_modpacks 51, test_mod_store 21,
  test_net 19, test_production 13, test_gallery 38,
  test_versions_profile_key 11, test_launch_indicator 11.

## Notes for the next agent
- If you touch the palette again, remember the *default* lives in
  `DEFAULT_COLOR_TEMPLATE` (`cubeon/__init__.py`), NOT `cubeon/theme.py`.
  `theme.py` is only the fallback when that constant is `None`.
- Module-map palette bullet + guide-ui loader-segment line updated.
