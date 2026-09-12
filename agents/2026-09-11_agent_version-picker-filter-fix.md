# 2026-09-11 - Play-tab version picker: filter no longer hijacks the selection

## What was wrong
User: the Play menu's "Browse versions" picker "doesn't work correctly and
overall doesn't work good." Root cause was in `main.py`'s `_filter_versions`
(the search field's on_change, via `on_pick_search`):

- It rewrote the canonical `version_dropdown.options` on every keystroke, and
  when the current selection fell outside the filtered subset it reassigned
  `version_dropdown.value` to the first match and called
  `on_version_selected()`.
- `on_version_selected()` sets the play button mode and calls
  `prefetch_version()`. So merely **typing in the version search box could
  silently change the selected version and start a background
  download**.
- Closing the dialog without picking left `version_dropdown.options` narrowed,
  so reopening showed a stale filtered list, and `_sync_version_button()` could
  no longer find the selected option's label (fell back to the raw id).
- `_rebuild_pick_list()` then filtered `version_dropdown.options` a second
  time on top of that.

## The fix (main.py)
- Added `pick_source = {"value": []}` - the picker's own snapshot (installed
  options offline, full online list after a fetch). `refresh_version_list`
  now fills it in BOTH branches, right where it assigns `version_dropdown.options`.
- `_rebuild_pick_list()` iterates `pick_source["value"]` only; it never
  touches `version_dropdown.options`/`.value`. Selection is committed solely
  by `_pick_version()` (a row click).
- Deleted `_filter_versions`; the field's on_change is `on_pick_search` ->
  `_rebuild_pick_list()`.
- Empty source or zero matches now renders an explanatory row
  ("Press “Browse all versions” to load the online list." / "No versions match
  your search.") instead of a blank box.
- `all_online_options` is kept for the `on_update_version` path.

## Verification
- `python3 tools/test_ui_smoke.py` -> 91/91 (added a source-level regression
  guard: `_rebuild_pick_list` must read `pick_source` and the file must not
  contain `version_dropdown.options = all_online_options`).
- `test_versions_profile_key` 11/11, `test_launch_indicator` 11/11.
- `python3 -m py_compile main.py` clean.
- module-map.md version-picker bullet rewritten (also fixed its stale mention
  of a snapshots checkbox inside the dialog - that lives in Settings now).

## Note for next agent
The picker dialog internals are closures in `main()`, so there is no direct
unit test - the guard is the source assertion in test_ui_smoke. If you touch
`refresh_version_list`, keep `pick_source` in sync with `version_dropdown.options`
or the dialog will offer a list that doesn't match the installed/online state.
