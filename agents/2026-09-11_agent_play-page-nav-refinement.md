# 2026-09-11 - Play page + top-nav refinement (hierarchy / spacing pass)

## What changed (main.py only)
A precision pass on the Play page and top navigation - no functionality, no
backend, no new widgets.

**Play tab structure** (`play_tab`, ~L2865):
- Page heading is `"Play"` + `"Launch Minecraft your way."` (was the long
  "Launch offline / cracked ..." line).
- The hero card is now three labelled bands separated by `pixel_divider()`:
  INSTANCE HEADER (emblem, title, loader chip + version meta, rename/delete)
  -> CONFIGURATION (Game version | Account on one row, then Mod loader)
  -> ACTION FOOTER (`update_version_btn` left, PLAY right at 280px).
- Card compacted: `glass_card(hero=True, padding=20)`, inner `spacing=0` with
  explicit spacers; hero title 26 -> 22 (below the page heading in the type
  hierarchy); emblem 64 -> 56.
- Fields: `username_field` / `version_dropdown` / `version_dropdown_button`
  all 48px (were 52) so Account + Game version read as a matched pair.

**Loader selector**: selected segment is a subtle dark-green thumb
(`#33431E`) + green semibold label; the per-segment dot is explicitly only an
"installed" marker, not the selection affordance.

**PLAY button**: clean UI font (not Minecraftia) + W_700, icon 18, text 15,
`vertical_alignment=CENTER`, padding v14/h20. `set_button_mode` states
unchanged.

**Top nav**: icon-only buttons 22 -> 21px icons, tighter padding/spacing; the
active tab now gets an `ACCENT_TINT` wash in addition to the green underline
(`_style_nav_button` top-icon branch). Account/Settings icons 22px, both with
a hover color style.

**Icons**: rename/delete 20 -> 18px; delete is `TEXT_DIM` at rest and `DANGER`
only under the cursor; version dropdown arrow 20 -> 18. `update_version_btn`
gained an `ACCENT_TINT` hover via `theme.attach_hover`.

## Version-string check (no change made)
The suspected `1.21.11` -> `1.21.1` mismatch is not a bug. This machine's
`~/.minecraft/versions/` genuinely contains `1.21.11`, `1.21.8`, `26.1.2`, each
with a matching JSON `id`. `hero_version_text` shows the raw id and
`extract_mc_version` is non-destructive. Left the data alone.

## Verification
- `tools/test_ui_smoke.py` 97/97, `tools/test_friends_service.py` 213/213.
- Sweep green: test_milestones 50, test_gallery 38, test_launch_indicator 11,
  test_versions_profile_key 11, test_capes 14, test_friends 37,
  test_mod_bridge 119, test_mod_matrix 68, test_mod_store 21, test_modpacks 51,
  test_net 19, test_invites 127, test_production 13.
- Docs: module-map.md (last-updated + Play composition/nav/version-string
  bullets + config band order) and guide-ui-modules.md (Play tab section).

## Note for next agent
The stale comment that used to claim "JUMP BACK IN / INSTALLED VERSIONS" live
under the hero was wrong - there is no such content; the blank region below the
card is just unused canvas and the card is deliberately NOT stretched to fill
it. If you ever add real content there, put it below the card, not inside it.
