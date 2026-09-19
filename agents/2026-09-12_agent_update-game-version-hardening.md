# 2026-09-12 — Update game version: make it never dead-end

## Why
`on_update_version` (Play tab, `main.py`) had a branch that could produce a
message that read like a no-op: if the newest release was already the selected
version but **not installed**, it fell through to
`"Latest is <v> - pick it from the list"` even though it was already picked.
It also couldn't select the newest release when that version wasn't in the
current list (offline / just-released), so the same dead-end message appeared.

## What changed (`main.py:on_update_version`)
- If the newest release isn't in `version_dropdown.options`, it is inserted
  (and into `pick_source`) before selecting, so the picker always has it.
- If it's already selected but not installed: `on_version_selected()` is
  called again to make sure the prefetch is running, and the status is
  `"Getting <v>..."` (or `"Already on the latest release (<v>)"` once the
  background install lands).
- If selected and installed: `"Already on the latest release (<v>)"`.
- The bad `"Pick it from the list"` branch is gone.
- `finally` now repaints the visible picker label (`_sync_version_button()` +
  `refresh(version_button_label)`), so the button's face is correct even on an
  error path.

## Verification
`tools/test_ui_smoke.py` gained section **6b** (105 -> **112 passed**), which
drives the real `on_click` handler found through the control tree:
- newest release not installed -> selection moves to 1.21.11, status reports
  the download, never the old "pick it from the list" text;
- newest release installed -> "Already on the latest release".
Status text isn't mounted (no visible status chip by design), so the test
captures it by spying on `thread_safe_ui.refresh`, which `set_status()` calls.
The prefetch install is blocked on an event so it can't flip the version to
"installed" mid-assertion.
Sweep green: mod_detail 66, perf_mods 15, mod_bridge 119, mod_compile clean,
mod_matrix 68, production 13, versions_manifest 10, versions_profile_key 11.
Docs: `module-map.md` + `guide-ui-modules.md` update-button bullets.

## Q for the next agent
The first Update click still fetches Mojang's list synchronously on the UI
thread (shared with the picker's "Browse all versions"). The cache makes it
instant after the first time; if it ever visibly stalls on a cold start, move
`refresh_version_list(online=True)` onto a worker with the existing
`thread_safe_ui.refresh` plumbing.
