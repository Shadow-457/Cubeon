# Performance notes — 2026-09-18 smoothness pass

Companion to `docs/performance/smoothness-audit.md` (the issue-by-issue
audit). This file records what changed, what didn't, and the test results.

## 1. What was measured

- Import/startup cost (measured, see audit table): Python imports are ~0.3 s
  total; seasonal resolution is effectively free (<1 ms). Startup time is
  dominated by the flet desktop client spawn/first-paint, which this pass did
  not touch.
- Full test suite before/after (see §4): identical pass counts before and
  after the changes (behavior preserved).
- Play-button repaint payload: inferred (page-wide diff → 3-control subtree
  diff), not instrumented; CUBEON_PERF=1 (cubeon/thread_safe_ui.py) can be
  used to measure real flush times on hardware.

## 2. What was changed (2 files, all small)

1. `main.py` — `on_exit()` now resets the play button when the game closes
   (was: stuck on GAME RUNNING... forever; the user-reported bug).
2. `main.py` — `on_version_selected()` shows GAME RUNNING... for the version
   that is actually live (was: offered a double launch).
3. `main.py` — new `_reconcile_running_button()`, called on Play-tab entry:
   clears a stale running claim the watchdog proves dead (covers launcher
   re-exec paths that lose the in-process on_exit watcher).
4. `main.py` — `set_button_mode()` repaints only the play button
   (`thread_safe_ui.refresh(play_button)`) instead of the whole page.
5. `main.py` — `_tray_activate()` ignores tray clicks while a window session
   is live (was: re-exec'd a whole new launcher under the open window).
6. `cubeon/config.py` — `seasonal_theme` / `season_pet` defaults → False
   (seasonal layer off by default, per user request). Settings fallbacks in
   `main.py` updated to match; users' existing saved configs are untouched.

## 3. What was intentionally NOT changed

- The tab modules' full-page `page.update()` calls (server 43, modpacks 26,
  mods 9) — real win, but each needs per-site subtree analysis; too much risk
  for a "no regressions" pass. See audit.
- Launch/close machinery (session loop, GL-fallback retries, watchdog
  records, os._exit hard-quit) — already hardened in prior passes; the only
  change is the tray-click guard.
- All friends/P2P/encryption/integrity behavior — untouched.
- No caching of security-sensitive state; no new polling; no threads added
  except none (the reconcile is inline and conditional).

## 4. Test results (all after the changes)

| Suite | Result |
|---|---|
| test_mega_smoke.py | 16/16 |
| test_ui_smoke.py | 148/148 |
| test_seasonal.py | 106/106 |
| test_friends_service.py | 370/370 |
| test_friends.py | 95/95 |
| test_invites.py | 127/127 |
| test_modpacks.py | 64/64 |
| test_mod_store.py | 27/27 |
| test_net.py | 21/21 |
| test_production.py | 58/58 |
| test_mod_bridge.py | 126/126 |
| test_mod_matrix.py | 68/68 |
| test_capes.py | 19/19 |
| test_p2p_relay.py | ALL RELAY CHECKS PASSED |
| test_p2p_session.py | PASS |
| test_p2p_transport.py | PASS |
| test_version_integrity.py | 39/39 |
| test_server_integrity.py | 59/59 |
| test_mod_compile.py | mod sources compile clean |

## 5. Remaining bottlenecks (for a future pass)

- Scoped repaints for server/modpacks/mods tab updates.
- `on_version_selected()` disk work could go to a worker if profiles get big.
- Flet client spawn dominates startup; not addressable in Python.

## 6. Hardening round (2026-09-18, "more bulletproof")

Three independent defenses now protect the game-running truth (details in
smoothness-audit.md §1b): a click-time double-launch guard in
`on_play_click()`, a `running-liveness` daemon thread that self-heals if
`on_exit` never fires (5 s watchdog poll, only while a claim is live), and an
exception-proof fallback in `on_exit()`. Defense in depth: the button can
now recover from a missed callback, a crashed watcher thread, a stale claim
left by a re-exec, AND a user clicking Play anyway.

