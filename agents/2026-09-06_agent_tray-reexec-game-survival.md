# Tray reopen + game survival + startup perf (finished by Claude Code)

## The big discovery of this session
**`ft.run()` is once-per-process on Flet 0.86.** My in-process reopen
approach (park the `__main__` loop, call `ft.run(main)` again on tray
Open) compiled and ran — a new flet client pid appeared — but the new
client's **engine never initialized**. No window, no crash, no "Timed out
waiting for OpenGL frame": just a silent hang with the launcher parked in
`do_epoll_wait` forever. Flet's `run()` wraps `asyncio.run()` and some
client/session state is not re-initializable in-process.

**The fix (by Claude): tray Open re-execs the launcher** —
`os.execv(sys.executable, ...)` in `__main__`: same pid, fresh
interpreter, guaranteed-working first-run path. `CUBEON_TRAY_REOPEN=1`
env tells the new image the game is still being watched (no "orphaned
session" prompt). PyInstaller case handled too (`sys.frozen` →
`sys.executable` is the launcher itself).

Fast-click subtlety: a user can click tray Open *while the window is
tearing down*. The reopen event is timestamped (`reopen_at`) and honored
if newer than `session_ended_at - 5.0`; older stray clicks are ignored.
The events must **never be cleared blindly** — a blind clear dropped
every fast reopen and looked exactly like "Open is broken".

## Ghost-window fix
Flet 0.86 can't remove its implicit view (`FlutterEngineRemoveView
returned kInvalidArguments`), so on X-close the **client process stays
alive showing a spinner/"Working..." window** owned by no session.
`_kill_flet_client()` (main.py, `__main__` block) walks `/proc` for
*children of this pid* named `flet` (name matters — Minecraft is also our
child, comm `java`), SIGTERM → 2s grace → SIGKILL. Runs on every session
end, before parking/re-exec.

## Game survival (independent bug, same session)
The launched game's stdout was a **pipe owned by the launcher** and it
shared our process group/terminal. Closing the launcher (or its terminal)
broke the game's logging (broken pipe) or SIGHUP'd the JVM. Now:
`start_new_session=True`, stdin `/dev/null`, stdout a real file
(`~/.cubeon_launcher/game.log`). The game now survives launcher exit —
what a real launcher does.

## Startup perf
- `minecraft_launcher_lib` import (~116ms, drags `requests`) is now lazy
  (`cubeon/lazy.py`) — first use, not import time.
- Mods / Modpacks / Servers tabs (~4,287 lines of control construction)
  now build **on first visit**, not at startup.
- `CUBEON_PERF=1` env arms a repaint profiler in `cubeon/thread_safe_ui.py`
  (times every `page.update()` by call site, table at exit). Zero cost off.

## Also
- Tray icon startup now verified via pystray's setup callback (fires
  inside pystray's loop once registered) instead of assuming success;
  `_pick_linux_backend()` prefers appindicator, falls back to gtk.
- Window default width 1180→1060, one-time migration for installs that
  only have the old default saved (exact-1180 match = never deliberately
  resized).
- Process-scoped singletons for Discord presence / FriendsService /
  ControllerWatcher (kept across sessions; per-session handlers
  re-registered via `_tray_runtime` slots — see `_dispatch_controller`).

## Verified
- `tools/test_ui_smoke.py` 41/41 after the changes
- `python3 -m py_compile main.py cubeon/*.py` clean
- User confirmed tray reopen works live ("he done doing and it works")

## Baton for the next agent
The `__main__` `os._exit(0)` skips Python teardown by design (native GLib/
pango threads wedge shutdown). If you ever see the launcher "not exiting"
after quit, check whether someone made that path conditional — the hang
returns immediately without the hard exit.
