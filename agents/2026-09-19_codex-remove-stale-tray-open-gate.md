# Remove stale tray Open gate

- **Agent:** Codex
- **Date:** 2026-09-19
- **Task:** Fix tray Open still being ignored after native window close.

## What I did

Removed the `controller_page`/window visibility gate from `_tray_activate()`. Flet 0.86 can retain a page reference and report the window visible after the native X close, so the old gate discarded valid Open requests. Open is now recorded and consumed by the session loop only after `ft.run()` ends.

## How I verified

Python compilation passed and `python tools/test_ui_smoke.py` reported 148 passed, 0 failed.
