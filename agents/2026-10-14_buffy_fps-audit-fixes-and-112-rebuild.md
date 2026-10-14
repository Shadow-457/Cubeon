# 2026-10-14 — FPS audit fixes applied, website claims corrected, 1.1.2 binaries rebuilt

Follows `agents/2026-10-14_opencode_performance-bugs-audit.md`. That document
was research-only ("NO code changed"); this one applies it.

## A. `cubeon/game_options.py` — Max FPS mode

* **A1 `particles`** — `"0"` was ALL, not minimal (the value is the enum *id*:
  ALL=0, DECREASED=1, MINIMAL=2). Now `"2"`. Max FPS mode had been *maximising*
  particles.
* **A2 `graphicsMode` → `graphicsPreset`** — `graphicsMode` survives only in a
  legacy `DataFixer` (`bph`), so writing it was a silent no-op and the "biggest
  lever" never fired. The live key is `graphicsPreset`, and the value must be
  written QUOTED (`"fast"`) because it is a string option.
* **A3 `_set_options` quoting/idempotency** — it compared
  `raw.strip().strip('"')` but wrote `f"{key}:{value}"` verbatim, so a quoted
  value never matched and the file was rewritten (and reported as "changed") on
  **every** launch. It now compares the file's RAW text against the exact string
  it would write, so a quoted value round-trips and the write is idempotent.
* **A4 `ao:false`** — ambient occlusion was the last fast-preset default still
  on; it is real terrain-shading/meshing work.
* **A5 tests** — `tools/test_perf_mods.py` section 10 rewritten to the live key
  and to MINIMAL particles, plus two new checks: a bare (unquoted) string value
  is normalised quoted **once** and then left alone.

## B. `cubeon/launch.py` — Aikar's *server* GC set on a *client*

* **B1 `-Xms == -Xmx`** — that committed the whole heap up front (F3
  "Allocated: 100%") and pinned RSS for the session. New `_initial_heap_mb()`
  starts small (512 MB, never more than half of `-Xmx`) and lets the JVM grow
  into the ceiling. `AlwaysPreTouch` is unchanged (still gated by
  `_pretouch_flag`).
* **B2 `G1NewSizePercent 30/40 → 10`** — the 30% young-gen floor meant G1 would
  not collect until eden was ~30% of the heap, so the heap climbed to ~50%
  before it "cleaned" (exactly the reported behaviour) and every young GC copied
  hundreds of MB on the render thread's cores.
* **B3 server values replaced with JVM client-sane ones** —
  `G1ReservePercent 20 → 10`, `InitiatingHeapOccupancyPercent 15 → 45`,
  `SurvivorRatio 32 → 8`, `MaxTenuringThreshold 1 → 15`. `G1HeapRegionSize=8M`,
  `G1HeapWastePercent=5` and the pause goals are unchanged.
* Stale comments that still claimed "-Xms matches -Xmx" were corrected.

## C. `cubeon/config.py`

* **B4** — untouched, already correct: the seeded default is
  `min(recommended_max_ram_mb(system), DEFAULT_HEAP_CEILING_MB)` and
  `DEFAULT_HEAP_CEILING_MB` is 6144, so a big machine no longer starts at half
  of RAM.

## D. Website — wrong claims removed

The mod no longer carries an in-game chat UI (commit `75072d9` deleted
`CubeonClientScreen` + the pause/title-screen mixins), so two pages advertised a
feature that does not exist:

* `web/index.html` "Play with friends" — "Chat works in the launcher **and
  inside Minecraft**" → messaging lives in the launcher.
* `web/help.html` — the "chat icon in the pause menu opens the same
  conversations" sentence → replaced with what the mod *does* still do: it marks
  Cubeon players in Minecraft's own player list (Tab).

The launcher-side friends chat is untouched and still described correctly.

## E. Mod jars

Rebuilt both brackets (`tools/build_mod_jars.py`) — the `26` bracket now builds
too, JDK 26 is installed on this host. Verified the shipped jars contain **no**
chat classes (`CubeonClientScreen`/`PauseScreenMixin`/`TitleScreenMixin`/
`CornerIcon` count = 0); only `PlayerTabOverlayMixin` +
`YggdrasilSessionServiceMixin` remain in `cubeon-client.mixins.json`.