Verification re-run after the hardening: mega_smoke 16/16, ui_smoke 148/148
(5 consecutive clean runs; one transient 146/2 timing flake was seen once and
could not be reproduced — the animator ticker tests sleep on real time),
seasonal 106/106, friends_service 370/370, friends 95/95, p2p_session PASS,
version_integrity 39/39.

## 7. Round 3 — restart / open-quit robustness (2026-09-19)

Report: Settings > Seasonal > "Restart to apply" closed Cubeon but never
reopened it, and afterwards the launcher could not be opened from the
background process either. Root cause and full evidence: smoothness-audit.md
§7-§11. In one line: the flet client can WEDGE (no frames, `ft.run` never
returns), which made every recovery path — tray Open/Quit, the retry ladder,
the restart request — unreachable at once.

### What was changed
- **`main.py` — wedge watchdog (new daemon):** turns the measured wedge
  signature into a client kill, so `ft.run` returns and the EXISTING ladder
  recovers. Never tears down the session from a side thread.
- **`main.py` — retuned trigger:** `_WEDGE_TIMEOUTS 3 → 2`,
  `_WEDGE_RECENT 8 → 25 s`. At 3/8 s the detector could never fire (a real
  wedge emits a burst of exactly two lines ~0.15 s apart, then goes silent).
- **`main.py` — stream-agnostic capture:** the client's stdout+stderr are
  merged into one pipe and forwarded with an explicit flush. The previous
  stderr-only filter is what made the earlier "verification" vacuous.
- **`main.py` — orphan sweep in `_kill_flet_client()`:** cleans up client
  windows left behind by dead launchers (two-factor check, never touches a
  second live instance).
- **`cubeon/launch.py`:** `CUBEON_GPU_RESTARTS` (launcher-internal crash
  budget) can no longer leak into Minecraft's environment.
- **`tools/test_wedge_watchdog.py` (NEW)** + registered in
  `tools/test_mega_smoke.py`'s SUITES.

### Measurements (before/after, same machine)
| Scenario | Before | After |
|---|---|---|
| Wedged client (deterministic fake, measured signature) | never detected; window frozen forever | killed at age 12.2 s → retry 1 → retry 2 → giving up |
| Restart-to-apply onto a wedge | launcher closed, never reopened | client killed, ladder recovers the session |
| Orphaned client windows | 3 ghosts alive (34+ min, ~30% CPU each) | swept at session start; 0 left after the runs |
| Ladder completion | unreachable (never entered) | deterministic, terminator verified (test 9/9) |
| New guard suite | (did not exist) | `test_wedge_watchdog.py` 9/9 |

### What was intentionally NOT changed
- **Retry-exhaustion still exits.** Parking in the tray instead would keep
  Open/Quit alive with a persistently broken driver, but that is a behavior
  change and was not confirmed — flagged, not done.
- No change to any encryption/authorization/validation/timeout behavior.
- No change to the UI, the flet spawn cost, or the tab-module repaint work.

### Remaining bottlenecks
- A client that wedges WITHOUT logging any line is undetectable by this
  mechanism (never observed; every measured wedge logged first).
- Flet desktop client spawn still dominates cold start (out of Python's hands).
- Scoped repaints for server/modpacks/mods tab updates (unchanged from §5).

### Test results (this round)
| Suite | Result |
|---|---|
| test_wedge_watchdog.py (new) | 9/9 |
| test_ui_smoke.py | 148/148 |
| test_launch_fixes.py | 58/58 |
| test_mega_smoke.py | 16/16 |
| test_seasonal.py | 106/106 |
| deterministic wedge reproduction (fake, measured signature) | 3 consecutive kills, ladder completed, 0 leftovers |
| live real-client runs | clients crash/kill as expected, **no false-positive kills**, 0 leftover clients |

