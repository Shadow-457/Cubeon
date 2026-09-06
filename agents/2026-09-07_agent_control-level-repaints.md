# Control-level repaints: the perf fix that actually mattered

## The measurement (CUBEON_PERF=1, live run)
- page-level `update()`: **5–8 ms avg** (full ~9k-line tree walk + IPC patch)
- control-level `update()`: **0.35 ms avg** — same page, same tree
- After conversion: **12 page-level updates per session** (mostly Flet's
  own first-mount), everything hot is control-level.

## What was built
`cubeon/thread_safe_ui.py` now has `refresh(control)` — the control-level
sibling of the page.update() wrapper, with the SAME contract: loop-thread
fast path, `call_soon_threadsafe` marshalling from background threads,
TREE_LOCK around the diff, reschedule-once on failure, CUBEON_PERF
attribution. A `_loops` side table (page-id → loop) is recorded by
`install(page)` so `refresh()` can find the right loop from any thread.

**Rule of thumb for call sites** (also in the module docstring):
- one small region changed (label, button state, one list) → `refresh(that)`
- structure changed (add/remove controls, swap tab body) → `page.update()`

## Sites converted (the per-keystroke / per-file / per-line ones)
- `main.py` `_filter_versions` (per keystroke) → dropdown only
- `main.py` `set_status` → sidebar status pair only
- `main.py` install/launch progress callbacks → progress row only
  (`throttled_update`+`final_update` retired from this path — control
  repaints are cheap enough without coalescing)
- `ui/mods_tab.py` live search, search-fail, installed-filter refresh →
  browse region / list+count only
- `ui/server_tab.py` console flush (per log line, was per-line
  full-tree!) → console ListView + counter; server install progress →
  status/bar; smooth-install events → progress row
- `ui/modpacks_tab.py` install progress + popular-packs loading →
  status/bar/results region
- `ui/skin_tab.py` upload status → status text only

## List virtualization audit (the "third fix" from the analysis)
Already effectively done by design: server console is a `ListView`;
mods / plugins / installed packs cap at 5 rows with a show-all toggle;
browse views page 5 at a time. At current data volumes nothing else
needs virtualizing. If a real "hundreds of live rows" list appears, the
pattern to copy is `console_log = ft.ListView(...)` + control-level
flush (server_tab.py `append_console`).

## Retired-in-this-path (not deleted)
`throttled_update` / `final_update` remain in thread_safe_ui for any
future full-tree flood; no current caller, kept as utilities.

## Verification
- `tools/test_ui_smoke.py` 41/41 after every file
- Live CUBEON_PERF run: numbers above (perf1.log had the table)
- No stray processes left; test launcher cleaned up

## Baton
The profiler is opt-in (`CUBEON_PERF=1`). If someone reports "UI feels
slow", run one session with it and read the table before changing any
code — the cost lives in repaint count × tree size, not in Python.
