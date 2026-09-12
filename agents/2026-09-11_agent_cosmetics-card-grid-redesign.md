# 2026-09-11 - Cosmetics tab redesign: card grids replace the pager

## What I changed
The previous note added a one-row-per-page pager to the Skin/Cape Installed
panes. The user tried it and said it was "not good" - asked for a full
Cosmetics-tab redesign. Direction chosen: **scrollable card grid + previews**.

All in `ui/skin_tab.py`:

- **Deleted the pager entirely** - `_make_pager`, `_thumb_box`,
  `_skin_thumb_b64`, `_cape_thumb_b64`, `skin_pager_row`/`skin_pager_row`-sync,
  `_cape_pager_*`, `_skin_pager_render` / `_cape_pager_render`. No pager
  remains in the cosmetics tab.
- **`_owned_card(...)`**: one card builder used by both Installed panes -
  preview on top, name, optional sublabel, and a footer that is either an
  hover-revealed Use/Delete row or an outlined ACTIVE pill (active card gets
  the accent border). Built-in Cubeon cape passes `on_delete=None` (no delete).
- **`_grid_scroll(grid, height=290)`**: wraps a wrapping `ft.Row` grid in a
  fixed-height scrolling Column so a long list never stretches the tab.
- `skins_list_col` / `capes_list_col` are now `ft.Row(wrap=True, run_spacing=10)`
  grids; `_skin_card_b64` / `_cape_card_b64` render previews at scale=3.
- Hat grid (`hat_row`) wrapped in `_grid_scroll(..., height=290)` too, so all
  three panes share the same shape: stage left, scrolling card grid right.

## Follow-up the same day: "box in a box" -> Mods-tab theming
- Removed the tab's own bordered SURFACE card in `main.py`: `profile_tab` is now
  a plain `ft.Column([skin_section_container])` like Mods/Stats/Settings. That
  card was the outer half of the nested-box look.
- `ui/skin_tab.py` now imports `CARD_FILL`, `CARD_BORDER`, `ROW_HOVER`,
  `TEXT_FAINT` and paints interiors with the Mods-tab language: preview stages,
  gallery tiles, `_owned_card`, and hat tiles use translucent `CARD_FILL` +
  `CARD_BORDER` (no solid SURFACE/SURFACE_HI + hard borders), hover lifts to
  `ROW_HOVER`, selection washes with `ACCENT_TINT`, and the search fields use
  `CARD_FILL`/`CARD_BORDER` + `focused_border_color=ACCENT_DIM` + faint hints.
  The Use button is now an `ACCENT_TINT` wash with ACCENT text (Mods download
  style) instead of a solid ACCENT block.

## Verification
- `test_ui_smoke` 90/90. Updated 5b ("installed lists no longer paginate") and
  rewrote 5f ("installed skin card shows a real preview image", "installed
  skins flow as a wrapping card grid" - it now looks for the wrapping Row, not
  a one-child Column). Also fixed the stale SKIN GALLERY header comment at the
  top of the gallery block.
- `test_gallery` 38/38, `test_capes` 14/14, `test_milestones` 41/41,
  `test_net` 19, `test_mod_store` 21, `test_modpacks` 51 - all green.
  `py_compile` clean on `ui/skin_tab.py main.py`.
- NOTE: `test_milestones.py` is flaky (~1 in 3 runs) on the pre-existing
  "no unlock -> no sync POST at all" check - it sometimes sees 1 stray POST.
  It is unrelated to this change (skin_tab is not imported there) and is not
  a regression from the redesign.
- module-map.md updated: paging note replaced by the card-grid note; Tests
  list updated; Cosmetics-pane note now mentions `_grid_scroll`.

## Note for next agent
The prior diary note (`2026-09-11_agent_installed-preview-paging.md`) is now
history - it describes the pager that was removed. Do NOT resurrect it. The
living truth is the "Installed lists show previews as a wrapping card grid"
bullet in `agents/docs/module-map.md`.
