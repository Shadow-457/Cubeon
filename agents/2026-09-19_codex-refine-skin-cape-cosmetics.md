# Refine skin and cape cosmetics UI

- **Agent:** Codex
- **Date:** 2026-09-19
- **Task:** Improve the cosmetics section hierarchy, previews, and installed-item browsing.

## What I did

Upgraded `ui/skin_tab.py` with an Appearance header, live-preview badge, framed current-look stages, explicit active-item metadata, a useful empty-skin state, larger installed cards, and clearer active/local-preview labels for skins and capes. Existing async thumbnail rendering and generation guards remain in place; the new preview controls are optional in the isolated stale-preview harness.

## How I verified

`tools/test_ui_smoke.py`: 148 passed. `tools/test_capes.py`: 19 passed. `tools/test_gallery.py`: 32 passed.
