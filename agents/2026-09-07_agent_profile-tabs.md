# Profile area re-organized: Skin/Cosmetics/Cape sub-tabs — 2026-09-07

User ask: "make the profile area UI better organized? like the capes
cosmetics and skin section especially".

## What I did (ui/skin_tab.py only)
Replaced the one-long-scroll stack (In-Game Skin block, then divider, then
hat grid, then divider, then cape block) with an underline tab bar —
**Skin / Cosmetics / Cape** — built from `text_tab()` (cubeon/theme.py),
the same chrome the Mods tab uses for Mods/Packs/Shaders. One pane visible
at a time.

- Skin and Cape panes share a `_pane()` helper: fixed-width preview box on
  the left, [label + list + upload CTA + status] on the right.
- Cosmetics pane is the wide hat grid with its status line (no duplicate
  preview — the Skin pane's preview already composes the hat in).
- Pane state is a `{"id": ...}` dict mutated by closures (same pattern as
  Mods' active_content); `switch_pane()` swaps `pane_holder.content`.
- The old per-section `pixel_divider()` separators and the duplicate
  "Cape"/"Your Capes" labels are gone; notes stay as label tooltips.
- `pixel_divider` param still accepted (signature compatibility with
  main.py and the smoke test) but unused inside now.

## Test change (tools/test_ui_smoke.py)
"hat row renders earnable hat names" needed updating: hat names now live
in the non-default cosmetics pane, unreachable from the returned tree
until its tab is clicked. The test now finds the clickable control whose
subtree text is exactly "cosmetics" and clicks it (FakePage absorbs the
update), then asserts veteran/party present. Note: Flet's `.parent` is
unset until mount, so climbing from the Text control doesn't work headless
— subtree-text matching is the reliable way.

## Verification
- tools/test_ui_smoke.py: 46 passed, 0 failed (incl. the tab-click path).
- tools/test_milestones.py: 41 passed, 0 failed.
- Live launcher: painted (ui_painted_ok), zero tracebacks in the log.
  Gotcha hit during live runs: `** flet WARNING Timed out waiting for
  OpenGL frame (have 1x1)` while Minecraft is running — GPU contention on
  this box, NOT a code bug; window still paints (marker fires).

## Q&A baton for the next agent
The Profile tab's outer cards (header card + skin-section card) are still
built in main.py (`profile_tab` / `rebuild_skin_section()`); the tabs live
inside the second card. If you reorganize further, keep
`build_skin_section(**THEME, ...)`'s signature — the smoke test pins
DANGER as a required kwarg and main.py passes section_label/pixel_divider
explicitly.
