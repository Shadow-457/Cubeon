# 2026-10-14 — FPS: perf suite widened to six mods ("twice as much FPS")

## Ask
"i need twice as much as any launcher fps i need more fps please"

## What changed
- `cubeon/perf_mods.py` PERF_MODS is now SIX mods (an earlier interrupted run
  had made the code change but left the tests stale — 5 FAILs; I verified the
  Modrinth project IDs live, adopted the change, and fixed the tests):
  Sodium (renderer), Lithium (tick/game logic), ImmediatelyFast (HUD/text),
  Entity Culling, FerriteCore (memory/GC), More Culling.
- On top of the suite, already in place and unchanged:
  frame-rate unlock (`enableVsync:false`, `maxFps:260` via game_options.py),
  CPU-aware G1GC tuning + AlwaysPreTouch gating (launch.py), and the
  unconditional EntityCulling config sanitize.
- `tools/test_perf_mods.py` updated to the suite (55/55): install order,
  hand-dropped lithium kept, retired-ID check now uses badoptimizations,
  prune section targets krypton/threadtweak.
- module-map FPS invariant updated (six mods supersede Sodium-only).
- Honest framing for the user: "twice" depends on where their current frames
  are lost (CPU-bound vanilla gains the most; a GPU-bound or shader-bound
  setup gains less). This is the proven max-FPS mod stack for Fabric/Quilt;
  Forge/NeoForge get nothing (suite is Fabric-only by design).

## Verification
- test_perf_mods.py 55/55; mega_smoke --static 16/16; test_ui_smoke 182/182.
- Modrinth IDs checked live: all six resolve to the right projects.
