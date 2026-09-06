# 2026-09-07 — agent: unmounted-refresh crash fix + Atk noise filter

## What happened
User reported a crash dialog: `Column(296) Control must be added to the
page first`, triggered by clicking the **Mods** nav item.

Root cause (verified against flet 0.86 source): `BaseControl.page` is a
property that walks `.parent` and **raises RuntimeError** for unmounted
controls. `hasattr(ctrl, "page")` is True (the property exists), so the old
guard in `thread_safe_ui.refresh()` caught nothing. The lazy-built Mods tab
calls `refresh_mods_list()` → `refresh(mods_list_view)` while the tab body is
still unmounted (first visit, before the mounting `page.update()`).

Second task (same session): silence the `Atk-CRITICAL **: atk_socket_embed`
line the flet client prints on every launch.

## What I changed
1. `cubeon/thread_safe_ui.py` — `refresh()` now wraps the `control.page`
   read in try/except → unknown page falls to the direct path;
   `_refresh_now()` recognizes the "must be added to the page" RuntimeError
   as an expected unmounted-control case and silently skips (Flet sends a
   control's full state at mount, so nothing is lost).
2. `main.py` (`__main__`) — `NO_AT_BRIDGE=1` (set before `ft.run`; env
   propagates but does NOT stop the warning) **plus** a wrapper around
   `flet_desktop.open_flet_view_async` that spawns the client with piped
   stderr and streams it through a drop-filter (`Atk-CRITICAL|
   atk_socket_embed|plug_id != NULL`). Non-matching stderr still reaches
   the log. The reader MUST be `await readline()` — a sync read on the
   asyncio pipe leaves the coroutine un-awaited and silently eats ALL
   client stderr (caught this in a live run).
3. `tools/test_ui_smoke.py` — 4 new checks (43 → 45):
   - Mods nav button found in the built tree (matches via the handler's
     `__defaults__` — the tab key is bound as a default arg, not a const),
   - clicking it (full lazy build + `refresh_mods_list` path) doesn't raise,
   - `refresh()` tolerates never-mounted controls,
   - `refresh()` direct path safe for detached controls.
4. `agents/docs/module-map.md` — added the two hard rules (`.page` raises on
   unmounted; the Atk filter and its sync-read gotcha).

## How I verified
- Smoke suite 45/45 (`CUBEON_GAME_DIR=/tmp/... python3 tools/test_ui_smoke.py`).
- **Mutation test**: temporarily restoring the old `hasattr`-based
  `refresh()` makes exactly the 3 new checks fail (the 4th, nav-button
  discovery, still passes) — the tests genuinely cover the bug.
- Probe run: instrumented `_refresh_now` confirmed the Mods click routes
  unmounted `Column` + `Text` through `refresh()`.
- Live runs: atk line count 0 (was 1 per launch), window painted
  (`ui_painted_ok`), no unhandled errors, no coroutine warnings; tray
  behavior and client cleanup unaffected; all test launcher/flet processes
  cleaned up afterward.

## Q&A baton for the next agent
The stderr drop-filter is deliberately narrow (one known-harmless pattern).
If the flet client ever starts failing in ways hidden by it — remember the
filter is in main.py right before `ft.run`, search `_filtered_open_flet_view_async`.
Also: flet 0.86's `BaseControl.update()` raises the SAME "must be added"
RuntimeError — any future code calling `ctrl.update()` directly on possibly-
unmounted controls should route through `thread_safe_ui.refresh()` instead.
