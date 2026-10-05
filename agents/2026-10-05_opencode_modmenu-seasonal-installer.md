# Remove in-game mod menu; fix Windows seasonal colours, installer speed, close-to-background (2026-10-05)

- **Agent:** opencode (deepseek-v4-flash)
- **User report (one batch):** Cubeon runs in the background after close; remove
  the in-game Cubeon Client's mods area; seasonal theme COLOURS don't show on
  Windows (only weather+pet); make the Windows installer better and its update
  "deleting" step faster; rebuild Windows binaries and clobber release v1.0.0.

## 1. In-game Cubeon Client mod menu + modules REMOVED
Confirmed with the user this meant the IN-GAME mod's "Mods" button and module
framework, not the launcher's Mods tab.
- Deleted the `modules/` package, `ModuleMenuScreen`, `MenuPaint`,
  `MenuPainter`, `keys/MenuKey`, `mixin/PlayerTickMixin`, and the per-overlay
  `MenuPaintImpl`/`HudMixin`/`MenuPaintMixin`. KEPT Friends (`CubeonClientScreen`,
  `CornerIcon`, pause-menu icon) and the tab-list tag.
- `cubeon-client.mixins.json` now lists only Pause/Title/PlayerTabOverlay
  mixins; `PauseScreenMixin` no longer adds the "Mods" button; `CubeonClient` no
  longer loads `cubeon-modules.json`; `build.gradle` drops glfw; build/test
  lists updated (`tools/build_mod_jars.py`, `test_mod_compile.py`,
  `test_mod_bridge.py`, `SelfTest.java`).
- **Rebuilt `assets/jars/cubeon-client-1.0.0+mc1.20-1.21.jar`** (Gradle+loom) so
  1.21.11 loses the menu. **The 26 jar was NOT rebuilt** — its javac path failed
  and the Gradle fallback stalled; a 26.x player keeps the old menu for now.
- Verified: `test_mod_bridge.py` 146/0, `test_mod_compile.py` all mod sources
  compile clean.

## 2. Windows seasonal colours
Root cause found: dynamic palette import + `--collect-submodules templates`
collects zero on the isolated WinPython build interpreter → silent fallback to
green. Fixed all three Windows builders to use explicit
`--hidden-import templates.color_*` + `--paths ROOT`; added a
`test_mega_smoke` guard. (See module-map for the full chain.)

## 3. Installer faster + better
`Cubeon.nsi`: replaced `RMDir /r` + `File /r` with `SetOverwrite ifdiff` over the
top (skips rewriting ~100 MB of unchanged assets), targeted stale `templates`
cleanup, `OldInstDir` tracking, `/SD IDOK`, uninstall path guard, and richer
P&F keys. `build_windows_installer.py` computes `EstimatedSize`.

## 4. Close-to-background on Windows
`_on_window_event` now hard-exits on `close`/`disconnect` after cleanup;
`_kill_flet_client()` gained a psutil-based Windows/macOS branch.

## 5. Background investigation note
A prior subagent for this task failed ("Not Allowed"), so it was done by hand.
The launcher's own session loop already exits the process on a clean close
(`os._exit(0)`); the Windows-specific hole was the delivered `close` event not
ending the process. Not verifiable here (no Windows) — the hard-exit is the fix.

## Verification
`test_perf_mods` 55/0, `test_launch_fixes` 98/0, `test_ui_smoke` 166/0,
`test_mod_bridge` 146/0, `test_mod_compile` compile-clean.

## For the next agent
- Rebuild the 26 client jar (`python3 tools/build_mod_jars.py 26`) on a box with
  the right JDK 25 + network.
- The Windows artifacts must be rebuilt for the seasonal fix to reach users
  (build scripts changed), then clobbered onto release v1.0.0.
