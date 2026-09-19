# Move screenshot gallery to a top-level tab

- **Agent:** Codex
- **Date:** 2026-09-19

Moved Minecraft screenshots out of the Account popup and into the top-bar Gallery tab. Opening the tab refreshes the thumbnail rail and full preview; the Account panel is profile-only again. Verified with `python -m py_compile main.py ui/screenshot_gallery.py cubeon/screenshot_gallery.py`, `python tools/test_screenshot_gallery.py` (5/5), `python tools/test_ui_smoke.py` (150 passed), and `git diff --check`.
