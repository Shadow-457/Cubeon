# Fix tray Quit leaving a ghost launcher window

- **Agent:** Codex
- **Date:** 2026-09-19
- **Task:** Fix launcher close/background reopen and quit behavior.

## What I did

Updated `main.py` so tray Quit also reaps the separate Flet desktop client before the hard process exit. This prevents quitting while the window is open from leaving a mapped ghost window that blocks or confuses the next background/tray launch.

## How I verified

Ran `python tools/test_ui_smoke.py` — 148 passed, 0 failed.
