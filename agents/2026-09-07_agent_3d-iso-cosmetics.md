# 3D isometric cosmetics previews — 2026-09-07

User ask: "make the cosmetics 3d? like they are 2d in skin for rn".
Hats rendered as flat top+front face stacks; the main skin preview was a
flat front view. Shipped true 3D-looking previews, all pure PIL.

## What I did (cubeon/cosmetics.py)
- New `render_head_isometric(cfg, out, hat_id, zoom, pad)`: renders the
  player's head as a Minecraft-style 2:1 isometric cube — top + left +
  front faces sheared via PIL AFFINE dest->source transforms (NEAREST,
  fillcolor transparent), per-face light shading (1.0/0.8/0.62), hat
  template composited per face. Painter's order: sides then top.
- `render_hat_preview` now delegates to it (all 12 hats verified visually).
- `preview_composed_body` replaces the flat head with the iso cube (flat
  head band ERASED first — no doubled head) and extends the canvas upward
  for tall-hat headroom.
- ui/skin_tab.py: hat tiles 80x70 (cube aspect) instead of 48x96.

## Gotchas learned (also see code comments)
- First attempt drew per-cell polygons — wrong cell width (2s vs s) caused
  overhang slivers past the cube edge. AFFINE whole-face transforms are
  seam-free and simpler; BILINEAR bleeds edge pixels, must use NEAREST +
  fillcolor=(0,0,0,0).
- Head faces shown: head's LEFT (sheet 16,8) and FRONT (8,8); hat template
  mirrors head layout so same crops work for both layers.
- Tile PNGs in skins/ only refresh when the Skin tab is (re)built — stale
  sizes on disk after a code change are not evidence of old code running;
  check process start time (`ps -o lstart= -p PID`).

## Verification
- tools/test_milestones.py: 58 passed, 0 failed (new section 5b: geometry
  aspect contract, front-face features visible, unknown-hat fallback, all
  12 hat previews non-blank, composed preview headroom).
- tools/test_ui_smoke.py: 46 passed, 0 failed.
- Live launcher: painted, 0 tracebacks; fresh 172x132 3D tiles rendered
  into real HOME; main preview 128x266 with headroom.

## Q&A baton for the next agent
The iso renderer is head-only. If a full-body 3D preview is ever wanted,
extend the same AFFINE-shear approach per body part (torso 8x12x4, arms,
legs) — but note skins.py's flat renderer is load-bearing for the upload
preview path (render_preview_for falls back to it when no hat is worn).
