# Cubeon smoothness audit — 2026-09-18

Scope: user-facing responsiveness, launch/close behavior, play-button state
truth, startup, seasonal decoration cost. Nothing was redesigned; no features
added; behavior preserved except where the old behavior was the bug.

## What was measured

| Measurement | Result | How |
|---|---|---|
| `import main` (all launcher imports) | 0.29 s | `python3 -c "import time; import main"` |
| `import launcher_core` | 0.22 s | same |
| `seasonal.import + boot()` | <0.001 s | same (resolution is cached, see cubeon/seasonal.py) |
| Play button repaint path | whole-page diff before change | traced: `set_button_mode()` ended in `page.update()` |

Startup is NOT import-bound; the real startup cost is the flet desktop client
spawn + first paint (out of Python's hands on this build). Nothing worth
moving off the critical path was found in Python-side startup.

## Issues found & disposition

### 1. Play button stuck on "GAME RUNNING..." after the game closes — FIXED (user-reported)
- **Location:** `main.py` `on_exit()` (inside `do_install_and_launch`).
- **Why:** the comment said on_exit is "the only place that should put the
  button back to play" — but it never called `set_button_mode()`. The button
  stayed disabled on GAME RUNNING... until an unrelated selection/tab switch
  recomputed it.
- **Severity:** high (daily UX, user-reported).
- **Fix:** on_exit now resets the button to `play`/`download` when the selected
  version is the one that just exited; crash and clean-close paths covered.
- **Effect:** button reflects reality the instant the game closes.
- **Verified:** inferred from the code path + suites green (ui_smoke 148,
  mega_smoke 16).

### 2. Selecting a running version showed PLAY (double-launch trap) — FIXED
- **Location:** `main.py` `on_version_selected()`.
- **Why:** mode computation ignored `state["running_version"]`, so re-selecting
  the live version offered a second launch of the same instance.
- **Severity:** medium.
- **Fix:** one dict read after mode computation → `set_button_mode("running")`.
  No psutil, no disk on the selection path.

### 3. Stale running state survives launcher re-exec — FIXED
- **Location:** `main.py` `switch_tab("play")` → new `_reconcile_running_button()`.
- **Why:** GPU-crash recovery / tray-Open re-exec replaces the process; the
  in-process `on_exit` watcher dies with it, so nothing ever cleared
  `state["running_version"]`.
- **Fix:** when returning to the Play tab, if a running version is claimed but
  `watchdog.stale_session()` says nothing is alive, clear the state and repaint
  the honest mode. One psutil probe, only when a claim exists.
- **Effect:** the button can no longer be stuck in "running" permanently.

### 1b. Hardening round (same day, "more bulletproof") — ADDED
Three defenses so the play button/game-running truth no longer depends on any
single code path firing:
- **Click-time double-launch guard** (`on_play_click()`): if the selected
  version is claimed as running, the click re-verifies the claim against the
  watchdog before committing. Cannot prove it alive → refuse with a snack
  ("That version is already running"); proven dead → clear the stale claim
  and proceed. Failure to check counts as "maybe alive" — refusing a launch
  is recoverable, a double launch is not.
- **Liveness self-heal thread** (`running-liveness`, one per process): while a
  launch's claim is live, polls the watchdog every 5 s (one psutil probe, no
  disk/network); if the game dies without `on_exit` ever firing (watcher
  thread death, missed kill), it clears the claim and repaints via the same
  reconcile the Play tab uses.
- **Exception-proof exit handler**: the whole on_exit UI/presence tail is
  wrapped; on any failure a minimal, itself-exception-proof fallback still
  clears `running_version` and resets the button.

### 4. Play button repaints the WHOLE page — FIXED
- **Location:** `main.py` `set_button_mode()` — ended in `page.update()`.
- **Why:** page.update() diffs every mounted control (~hundreds) over the
  websocket on every mode change (launch start/end, every version selection).
  The mode only mutates three controls that all live inside `play_button`.
- **Fix:** `thread_safe_ui.refresh(play_button)` — subtree-scoped diff, same
  thread-safety/loop routing as the patched page.update().
