# Removed the system tray / close-to-tray background mode (2026-09-27)

- **Agent:** Cline
- **Date:** 2026-09-27
- **Task:** "remove the tray bg shit completly cleanly"

## What was removed
The whole system-tray / "background process" feature, not just its look:
- `cubeon/tray.py` — the entire pystray module (TrayController, the Linux
  appindicator backend picker). Deleted via `git rm`.
- `cubeon/config.py` — the `close_to_tray` setting (default True).
- `requirements.txt` — the `pystray` runtime dependency.
- `main.py` — ~479 lines changed, net −350:
  - `_stop_tray_best_effort()` (the execv watchdog) and all 3 call sites.
  - `_tray_activate` / `_tray_quit` and the `TrayController` startup block.
  - The entire **park** half of `_session_loop`: a closed window used to park
    the process headless and wait on `_reopen`/`_quit`. Every park-only exit is
    now a plain `return`, so a closed window ends the process.
  - The `_tray_active` gate in `_do_session_end_cleanup` — it now always stops
    `friends_service` (there is no windowless state to keep it alive for).

## Renames (behaviour-preserving)
- `_tray_runtime` → `_session_runtime`. It was never only about the tray: it
  also holds the process-scoped friends service/client and the gamepad
  watcher's `controller_*` slots, which outlive a single window session.
- `CUBEON_TRAY_REOPEN` → `CUBEON_RELAUNCH` (set by `_relaunch_fresh_process`,
  popped in main() to suppress the "orphaned Minecraft session" prompt after a
  deliberate relaunch — still wanted, tray or not).
- `_reclaim_session_signals()` no longer sets an event; it only counts presses
  in `_session_signal_hits` (1st ^C swallowed so the bounded teardown finishes,
  2nd is `os._exit(0)`). The reclaim itself is still load-bearing — flet never
  removes its own handler.
- Dropped the now-dead `_session_ended_at` stamp (only the park logic read it).

## Verification
- `tools/test_mega_smoke.py --static` → **15/0** (imports 67 modules, was 68).
- `tools/test_ui_smoke.py` → **166/0**.
- `tools/test_friends.py` → 104/0. `tools/test_wedge_watchdog.py` → 9/0.
- `tools/test_mega_smoke.py` (runtime) → 18/1. The single failure is
  **pre-existing and unrelated**: a `TypeError` in
  `ui/modpacks_tab.py`'s CurseForge-key dialog lambda. I proved it by
  `git stash`-ing the whole change and re-running: identical failure on a
  clean tree. Left alone — it is not mine to fix in this pass.
- `grep -ri tray` over main.py / cubeon/ / ui/ / requirements.txt / Cubeon.spec
  returns nothing but the word "stray". The only surviving mentions anywhere
  are the new negative guard in test_ui_smoke.py, a stale PyInstaller
  `build/Cubeon/warn-Cubeon.txt` log, and the `.kilo/worktrees/` checkout
  (a separate agent worktree — not part of this repo's tracked source).

## Notes for the next agent
- **The tray guards in test_ui_smoke.py were rewritten, not just deleted.**
  Section 4c used to test that a hanging `stop()` could not block a re-exec;
  that is now a negative guard ("the tray is gone from the launcher entirely",
  asserting `TrayController` / `_stop_tray_best_effort` / `_tray_runtime` /
  `pystray` are all absent from main.py). §4d's park-tick checks were replaced
  with counter-based signal checks, and the old "tray Quit kills the flet client
  first" guard now asserts the same ordering inside `_session_loop` — that
  ghost-window bug is still real, it just has no tray to hang off.
- **Behavior change to be aware of:** closing the window now quits. That is
  intended, but it IS a user-visible change — there is no longer any way to
  keep friends presence / Discord RPC alive with no window.
- Durable facts went into `agents/docs/module-map.md` under a new
  "Tray / background mode REMOVED" invariant block, not into this note.
