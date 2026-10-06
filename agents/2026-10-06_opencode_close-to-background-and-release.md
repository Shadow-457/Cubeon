# Real close-to-background fix (Discord RPC deadlock + `on_close` watchdog); re-cut release v1.0.0 (2026-10-06)

- **Agent:** opencode (mimo-v2.6-flash-free)
- **Carried from 2026-10-05's note:** the launcher still ran after close on
  Linux too, and the seasonal "Restart to apply" button had never been proven
  live. Both are now root-caused, fixed, and verified on the shipped binary.

## 1. The background bug was a SELF-DEADLOCK, not a missing flet event
Live repro on the real X display: closing the window left a zombie
`flet-desktop-light` client and `python3 main.py` alive forever. A faulthandler
SIGABRT dump pointed straight at
`_on_window_event` → `discord_rpc.close()` → `clear()` → `_memoize_and_send()`
blocked on a mutex: `DiscordPresence.close()` held a **non-reentrant**
`threading.Lock` and `clear()` re-took it, freezing flet's event loop so
`ft.run()` never returned. **Fix:** `self._lock = threading.RLock()` plus
`self._stop.set()` in `close()` (the retry thread also kept the process up).

While chasing it I also disproved the previous note's premise: **`page.on_disconnect`
never fires** — `Session.disconnect()` has zero callers in flet 0.86.5 *and*
1.0.3; client death dispatches `page.on_close`. So `main()` now wires one
handler to both via a `setattr` loop, and the window-event `close` **and** `hide`
(KDE/Windows deliver HIDE on a real X-button close) branch only into
`_arm_window_gone_exit()` — never RPC or friends teardown on the event loop.

The watchdog (`_arm_window_gone_exit` → `_window_gone_finish`, 1.0 s close /
2.0 s hide) honors `_relaunch["request"]` so the seasonal restart still
re-execs, then `_terminate_flet_clients()` + `os._exit(0)`;
`_session_loop` marks `ft_returned` as soon as `ft.run()` returns so the
watchdog can't fire on a clean exit or a legit relaunch.

## 2. Verified
- Suites (all green, run from `~/cubeon-venv`, flet 0.86.5): `ui_smoke` 176,
  `launch_fixes` 98, `perf_mods` 55, `net` 42, `friends` 104, `wedge_watchdog`
  9, `mod_bridge` 146, `seasonal` 106; `mega_smoke --static` 16 (system python);
  `mod_compile` clean.
- **Close, twice:** from source under flet 1.0.3 (0.5 s) and 0.86.5 (1.0 s),
  rc=0, no survivors — and on the **shipped `dist/Cubeon-x86_64.AppImage`**
  (runtime+payload+flet child tracked by cmdline, exit in 1.0 s, zero left).
- **Restart button:** a temporary `CUBEON_TEST_AUTO_RESTART` one-shot hook
  (added, used, then **removed** — `grep` = 0) showed a real re-exec with
  `CUBEON_RELAUNCH=1` at 15.5 s / 16.0 s on both flet versions.
- **Frozen bundles:** PyInstaller CArchive/POO inspection of the Windows
  onedir and the AppImage payload confirms `_window_gone_finish`,
  `_arm_window_gone_exit`, `_live_flet_clients`, `on_close`/`on_disconnect`,
  `_relaunch_fresh_process`, `cubeon.discord_rpc.RLock`, and all 12
  `templates.color_*` modules. Parsed as `marshal.loads(d[toc_pos:])` where
  `d` is bytes — `d[idx]` returns an **int**, you need the slice.

## 3. Release v1.0.0 clobbered (all sha256-verified against the GitHub API)
`Cubeon-Windows-x64-Setup.exe` (114 MB, 1.0.3), `Cubeon-x86_64.AppImage`
(108 MB — was missing, so `/linuxdownload` 404'd), `Cubeon-Linux-x86_64-Setup.sh`,
`cubeon_1.0.0_amd64.deb` (built as `cubeon_1.0.3_amd64.deb`, uploaded under the
name `worker/cubeon-downloads.js` expects). Build order matters:
`packaging/build_appimage.sh` does `mv dist/Cubeon/*`, so the installer goes
first; Linux builds must use `PATH=$HOME/cubeon-venv/bin:$PATH` (system
python3.14 drifted to flet 1.0.3 — never build with it).

## 4. Batons for the next agent
- **26-bracket client jar still not rebuilt** (`cubeon-client-1.0.0+mc26.jar`):
  javac path failed, Gradle fallback stalled — 1.21.11+ players keep the old
  in-game mod menu until this lands.
- **`cubeon.gg` doesn't resolve from this machine**, so the download routes
  were verified on the release (assets + digests) but never over HTTP.
- Uncommitted at time of writing: `main.py`, `cubeon/discord_rpc.py`,
  `tools/test_ui_smoke.py`, `agents/` — see git log for the commit.

Full contract lives in `agents/docs/module-map.md` → "Windows seasonal
colours + installer + close-to-background" (rewritten today).