- **Measured/inferred:** inferred (payload shrinks page-wide → 3 controls);
  repaint correctness verified by suites.

### 5. Seasonal layer on by default — CHANGED TO OFF (user-requested)
- **Location:** `cubeon/config.py` defaults (`seasonal_theme`, `season_pet`).
- **Why:** palette swap at boot + season greeting card + top-bar pet GIF are
  pure decoration; the default experience should be the plain green identity.
  Ambience already shipped off.
- **Fix:** defaults now `False`; Settings fallbacks (`cfg.get(..., True)`)
  updated to match. Users who enabled it keep their config — only fresh
  configs are affected. `CUBEON_SEASON=autumn` still pins for screenshots.
- **Verified:** `test_seasonal.py` 106/106 (it tests resolve(), not the
  default).

### 6. Tray "Open" re-exec'd the launcher even with a window already open — FIXED
- **Location:** `main.py` `_tray_activate()`.
- **Why:** every tray click armed a reopen → the parked loop re-exec'd a
  brand-new launcher, killing the live session (open dialogs, scroll,
  in-flight launch feedback). Made "Open" feel random.
- **Fix:** if a session is live (`_tray_runtime["controller_page"]` is set —
  it is cleared the moment session cleanup runs), the click is ignored.
  Reopen-from-parked behavior is unchanged.

## Round 3 — restart / open-quit robustness (2026-09-19)

User report: "when i click restart cubeon on seasonal update area in settings
cubeon does closes but never opens and i am not able to open cubeon with the
background process", plus client windows that stayed on screen after the
launcher was gone.

### 7. A wedged flet client makes EVERY recovery path unreachable — FIXED
- **Location:** `main.py` `__main__` session loop + the `ft.run` client spawn.
- **Why:** the flet desktop client does not only crash; it can WEDGE (window
  mapped, zero OpenGL frames, ~180% CPU) and then `ft.run` **never returns**.
  Session classification, the software-GL retry ladder, tray Open/Quit handling
  and Settings > "Restart to apply" all live AFTER `ft.run` returns, so a wedge
  disables all of them at once: the frozen window cannot be dismissed and the
  launcher can never be reopened or quit.
- **Severity:** critical (user-reported, unrecoverable without a task manager).
- **Evidence (measured live, this machine, Mesa 26.1 / AMD Polaris):**
  - ghost client pid 29728 stayed alive 34+ minutes with a mapped, unpainted
    window (rt2.log); pids 18292/27265/29728 were three such ghosts burning
    ~30% CPU each.
  - the client announces the failure itself, on **stderr**:
    `** (flet:29626): WARNING **: 14:12:54.620: Timed out waiting for OpenGL
    frame of size 1280x720 (have 1x1)`.
- **Fix:** a `cubeon-wedge-watchdog` daemon kills a client that has proven it
  cannot render, so `ft.run` returns and the EXISTING ladder recovers. The
  watchdog never tears a session down from a side thread (`ft.run` is
  once-per-process) — it only kills the child (SIGTERM, SIGKILL after 3 s).
- **Effect:** a permanent freeze becomes an automatic restart.

### 8. The wedge detector was DEAD CODE — FIXED
- **Location:** `main.py` `_WEDGE_TIMEOUTS` / `_WEDGE_RECENT`.
- **Why:** the thresholds assumed a steady stream of GL-frame-timeout lines
  (≥3 lines, newest within 8 s). The measured signature of a REAL wedge is a
  **burst of exactly TWO lines ~0.15 s apart and then silence forever**
  (rt2.log pid 29728; rt.log pid 22385). The ≥3 threshold could therefore never
  be satisfied — the detector looked armed and never fired.
