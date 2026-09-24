# Four-fix pass: chat dupes/latency, Linux restart button, Windows icon, installer (2026-09-23, Cline)

- **Agent:** Cline
- **Date:** 2026-09-23
- **Task:** four user reports in one message: "chat msgs are duping and very
  much latency", "restart button in seasonal updates in settings doesnt work
  on linux build specifically", "the windows icon doesnt show on app in
  correct way", "the installer of windows is too crappy technical shi".

## What I did

### 1. Chat duplication (ui/chat_tab.py)
Reproduced it headlessly with the real tab + a scripted service: when the
relay echo landed AFTER `_sweep_pending`'s 12s cutoff, the red "Couldn't send"
bubble was **removed from `_pending`** by `_fail_pending`, so the real line
appended as a second bubble → one message, two bubbles. Fix: failed entries
stay in `_pending` (`failed:True`); a late echo REPLACES that exact slot in
place (`handled_in_place` flag → skip the append). Queue bounded at
`_MAX_PENDING = 64`. Legit identical texts still render twice (FIFO text
match consumed once per real line).

### 2. Chat latency (same file)
Was a fixed 1.5s poll for everything — the sender's own bubble only
confirmed on the next tick. Now adaptive `_poll_interval()`: 0.25s for 2s
after a send (`_fast_until` + `_wake` event), 0.5s while a conversation is
open, 1.5s idle. Measured a real tick at ~2ms (20-friend roster +
50-message ring), so this is free.

### 3. Restart-to-apply on Linux (main.py)
The relaunch branch did `_ctrl.stop()` **raw** before execv — pystray/GLib
teardown is the one native call this codebase already documents hanging
(futex_wait on KDE), so the window could close with nothing ever relaunching.
New `_stop_tray_best_effort(timeout=2.0)` (watchdogged daemon thread) is now
the ONLY way the three execv paths stop the tray (Settings > Restart, GPU
crash recovery, tray Open); broadened those branches' excepts to Exception.

### 4. Windows icon (packaging + Cubeon.spec)
No Windows build path ever passed an icon: exe, shortcuts and installer all
shipped PyInstaller's default bootloader art (the runtime window icon WAS
set - main.py sets `page.window.icon` - so only the shell was wrong). Added
`--icon=assets/icon.ico` to build_windows.py / build_windows_single.py /
build_public_windows.py and `icon='assets/icon.ico'` to Cubeon.spec's EXE.

### 5. Windows installer (packaging/Cubeon.nsi + build_windows_installer.py)
Rewrote on MUI2: welcome page with plain-English copy, proper directory
page, progress bar instead of the `ShowInstDetails show` wall of extracted
paths (now `hide`), finish page with "Open Cubeon", Cubeon icon on the
setup/uninstaller, version resources, and a Programs-and-Features uninstall
entry. The build script now passes ICON_FILE + APP_VERSION (4-part numeric,
read from `cubeon/updater.py`) + DISPLAY_VERSION.

## How I verified
- **Chat**: `tools/test_chat_optimistic.py` (NEW, 12 checks: normal replace,
  late-echo-replaces-red = the regression, identical repeats, cadence,
  bounded queue) — 12/0. The repro before the fix showed
  `['late one', 'late one']`, after the fix `['late one']`.
- **Restart**: `tools/test_ui_smoke.py` §4c (8 checks: hanging/raising/no-op
  tray stop, all execv paths watchdogged, restart branch order, AND clicking
  the real built Settings button arms the request + schedules the close) —
  full suite **156/0**. Found along the way: `FakeWindow` lacked `close`,
  which made the button's fallback branch clear the request *in tests only*
  (real flet 0.86.5 has `async def close` — verified in site-packages).
- **Windows icon**: PyInstaller 6.21 accepts `--icon` on Linux with exit 0
  (warning only) — sanity-built a hello-world exe to prove the flag; the
  spec's `icon=` is likewise warn-and-ignore off Windows (read
  `PyInstaller.building.api.EXE` source).
- **Installer**: compiled the new .nsi with electron-builder's bundled NSIS
  under Wine → `dist`-style `Cubeon-Windows-x64-Setup.exe` produced,
  **0 warnings / 0 errors** (the first compile caught a real bug:
  `ShowInstDetails` takes show|hide|nevershow, not nshow). Confirmed the
  Cubeon icon bytes are embedded in the setup exe.
- Suites after everything: mega_smoke --static 12/0, seasonal 106/0,
  faces 11/0, ui_smoke 156/0, chat_optimistic 12/0; fuzz run green
  (see log); test_friends_service pre-existing 4 fails unchanged (proven on
  pristine HEAD earlier).

## Notes for the next agent
- The only UNVERIFIED piece end-to-end is a real click on a real Linux
  desktop (needs a human): the flow is button → event set → window closes →
  session loop (watchdogged tray stop) → execv. Each half is now guarded
  headlessly; the execv function itself is the same one tray-Open has used
  successfully on Linux for weeks.
- Rebuilding Windows artifacts still needs the normal wine/windows path
  (`build_windows.py` then `build_windows_installer.py`); only the installer
  script itself was compiled here.
- nsis compile recipe for tests: `/tmp/nsis_build.py` pattern in this
  session's notes is disposable — call
  `packaging/build_windows_installer._compiler()` + defines against a dummy
  SOURCE_DIR instead.

## Question for the next agent
The chat fast-cadence window (0.25s after send) is time-based; if the relay
ever gets slower than ~2s for echoes, the sender will still see
"Sending…" settle to a red bubble before the real line lands. Would an
explicit "echo received" signal from the service (instead of polling for it)
be worth the plumbing now that the UI already survives late echoes?