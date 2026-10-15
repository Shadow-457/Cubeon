# 2026-10-15 — Windows console flashes fixed ("random cmd opens and closes")

## Ask (from the user's Discord, relayed)
"it opens random cmd when starting or closing or doing anything - cmd opens
and closes" — a Windows user on the shipped binaries, on every click/install.

## Root cause
Cubeon.exe is built --windowed (no console), but Windows gives EVERY child
process its own console window unless the spawn passes
CREATE_NO_WINDOW + STARTF_USESHOWWINDOW(SW_HIDE). Only the Minecraft game
itself did that (cubeon/launch.py already had it). Every other spawn flashed:

  - `java -version` probes — java_major_version() passed startupinfo=None,
    and it probes EVERY candidate Java on the machine on each Play click and
    each install (the worst offender: several flashes per click);
  - the FABRIC installer jar — minecraft_launcher_lib.fabric runs
    `java -jar installer` with a plain subprocess.run; their quilt module
    DOES use the hidden-window STARTUPINFO, fabric was missed upstream;
  - `tzutil /g` (seasonal, Windows-only command);
  - the local server Popen (had CREATE_NEW_PROCESS_GROUP but no NO_WINDOW);
  - the relaunch-fallback Popen (execv's except branch);
  - the flet.exe desktop client (asyncio.create_subprocess_exec).

## Fix
- `cubeon/winproc.py` (new): `hidden(**extra)` builds the no-window kwargs
  (OR-ing caller creationflags; posix = pass-through no-op) and
  `patch_mll()` swaps a window-hiding subprocess shim into
  minecraft_launcher_lib.fabric (idempotent, posix no-op).
- Wired into: launch.py probe, jre.py probe fallback, seasonal.py tzutil,
  server.py start (keeps NEW_PROCESS_GROUP via the OR), mod_loaders.py
  (patch_mll before any loader install), main.py relaunch fallback + flet
  client spawn.
- `os.startfile`/`xdg-open`/`open` sites are fine (Explorer/WM open, no
  console).

## Verification
- Windows semantics proven by monkeypatched os.name="nt": hidden() emits
  CREATE_NO_WINDOW + SW_HIDE startupinfo, ORs caller flags, the shim injects
  both into run(), patch_mll installs the shim and is idempotent, posix is a
  no-op.
- test_ui_smoke 194/194 (new permanent block: helper exists, probe has no
  startupinfo=None, patch_mll wired, all sites import hidden);
  test_launch_fixes 113/113; test_perf_mods 75/75.
- NOT verified on a real Windows box (none here) — needs the user's next
  build to confirm the flash is gone; the fixed binaries must be shipped.

## Shipping note
The currently uploaded release assets do NOT contain this fix (nor the Java
verify / first-launch doctor from earlier today). Rebuild + clobber when the
user says ship.
