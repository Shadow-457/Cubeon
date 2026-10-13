# 2026-10-13 — Import: per-instance "Import to" + search; launcher-reopen fixes

## What the user asked for
1. Import area: no "Import all" — a **search** that shows everything, and an
   **Import to** button that lists all instances, greys the incompatible ones,
   and installs into the picked instance.
2. Fix the thing that "reopens Cubeon after I open once… it thinks cubeon
   crashed by graphics shit".
3. Push.

## Import rework (`ui/import_section.py`, `cubeon/importer.py`, `main.py`)
- `main.py` now passes `get_instances=_import_instances` (id/mc/label from
  `core.get_installed_versions()`); the pane derives each instance's loader
  with `importer.loader_of(version_id)`.
- Per item: "Import to..." → AlertDialog of instances. Greyed rows =
  incompatible (`importer.instance_compatibility`: Fabric jar never into Forge;
  declared `mc_dep` "1.21" fails on 1.20.1) or already contain the item
  (`importer.already_in_profile`). Click an enabled row → `import_item` into
  THAT profile (mods land in that profile's folder, packs linked there; worlds
  are shared `saves/` so every instance row is compatible).
- "Import all" removed; a live search TextField filters rows (auto-expands
  groups while a query is active).
- Duplicate detection from earlier today is unchanged (`mark_installed` flags +
  `import_item` guards + pack `.origin` sidecars) — it now also feeds the
  picker's "Already installed" rows.
- Pane hooks for tests: `import_item_ui(entry, btn, inst=...)`, `picker_model_ui`,
  `open_picker_ui`, `_search_field`, `remark_installed_ui`.

## "Reopens after close" — three real causes, all fixed in `main.py`
1. `_classify_session_end`: a client that exits **0 is always clean_close**,
   even if the `ui_painted_ok` marker was lost (marker write is best-effort;
   "marker lost + exit 0" used to route to the software-GL retry = reopen).
2. Wedge watchdog false positive: it counted any 2 GL-frame timeouts within
   25s, but a merely SLOW client emits them ~10s apart (one per failed frame).
   A real wedge emits them as a ~0.2s BURST. Added `_WEDGE_BURST_GAP = 4.0`
   on `_wedge_state["stamps"]`. False positives used to kill a healthy client,
   which the ladder then "recovered" by reopening.
3. (Already fixed earlier, kept in mind: the old live-child test.)

## Also fixed on the way
- `ui/modpacks_tab.py` CF-key dialog Remove button: `key_field.update(value="")`
  raised TypeError on flet 0.86 (update() takes no kwargs) — was mega_smoke's
  only red check. Now sets `.value` + `thread_safe_ui.refresh`.

## Verification
- `tools/test_importer.py` 47/47, `tools/test_import_ui.py` 45/45 (rewritten for
  search + picker + per-instance imports), `tools/test_ui_smoke.py` 177/0 (+
  new `(False, 0) -> clean_close` pin), `tools/test_mega_smoke.py` 20/20,
  `tools/test_wedge_watchdog.py` 9/9, launch/content/modpacks suites green.

## Q&A baton
- The wedge-burst threshold (4s gap) is still one number from ONE machine's
  logs. If someone reports a frozen window that is NOT recovered, suspect the
  gap being too tight before touching `_WEDGE_TIMEOUTS`.
