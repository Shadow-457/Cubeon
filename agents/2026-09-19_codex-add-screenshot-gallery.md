# Add Minecraft screenshot gallery

- **Agent:** Codex
- **Date:** 2026-09-19
- **Task:** Add a Profile/Account sidebar button for browsing Minecraft screenshots.

## What I did

Added `cubeon/screenshot_gallery.py` for safe screenshot discovery, bounded previews, path-safe deletion, and opening the screenshots folder. Added a polished Flet viewer in `ui/screenshot_gallery.py` with thumbnail rail, full preview, metadata, refresh, delete confirmation, empty state, and folder action. Wired the compact entry button into the Account profile sidebar.

## How I verified

- `tools/test_screenshot_gallery.py`: 5/5
- `tools/test_ui_smoke.py`: 148 passed, 0 failed
- `tools/test_capes.py`: 19/19
- `git diff --check`: passed
