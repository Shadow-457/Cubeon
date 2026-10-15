# KeyHUD merged into one jar per Minecraft version, progress UX, and the benchmarks page

- **Agent:** opencode (DeepSeek V4.1 Flash Free)
- **Date:** 2026-10-16
- **Task:** finish the KeyHUD -> Cubeon Client merge the previous note left paused
  (one `cubeon-client` jar per Minecraft version, 1.20 -> 26.3), fix the download
  and install progress UX, and publish the FPS report as a site page.

## 1. The merge (the paused work, finished)

- `mod/brackets.json` is the single source of truth: **24 brackets**, 1.20 -> 26.3,
  consecutive `min`/`below`, newest open-ended (`>=26.3`). It is read by both
  `mod/build.gradle` and `cubeon/cubeonfriends.py`.
- The line between the two halves is a **namespace** change, not an API change:
  1.20-1.21.11 ship obfuscated, so those brackets use **Yarn** (loom remaps to
  intermediary); 26.x ships unobfuscated, so they apply loom's **no-remap marker**
  plugin `net.fabricmc.fabric-loom` and declare no mappings.
- Shared `mod/src/main/java` is now Minecraft-free. Per-bracket overlays:
  `api-yarn` / `api-mojang` (the four Cubeon sources that touch Minecraft) and
  **seven** `hud-*` copies (1.20, 1.20.1, 1.20.2, 1.21.9, 26.1, 26.2, 26.3).
- Bytecode is Java 17 for every bracket (the mixin config declares JAVA_17, and
  Mixin refuses a newer class file); the *toolchain* is 17 / 21 / 25 per bracket
  because javac has to read that Minecraft's class files.
- **Fabric API is `recommends`, never `depends`** - a missing API must cost the
  HUD, not the game. `KeyHudClient.onInitializeClient()` is wrapped in
  `try/catch (Throwable)` in every HUD overlay, and the launcher installs Fabric
  API itself (`cubeonfriends.ensure_fabric_api`, local check first, called from
  `cubeon/launch.py` after the mod jar is in place).
- `KeyHud/` stays git-ignored (732 MB of dead source); `mod/` is the source of
  truth now.
- **The 26.3 gotcha that cost the first attempt:** 26.1/26.2 call the keybind
  type `InputConstants.Type.KEYSYM`; 26.3 renamed it to `KEYBOARD` and dropped
  `SCANCODE`. A single 26.2-era overlay cannot serve both, so 26.3 got its own
  `hud-26.3`. I confirmed it with `javap` on the real jars (26.2 still has
  `KEYSYM`) rather than guessing from the changelog.

## 2. Download / install progress UX

- `cubeon/eta.py` - a **measured** time-left. mll reports file counts per phase,
  mod installs report file units and content downloads report bytes, so there is
  no single size to divide by; the estimator samples the fraction over time
  instead (silent until ~2 s and >=1% movement, rate from the last 30 s, history
  dropped when the fraction jumps backwards = a new phase, stops after a 15 s
  stall, capped at 6 h).
- `cubeon/status_text.py` + `_FriendlyStatus` in `cubeon/versions.py` - the asset
  phase names every file by its sha1, so the status line read
  "Download c4dbabc820f04ba685694c63359429b22e3a62b5". That wall of hex is the
  "memory address" the user reported. It now reads "Downloading game assets
  (12/345)". The match is deliberately narrow (a bare 40-hex, or a 16+ hex run
  with no extension) so no real library name is swallowed.
- Object reprs (`<... at 0x...>`) are stripped where a status or error is built
  (`cubeon/net.py` + the UI setters). Narrow on purpose: hashes and UUIDs are
  left alone because integrity errors need them.

## 3. "It prepares for a long time" on a first install

Two silent waits, both fixed at the source:

1. mll's `install_minecraft_version()` answers a missing
   `versions/<id>/<id>.json` with a bare, un-timed, un-retried `requests.get()`
   of Mojang's ~4 MB manifest - before its first progress callback. Fixed with
   `_seed_version_json()` in `cubeon/versions.py`: Cubeon already keeps that
   manifest, so the one small json is fetched here, with a real status line and
   real progress. Strictly best-effort (mll's own lookup is the fallback), and a
   cancel is re-raised rather than swallowed.
2. A background prefetch of the whole version holds the per-version install lock,
   so a Play/Install click waited behind it on a frozen "Preparing". Fixed in
   `main.py`: the lock is acquired in 0.25 s slices and the progress row is
   repainted from `_prefetch_view` via `_adopt_prefetch`.

## 4. The benchmarks page

`web/benchmarks.html` (served at `/benchmarks`) publishes
`benchmarks/Minecraft_FPS_Report-1.pdf`: Cubeon vs SKLauncher vs FastClient on
Minecraft 1.21.11, FPS counted frame by frame from screen recordings. Four CSS
bar charts + the full stats table, the PDF itself as
`web/assets/Minecraft-FPS-Report.pdf`, and a "Read it honestly" section that
keeps every caveat. "Benchmarks" joined the navbar on all 15 pages;
`docs/performance/fps-benchmark-2026-10-15.md` records the numbers so the PDF is
quotable. Details in `agents/docs/module-map.md`.

## How I verified

- All 24 brackets built through Gradle/loom and passed
  `tools/build_mod_jars.py`'s `verify()` (required entries present, no `${...}`
  placeholders, a real `minecraft` range). Rebuilt 1.20.5/1.20.6 with `jdk: 21`
  after their original `javac` failure.
- Suites: `test_mod_matrix` 230, `test_mod_compile`, `test_eta` 30,
  `test_install_prepare` 7, `test_install_cancel` 5, `test_launch_fixes` 113,
  `test_mod_install_progress` 42, `test_net` 42, `test_ui_smoke`,
  `test_web_download_count` 76, plus a full CI mirror: **55 suites, 0 failures**.
- Site: every page's tags balance, every local link resolves, and the page was
  rendered at 1280px and 500px in headless Chrome and checked by eye.
- `javap` on the real 26.1 / 26.2 / 26.3 Minecraft jars for the rename above.

## Notes for the next agent

- **Do not kill a running `build_mod_jars.py`.** The Gradle daemon survives the
  client and keeps holding the `fabric-loom` cache lock; the next build then
  waits forever on a pid that no longer exists. Kill the daemon
  (`pkill -f GradleDaemon`) before retrying.
- Gradle must run on **JVM 25+**; `build_mod_jars.py` finds a suitable JDK itself.
  One bracket: `python3 tools/build_mod_jars.py 1.20.5`.
- **CI does not build mod jars.** The 24 real Gradle builds are the HUD's only
  compile check - `test_mod_compile.py` stub-compiles the `api-mojang` overlay
  only, so it would not have caught the `KEYSYM`/`KEYBOARD` rename.
- `assets/jars/` holds the 24 jars; `find_jar` resolves the exact generated name
  from `brackets.json`, so a stale jar can never be selected.

## Question for the next agent

The benchmark is honest but not a lab test - each launcher ran in a different
spot in the world, and F3 was on for two of the three. Is it worth re-recording
all three with identical settings, the same world and the same camera path, and
publishing that next to this one? The page already says it would be stronger.
