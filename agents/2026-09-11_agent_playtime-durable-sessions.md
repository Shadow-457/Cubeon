# 2026-09-11 - Playtime, part 2: durable game sessions (launcher re-exec gap)

## Symptom
User: "time in game is still not showing even if i play." The earlier fix
(the `core.add_play_seconds` -> `core.milestones_add_play_seconds` rename in
`on_exit`) was correct but incomplete.

## Root cause (confirmed against the live home)
`on_exit` is only invoked by the in-process watcher thread that `launch_game`
spawns. But the game is deliberately designed to outlive the launcher
(`start_new_session=True`), and the launcher re-execs itself on a mid-session
GPU-client crash (`os.execv` in `_session_loop`, which sets
`CUBEON_TRAY_REOPEN`). Each `execv` replaces the process and kills the watcher.

Evidence on this machine:
- `~/.cubeon_launcher/game.log` shows a session 02:50:39 -> 03:01:26.
- `running_game.json` held pid 24114 (never cleared) while the launcher process
  was pid 25902, started 02:55 - i.e. a different, later process. The game was
  launched by a launcher that had already been replaced.
- `milestones.json` mtime was days old and `seconds_played` stayed 0.0.

So the watcher died at the re-exec; the game kept running; nothing credited it.

## Fix
Persist the session and reconcile it on the next start.

- **`cubeon/milestones.py`**: new durable-session API.
  - `begin_play_session(pid, started_at=None)` writes
    `~/.cubeon_launcher/play_session.json` = `{started, pid}` (atomic).
  - `end_play_session(now=None)` credits
    `min(now, mtime(game.log)) - started` and clears the record. The log-mtime
    bound stops a launcher that was off overnight from minting idle hours as
    playtime. Idempotent under a new `_session_lock` (distinct from `_lock`,
    which `add_play_seconds` takes internally - no deadlock).
  - `reconcile_play_session(pid_alive=None)`: dead pid -> `end_play_session()`;
    live pid -> leave the record and poll every 30s until it exits.
- **`cubeon/launch.py`**: `launch_game` calls `begin_play_session(process.pid)`
  immediately after `watchdog.register`, before the watch thread starts.
- **`main.py`**: `on_exit` now calls `core.milestones_end_play_session()` (the
  in-memory `_milestone_launch_started_at` is gone). `main()` calls
  `core.milestones_reconcile_play_session()` on every start, placed BEFORE the
  orphan-watchdog block so the `CUBEON_TRAY_REOPEN` env pop cannot skip it -
  that env is set on exactly the crash re-exec that needs reconciling.
- **`launcher_core.py`**: re-exports the three new names.

## Verification
- `test_milestones` 50/50 - new §7 covers: begin persists `{started,pid}`; end
  credits to the game-log mtime (not a 10h idle gap); end clears + is
  idempotent; end credits nothing when the log predates the session (instant
  crash / unwritable HOME - no log evidence must not mint idle hours);
  reconcile credits a dead-pid session; reconcile leaves a live one on disk
  uncredited.
- `test_ui_smoke` 93/93 - reworded the wiring check to
  `core.milestones_end_play_session`; added: launch.py calls
  `begin_play_session`, main.py calls `core.milestones_reconcile_play_session`.
- `py_compile` clean on main.py, cubeon/milestones.py, cubeon/launch.py,
  launcher_core.py.
- Full sweep green: test_gallery 38, test_capes 14, test_net 19,
  test_mod_store 21, test_modpacks 51, test_versions_profile_key 11,
  test_csl, test_fuzz 12, test_launch_indicator 11.

## Note for next agent
The old historical `play_session.json` from before this feature obviously
doesn't exist, so the pre-fix sessions are unrecoverable. Going forward every
launch writes one. If you ever make the game launch outside `launch_game`, call
`milestones.begin_play_session` there too, or that path earns no playtime.
