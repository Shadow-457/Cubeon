# 2026-10-14 — Max FPS mode: the game's own speed-only options at launch

## Ask
"bro i need twice as much fps gng" — following the six-mod perf suite widened
earlier the same day.

## What changed
- `cubeon/game_options.py`: new `_set_options()` shared applier (the exact
  unlock_frame_rate contract: existing keys only, value-diff-only writes,
  atomic, idempotent, never raises) + `apply_max_fps()` setting
  MAX_FPS_OPTIONS = graphicsMode:0, particles:0, entityShadows:false,
  entityDistanceScaling:0.75, biomeBlendRadius:0, syncChunkWrites:false.
  unlock_frame_rate() now delegates to the same applier (one code path).
- `cubeon/config.py`: `max_fps_enabled` (default True).
- `cubeon/launch.py`: applies Max FPS right after the frame unlock, only when
  the setting is on.
- Settings toggle "Max FPS mode" (main.py builds `max_fps_cb`,
  ui/settings_tab.py arranges it under "Cubeon extras in-game").
- renderDistance/simulationDistance/mipmap/smooth lighting/clouds/leaves/water
  are deliberately NEVER touched - they are the player's visual choices.

## Why these six
They are pure engine-work savers with no gameplay cost. GraphicsMode Fast is
the biggest remaining lever after Sodium. syncChunkWrites:false moves chunk
saves off the render thread (stutter). The visual-choice options are excluded
on purpose.

## Verification
- tools/test_perf_mods.py 62/62 (new section 10: values, idempotency,
  renderDistance untouched, fresh-options.txt no-invented-keys).
- test_ui_smoke 182/182 (Settings tab renders with the new row);
  mega_smoke --static 16/16; --suites green except the known
  environment-bound wedge_watchdog.
