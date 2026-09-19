# Fix tray Open being ignored after window close

- **Agent:** Codex
- **Date:** 2026-09-19
- **Task:** Make tray Open work after closing the launcher window.

## What I did

Updated `main.py` so the tray callback distinguishes a genuinely visible window from a stale Flet page reference left behind by native window teardown. Tray Open now queues the reopen request when the old window is hidden/closed instead of dropping the click.

## How I verified

Ran `python -m py_compile main.py cubeon/config.py` and `python tools/test_ui_smoke.py` — 148 passed, 0 failed.
