# 2026-09-05 — Fixed "launcher freezes during downloads" (progress-flood throttle)

## Symptom

User: downloading 1.21.11, the launcher "got stuck", then became good again
when the download finished.

## Root cause

minecraft-launcher-lib's install callback fires once per FILE. A version
install = ~4000 asset files. Every callback ran `page.update()` — a full
control-tree diff + repaint. Thousands of repaints queued onto Flet's event
loop starved input handling: the window looked hung until the flood ended
and the queue drained. thread_safe_ui.py had already fixed *delivery*
(call_soon_threadsafe) and *tree-mutation races* (TREE_LOCK), but nothing
capped the *rate* — the delivery fix actually made the flood reliable
enough to always saturate the loop.

## Fix

`cubeon/thread_safe_ui.py`: new `throttled_update(page)` (coalesces any
call rate into ≤1 repaint / 0.1s) and `final_update(page)` (flushes the
pending coalesced state once a flood ends, so 100% always paints).

Call sites changed (the four flood paths):
- main.py `do_install_and_launch` status_cb/progress_cb/max_cb (+ final_update
  before the loader-lock refresh)
- ui/modpacks_tab.py status_cb/progress_cb/max_cb (+ final_update in the
  install worker's finally)
- ui/server_tab.py install progress_cb, `_smooth_progress`, (+ final_update
  on install error)

## Verification

- Isolated throttle test: 5000 rapid calls → 1 repaint; 30 calls over
  1.5s → 15 repaints (10 fps cap); final_update flushes the pending one.
- Full tools/test_*.py sweep (fresh CUBEON_GAME_DIR per suite): all pass.
- Committed as a8f0b4f and pushed; CI green run expected to produce new
  artifacts.

## Baton for the next agent

- The UI-freeze class of bug is now: (1) delivery [fixed], (2) tree races
  [fixed], (3) flood rate [fixed]. If a freeze report comes in again,
  check for a bare `page.update()` inside a per-chunk/per-file callback —
  grep for progress_cb definitions that call page.update() directly.
- mods_tab.py has download progress paths I did NOT touch (per-mod
  downloads are single-file, low frequency); if bulk mod downloads ever
  freeze, apply the same pattern there.
