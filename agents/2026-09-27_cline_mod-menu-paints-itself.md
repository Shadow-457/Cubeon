# The mod menu paints itself (2026-09-27) — REWRITE of the same day's first attempt

- **Agent:** Cline
- **Date:** 2026-09-27
- **Task:** The first mod menu was rejected: *"this is shit man i didnt asked
  you to make it minecraft looking and this is shit"*, with a screenshot of
  grey vanilla buttons in a ragged grid.

## What was actually wrong
Not a bug — a design decision. The first `ModuleMenuScreen` was built entirely
from vanilla `Button`/`EditBox` widgets, and I chose that because avoiding any
custom drawing is what lets one jar serve both Minecraft brackets. It worked,
compiled everywhere, and looked like a Minecraft options screen.

**I had the reference screenshot the whole time and built the one thing that
was not asked for.** "Don't break the cross-version build" is a real
constraint; it is not a reason to ship something that looks wrong.

The second problem in the screenshot was layout, not style: a hard-coded
two-column 150px grid with the toggle *outside* the card, so the screen read
as three loose columns instead of cards with a state.

## The fix
The menu now draws itself. The split is deliberately small:

- `MenuPaint` (shared interface): just `fill` and `text`. Both were verified to
  exist in 1.20.1 and 26.1.2 — `GuiGraphics.fill/drawString` and
  `GuiGraphicsExtractor.fill/text`, same shapes.
- `MenuPaintImpl` — one tiny implementation per `java-overlay-*`, adapting its
  own graphics type. That is the ONLY per-bracket menu code.
- `MenuPainter` (shared): the entire look. Panel, header, tab pills, cards,
  borders, status bars, hover highlight, text clipping. Every shape is built
  from axis-aligned `fill` calls, including the rounded corners (stepped corner
  bevels), so nothing in it is version-specific.
- `MenuPaintMixin` (per bracket, same FQN, registered in the mixin config):
  1.20-1.21 injects `Screen.render(GuiGraphics, ...)`, 26.x injects
  `Screen.extractRenderState(GuiGraphicsExtractor, ...)`. Unavoidable — the two
  signatures are unrelated — and now the *only* per-bracket screen hook.
- `ModuleMenuScreen` keeps the logic and the layout maths: panel size derived
  from the screen, column count derived from the panel width, hit targets,
  settings.

## The details that fix the screenshot
- **The grid is derived, not hard-coded.**
  `cols = (panelW - 20) / (CARD_W + GAP)`, cards centred. No more ragged
  columns at any window size or GUI scale.
- **The status bar is INSIDE the card**, bottom-left, green when on. It was
  floating to the right of the card before.
- `MenuPainter.clip()` truncates titles and descriptions with an ellipsis
  instead of letting them run into the card edge.

## One constraint worth keeping
**Opaque colours only.** 26.x's extractor has no alpha `fill` at all, so a
translucent panel would render correctly on 1.20-1.21 and as a solid block on
26. The palette is deliberately all-opaque so both brackets look identical.

## Verification
- `test_mod_compile` — all sources compile clean, wiring guard green (it caught
  that `MenuPaintMixin` is per-bracket and needed a `REQUIRED_ENTRIES` entry).
- `test_mod_bridge` **164/0** (framework tests unaffected by the rewrite).
- `mega --static` 15/0.
- **Both jars rebuilt and verified** to contain `MenuPainter`, `MenuPaintImpl`,
  `MenuPaintMixin` and `ModuleMenuScreen`. The 26 build is the real proof the
  extractor path compiles — the stub only covers the 1.20-1.21 overlay.

## For the next agent
- **Still never seen in-game.** No display. The layout maths and the fill/text
  calls are verified, but the *painted result* is not. This is the second
  rewrite of this screen, and the first one anyone has actually looked at is
  this one — if the spacing still looks off, that is a `layout()` tweak, not
  a rewrite.
- There is no search box in this version. The first build had one, but a
  painted EditBox would need a text field in the shared painter as well; I left
  it out rather than ship a half-styled one. The category tabs cover filtering
  for now.
- Durable facts went into `agents/docs/module-map.md` ("The mod menu PAINTS
  itself"), not into this note.