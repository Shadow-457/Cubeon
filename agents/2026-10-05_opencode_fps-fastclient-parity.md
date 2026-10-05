# FPS parity with FastClient: wider mod suite + frame-rate unlock + softer GC flags (2026-10-05)

- **Agent:** opencode (deepseek-v4-flash)
- **Task:** "it gives 3x as less than fastclient, i get 30-45 here and 120-170
  in fastclient — optimize this for best fps". User chose **all three levers**
  (mods + game options + JVM flags).

## Diagnosis (from the live install, not guessed)
- `~/.cubeon_minecraft/options.txt` had **`enableVsync:true`** and
  **`maxFps:70`**. On the user's 60Hz panel Vsync caps at 60 and snaps to ~30
  whenever a frame overruns the vblank — exactly the reported 30-45. This alone
  made any mod upgrade invisible.
- `~/.cubeon_launcher/mod_profiles/1.21.11-fabric` held only **Sodium 0.8.12 +
  Lithium** (the `perf_mods.PERF_MOD_SLUGS` pair from 2026-09-11). FastClient's
  "2x FPS" is a *suite* of culling/per-frame mods, which is what actually lifts
  a CPU-bound PvP client (this box: Xeon E5-1650 + RX 580, so CPU-bound).
- `perf_mods._present()` skip-if-present also pins the old Sodium (0.8.15 is
  out) — left as-is on purpose: auto-updating a mod that Iris pairs with is a
  compat risk the maintainers deliberately avoid.

## Changes
1. **`cubeon/perf_mods.py`** — widened from 2 to 9 client FPS mods via a
   `PERF_MODS = (slug, project_id, label)` table: Sodium, Lithium,
   **ImmediatelyFast, EntityCulling, MoreCulling, BadOptimizations, Krypton,
   ThreadTweak, Dynamic FPS**. Sodium/Lithium stay first (load-bearing pair if a
   download is cut short). All 9 confirmed to have 1.21.11 Fabric builds on
   Modrinth before adding. `download_mod` now also records `project_id`.
2. **`cubeon/game_options.py` (new)** — `unlock_frame_rate()` flips ONLY
   `enableVsync:false` and `maxFps:260` in `MINECRAFT_DIR/options.txt`. Atomic
   (tmp + `os.replace`), idempotent, preserves line endings, only edits keys that
   already exist, leaves render distance/graphics/packs/shaders completely alone
   (same rule as `content.py`). Called in `launch_game` right after
   `perf_mods.ensure_installed`, gated by the same `perf_mods_enabled`
   (config-only, no Settings toggle — the user removed that).
3. **`cubeon/launch.py` `CLIENT_JVM_FLAGS`** — kept Aikar-derived G1 but softened
   two values for a weak client CPU that shares cores between GC and the render
   thread: `MaxGCPauseMillis=200` (was 40; a 40ms goal makes G1 shrink young gen
   and young-GC far more often) and added `G1HeapWastePercent=5`. Also added
   `-Dorg.lwjgl.util.NoChecks=true`. Validated the exact flag list against the
   real `java` 21 (`/tmp/flagtest/T.class`), per the module-map rule.
4. **`cubeon/config.py`** — updated the `perf_mods_enabled` comment to match.

## Applied to the live install (user runs the Sep-24 AppImage, not the tree)
- `unlock_frame_rate()` run against the real `~/.cubeon_minecraft/options.txt`:
  `enableVsync:false`, `maxFps:260`.
- `perf_mods.ensure_installed("1.21.11", "fabric")` installed the 7 new jars
  into `mod_profiles/1.21.11-fabric` (Sodium/Lithium kept). The OLD launcher's
  `sync_mods_to_game` copies the whole profile, so these load on the next Play
  even before a rebuild. The *launcher-side* changes (JVM flags, auto-unlock,
  reinstall on other versions) need `pyinstaller Cubeon.spec` + reinstall the
  AppImage to take effect.

## Verification
- `tools/test_perf_mods.py` rewritten + extended: **34/0** (suite order,
  dedupe-by-every-identity, non-Fabric no-op, failure reporting, JVM flag
  assertions, and the options unlocker: only 2 keys, newline preserved, other
  options untouched, idempotent, missing-file safe, no invented keys).
- `tools/test_launch_fixes.py` **98/0**, `tools/test_ui_smoke.py` **166/0**,
  `tools/test_client_json.py` **40/0**, `tools/test_mod_store.py` **27/0**,
  `tools/test_mod_detail.py` **81/0**, `tools/test_production.py` **51/0**,
  `tools/test_mod_install_progress.py` **39/0**.

## For the next agent
- **Not measured in-game** (no display/session). The expected result is
  >60 FPS from the Vsync unlock alone; the culling mods are the rest. If the
  user still reports low FPS, ask for the **F3 pie chart / render-distance**
  next — the launcher side is now exhausted and it's a settings/CPU limit.
- **EntityCulling vs Wurst**: the user runs Wurst (a cheat client) on a PvP
  server. EntityCulling can hide culled entities from ESP/tracers. It was kept
  (FastClient bundles it) but is the first candidate to drop if ESP breaks.
- **Skip-if-present is intentional** — don't "fix" it into an auto-updater
  without sorting Iris/Sodium pairing first.
- Durable facts went into `agents/docs/module-map.md` (JVM FLAGS bullet, the
  `perf_mods.py`/`game_options.py`/`launch.py` table rows, and the FPS-boost
  bullets), not buried here.
