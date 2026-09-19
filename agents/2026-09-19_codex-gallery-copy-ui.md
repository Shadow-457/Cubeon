# Improve Gallery UI and add copy action

- **Agent:** Codex
- **Date:** 2026-09-19

Added a capture count, framed thumbnail rail, preview/details card, and Copy image action to the Gallery tab. The copy action uses Flet desktop clipboard file support with a validated screenshot path. Verified with `python -m py_compile main.py ui/screenshot_gallery.py cubeon/screenshot_gallery.py`, `python tools/test_screenshot_gallery.py` (6/6), `python tools/test_ui_smoke.py` (151 passed), and `git diff --check`.