`assets/jars/` and `~/.cubeon_launcher/cache/` both refreshed.

## F. Release 1.1.2 binaries

`APP_VERSION` was already `1.1.2` (commit `75072d9`); nothing to bump.

Rebuilt and clobbered in `dist/`:

| Artifact | Size |
|---|---|
| `Cubeon-x86_64.AppImage` | 108.0 MB |
| `cubeon_1.1.2_amd64.deb` | 114.4 MB |
| `Cubeon-Windows-x64.zip` | 121.2 MB |
| `Cubeon-Windows-x64-Setup.exe` | 114.3 MB |

* Linux: `.venv-build` (flet 0.86.5 + pyinstaller 6.22.3) → `build_appimage.sh`
  → `build_linux_installers.py`.
* Windows: wine + WinPython 3.11.9 → `build_windows.py` → NSIS 3.0.4.1
  (`~/.cache/electron-builder/nsis`) via `build_windows_installer.py`
  (`APP_VERSION=1.1.2.0`, `DISPLAY_VERSION=1.1.2`).
* `packaging/build_appimage.sh` **fixed**: appimagetool re-executes itself from
  a temp mount under `APPIMAGE_EXTRACT_AND_RUN=1`, and the continuous build then
  fails to resolve a *relative* AppDir ("no such file or directory:
  dist/AppDir"). It now passes `$PWD/$APPDIR` and `$PWD/dist/...`.
* Removed the stray `dist/_bg_preview.html` scratch file as part of "clobber".

### Verification of the frozen artifacts

Not just "the build exited 0". The embedded `PYZ.pyz` was extracted from **both**
`dist/Cubeon-x86_64.AppImage` (`usr/bin/Cubeon`) and
`dist/Cubeon-Windows-x64.zip` (`Cubeon/Cubeon.exe`) with PyInstaller's
`CArchiveReader`/`ZlibArchiveReader`, unmarshalled, and the constants/names
walked. All of these are present in both:

`graphicsPreset` + `"fast"`, `particles`/`"2"`, `ao`/`false`, no `graphicsMode`,
`_initial_heap_mb`, `-XX:G1ReservePercent=10`, (no `=20`),
`-XX:InitiatingHeapOccupancyPercent=45`, `-XX:SurvivorRatio=8`,
`-XX:MaxTenuringThreshold=15`, no `-Xms{ram_mb}M`, `APP_VERSION == 1.1.2`.

Full suite green afterwards: **49/49** `tools/test_*.py`, plus
`bash -n packaging/build_appimage.sh`.

## Not done / open

* **Publishing is not done.** The rebuilt files sit in `dist/` only. The live
  `/windowsdownload`, `/linuxdownload`, `/linuxdeb`, `/linuxsetup` routes are
  served by `worker/cubeon-downloads.js` from a bucket (`pickLatestPrefixed`
  picks the newest matching asset), so shipping means uploading these four files
  there (or to the GitHub release) — that needs the owner's explicit go-ahead
  and credentials.
* **C1/C2/C3 from the audit were deliberately not "fixed"**: they are live
  profile state, not launcher bugs. Wurst + XaeroWorldMap staying installed, the
  pinned sodium 0.8.12, and sodium's `use_entity_culling`/`use_fog_occlusion`
  being off are the *player's* choices (the launcher never writes
  `sodium-options.json`). Set them in game / in Sodium's own settings.
* `~/.cubeon_minecraft` layout: `cubeon/maintenance.py` already runs an
  `organize()` pass at startup and reports "Cubeon's files are already tidy"
  right now. Remaining visible clutter that the pass does *not* touch is listed
  in the thread (older versions of the same mod side by side in
  `global_mods/`, TLauncher's `backup/` next to Cubeon's `backups/`,
  `.cache/` next to `cache/`, `shaderpacks/*.zip.txt` leftovers) — awaiting a
  decision on how far to go, since pruning a mod version a profile may pin is
  not obviously safe.
