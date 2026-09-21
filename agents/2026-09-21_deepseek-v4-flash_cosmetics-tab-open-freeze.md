# 2026-09-21 — Cosmetics tab open "freeze for a moment"

Reported: opening the Cosmetics tab froze the launcher briefly, then it became
normal.

## Root cause

`switch_tab("profile")` -> `refresh_profile_tab()` -> `rebuild_skin_section()`
rebuilt the ENTIRE skin section from scratch on **every** visit to the tab.
Measured (headless probe, fake page, real builders): `build_skin_section` =
~130-150 ms steady-state (12 or 30 skins/capes — the cost is mostly fixed,
not per-card), plus the fresh ~700-control subtree re-serialization to the
Flet client via `thread_safe_ui.refresh(tab_switcher)`. Thumbnails and preview
composites were already worker-threaded — the rebuild itself was the freeze.

## Fix (main.py)

The rebuild's only purpose is the CSL-status tooltip reflecting the current
`mc_version`/`mc_loader`. `rebuild_skin_section` now caches the built tree in
`skin_section_container` and is a no-op unless
`(version_dropdown.value or cfg["last_version"], state["mod_loader"])`
changed. All section refresh paths (upload/use/delete handlers) repaint in
place, so nothing goes stale; `_THUMB_MEMO`/`_IMG_MEMO` now survive between
visits too (instant thumbs, no placeholder pop). Pane selection (Skin/Cape/
Images) also persists across visits now.

## Verification

- `python3 tools/test_ui_smoke.py` → 148 passed, 0 failed (incl. the 5g
  cosmetics-freeze thumbnail regression).
- `python3 tools/test_mega_smoke.py` → 16/16, includes "every nav tab opens"
  and a second independent build.
- Probe script evidence in `/tmp/opencode/probe_cosmetics.py` (build timings
  before: ~130-150 ms steady-state per visit; cProfile showed the cost inside
  `build_skin_section` itself).
