# Fix: EntityCulling crash, then "Sodium only" + CPU-aware JVM flags (2026-10-05)

- **Agent:** opencode (deepseek-v4-flash)
- **Report:** "my game seems to keep crashing after a ai editing the launcher",
  then (after that was fixed) "run it with only 2c/2t and 4gb ram", then
  "70-80 fps but 1 fps when entering a world/server, check jvm flags".

## Diagnosis (from the crash reports, not guessed)
- The two newest reports
  (`~/.cubeon_minecraft/crash-reports/crash-2026-10-05_16.52/16.53-client.txt`)
  are identical: `NullPointerException: Cannot invoke "String.indexOf(int)"
  because "$$0" is null`, thrown on the **Render thread** from
  `entityculling.EntityCullingModBase.clientTick` -> `transition.GeneralUtil
  .getResourceLocation` -> `ResourceLocation.<init>`, at **0 client ticks** —
  i.e. the window never reached the menu.
- `javap` of the installed `entityculling-fabric-1.11.2` confirmed `clientTick`
  iterates `Config.blockEntityWhitelist` and parses each entry as a
  ResourceLocation. The user's `config/entityculling.json` had `null` in
  `blockEntityWhitelist` (and `""` in `entityWhitelist`), so the first entry
  after `minecraft:beacon` NPE'd.
- The compiled 1.11.2 defaults and `ConfigUpgrader` contain only real ids and
  never add a null — so the bad entries were a **legacy config** carried
  forward. Nothing in 1.11.2 re-adds them, so cleaning the file is durable.
- The JVM flags / `options.txt` unlock from the previous commit were **not**
  involved (the crash report lists them fine).

## Changes
1. `cubeon/perf_mods.py` — added `sanitize_entityculling_config()` (strips
   `null`/blank entries from `blockEntityWhitelist`, `entityWhitelist`,
   `tickCullingWhitelist`; preserves every other key and all valid entries;
   atomic + idempotent; never raises).
2. `cubeon/launch.py` — `launch_game` calls it **unconditionally** (even with
   `perf_mods_enabled` off), since a stale broken config would keep crashing an
   install the user already has.
3. `tools/test_perf_mods.py` §8 — 8 checks (null/empty/blank removal, valid +
   unrelated keys preserved, idempotent, missing/non-object safe). **42/0.**
4. `agents/docs/module-map.md` — durable invariant + `perf_mods.py` table row.

## Applied to the live install
- Ran `sanitize_entityculling_config()` against the real
  `~/.cubeon_minecraft/config/entityculling.json`: **removed 2** entries
  (`null`, `""`). The game should now boot. Launcher-side self-heal needs a
  rebuild/reinstall to run on its own.

## Verification
- `tools/test_perf_mods.py` **55/0**, `tools/test_launch_fixes.py` **98/0**,
  `tools/test_ui_smoke.py` **166/0**, `tools/test_production.py` **51/0**,
  `tools/test_mod_store.py` **27/0**, `test_client_json` 40/0,
  `test_mod_detail` 81/0, `test_mod_install_progress` 39/0.

## Part 2 — narrowed to Sodium, made flags CPU-aware
- **"No more mods, just optimize Minecraft"**: `PERF_MODS` cut from 9 to
  **Sodium only** (the others added little and each carried crash surface).
  New `RETIRED_PERF_MODS` + `prune_retired_perf_mods()` deletes the 8 retired
  mods from a profile that has them — matching ONLY the recorded slug/project
  id, so the user's own mods (Iris, Wurst, Xaero, Jade…) survive. Verified on
  the live profile: removed exactly the 8, kept everything else.
- **CPU-aware flags** (user ran `taskset -c 0,1`, 2c/2t): `client_jvm_flags()`
  reads `os.sched_getaffinity`; ≤4 CPUs → smaller young gen (20/30%) and
  `MaxGCPauseMillis=100`, else Aikar's 30/40/200. `G1HeapRegionSize` 16M→8M.
  Added RAM-gated `-XX:+AlwaysPreTouch` (only ≥8 GB RAM and heap ≤ half).
  Validated the full set against real Java 21 (all accepted).
- Tests: `test_perf_mods` §1/2/6/9 rewritten for Sodium-only + prune + flags.

## What was measured on the live 2c/4GB run (the real answer)
- **In-world: 70-80 FPS** (up from 30-45 originally) — the Vsync unlock +
  Sodium + CPU flags work.
- **World/server entry: ~1 FPS for ~10-15 s**, then recovers. NOT a flag bug:
  the process sits at ~152% CPU (both cores full); the log shows
  `Preparing spawn area` took **11,171 ms**, then `Can't keep up! Running
  2061ms or 41 ticks behind` twice. Heap was healthy (1.5 GB used of 4 GB, 1 GB
  young, ~175 MB/s allocation during load) → CPU-bound worldgen + chunk-mesh
  build, not GC. **No JVM flag fixes this**; the only levers are render/
  simulation distance or more cores. The user said "idk" when offered the
  distance change, so nothing was forced (their earlier choice was "leave my
  settings").

## For the next agent
- **Not verified in-game by me** for the crash fix (no display here until the
  user ran it); the live config was repaired by hand and the source was then
  run by the user, who confirmed 70-80 FPS.
- The repo is still mid-rebase (`added bugs` stopped on a binary conflict in
  `assets/jars/cubeon-client-1.0.0+mc26.jar`). Left untouched — do not
  `git rebase --continue` without resolving that jar intentionally.
- If world-entry FPS comes up again, do not chase it in flags — it is 2-core
  worldgen. Point at render/simulation distance.
