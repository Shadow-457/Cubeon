# 2026-09-20 — remove "Update game version" from the Play tab

User request: remove the Update game version button **fully** (UI + backend),
without breaking anything else.

**Removed (all in `main.py`):**
- `update_version_btn` container + its `theme.attach_hover` call (never
  mounted now; the ACTION FOOTER row keeps `expand` spacer + PLAY at 280px).
- `on_update_version` handler.
- `_newest_release_key` helper (only caller was the handler).
- `all_online_options` cache (set in `refresh_version_list`, read only by the
  two functions above). `pick_source` is untouched and remains the picker
  dialog's filter source.
- Stale comments (legacy block, Play-tab hierarchy, filter comment).

**Tests/docs updated:** deleted `test_ui_smoke.py` section 6b and its
`_control_with_click` helper + the "update-version button present" check
(no other test referenced it). Updated the module-map bullet + Play-card
description, `docs/architecture/mod-management.md` and
`agents/docs/guide-ui-modules.md`.

**Verified:** `python3 -m py_compile main.py tools/test_ui_smoke.py`;
`tools/test_ui_smoke.py` → 142 passed, 0 failed;
`tools/test_mega_smoke.py` → 16 passed, 0 failed. Grep confirms zero
`on_update_version` / `update_version_btn` / `_newest_release_key` /
`all_online_options` references left in `main.py`.