- **Severity:** critical (it was the fix for #7 and did nothing).
- **Fix:** `_WEDGE_TIMEOUTS = 2`, `_WEDGE_RECENT = 25.0` (grace 12 s / window
  60 s unchanged). Tradeoff documented in code: a false positive costs one
  automatic restart; a false negative is a frozen window forever.
- **Effect (measured, deterministic):** the watchdog now fires at client age
  12.2 s / 12.0 s / 12.0 s and the ladder runs to completion:
  `producing no OpenGL frames` → `attempt 1` → `attempt 2` → `giving up`.

### 9. The wedge test was VACUOUS (stream mismatch) — FIXED
- **Location:** the ad-hoc fake client harness (not in the repo before now).
- **Why:** the fake logged its GL-timeout lines to **stdout** while
  `_filtered_open_flet_view_async` piped only **stderr**. A live gc-level probe
  of `_wedge_state` showed `armed` set but `timeouts` stuck at 0 forever, so
  the "verified" claim about the watchdog was never true.
- **Severity:** high (a green test that could not fail).
- **Fix:** the client's stdout and stderr are merged into one pipe
  (`stdout=PIPE, stderr=STDOUT`, forwarded with an explicit flush) so no
  logging-fd assumption can defeat the counter again; and the deterministic
  test now lives in the repo as `tools/test_wedge_watchdog.py` (registered in
  `test_mega_smoke.py`'s SUITES) with a fake that reproduces the measured
  signature (stderr, burst of two, then alive-and-silent so any progress proves
  a real kill).
- **Effect:** the guard fails if the trigger is retuned out of range or the
  capture goes back to a single fd.

### 10. Orphaned client windows from dead launchers — FIXED
- **Location:** `main.py` `_kill_flet_client()` (orphan sweep).
- **Why:** when a launcher dies before cleanup, its client is reparented to
  systemd with its window still mapped and CPU burning (three observed here).
- **Fix:** session start sweeps `flet` processes whose args carry our assets dir
  **and** whose parent is no longer a live launcher. Two-factor on purpose: a
  second live Cubeon instance is never touched.
- **Verified:** suite green; live scan after the reproduction runs found no
  leftover clients.

### 11. `CUBEON_GPU_RESTARTS` leaked into the game environment — FIXED
- **Location:** `cubeon/launch.py` `launch_game()` env strip list.
- **Why:** it is main.py's launcher re-exec crash budget; a game probing
  namespaced `CUBEON_*` knobs would have seen a stale restart count.
- **Fix:** stripped from the child env alongside the software-GL vars.

### Intentional non-change in this round
- **Retry-exhaustion still exits** (`main.py`: "client keeps dying before the
  window shows - giving up" → `return`). Parking in the tray instead would keep
  Open/Quit available under a persistently broken driver, but it is a behavior
  change and was NOT confirmed by the user, so it was left exactly as it was
  and is flagged as the next candidate.
- **Residual gap:** a client that wedges WITHOUT emitting any line is not
  detected (no evidence to judge on). Never observed — every measured wedge
  logged its timeouts first.

## Identified but intentionally NOT changed

- **Full-page `page.update()` in tab modules**: `ui/server_tab.py` (43 sites),
  `ui/modpacks_tab.py` (26), `ui/mods_tab.py` (9). Real candidates for scoped
  refreshes, but each site needs its own subtree analysis to avoid missed
  repaints; deferred, not traded for risk in this pass.
- **`on_version_selected()` does synchronous disk work** (mods list refresh,
  pack index, server panel) on the selection callback. Feels instant today
  because the inputs are small; if profiles grow large, move the mods scan to
  a worker with the existing thread-safe UI updates.
- **Version picker rebuilds its list per filter change** — list is bounded
  (~hundreds of labels); debounce not warranted yet.
- **Polling cadence**: backup scheduler 30 min; watchdog recovery only while a
  session is live — both already event-driven enough. No change.
- **Network**: update check is one background GET at startup; friends/P2P run
  on their own threads with dedupe (see agents/docs/module-map.md). No
  duplicate-request pattern found that could be fixed safely here.

## Correctness issues noticed (NOT fixed here, per pass rules)

- None new. The double-launch gap in issue 2 was fixed as part of the
  play-button truthfulness work; the non-running case behaves exactly as
  before.

## How to reproduce the measurements

```
python3 -c "import time; t=time.perf_counter(); import main; print(time.perf_counter()-t)"
python3 -c "import time; t=time.perf_counter(); import launcher_core; print(time.perf_counter()-t)"
```
