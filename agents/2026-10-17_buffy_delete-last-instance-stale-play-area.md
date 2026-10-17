# Deleting the last instance: it deleted, the Play area didn't

User report (verbatim): *"the main menu play area the delete button doesn't work
properly like when theres only 1 version and i delete it it does delte but the ui
doesnt correctly disappear"*. The delete itself was fine; the repaint was not.

## What was actually wrong

`refresh_version_list()`'s **"nothing installed" branch** (only reachable by
deleting the LAST instance) re-drew the mods list, the browse list and the hero -
but not the rest of the version surface:

- the compact **Game-version button** kept reading `1.21.11  ●` after that
  version was gone (it mirrors the dropdown, and nothing re-labelled it there),
- the hero **rename/delete pair stayed lit and clickable** (their guard only ran
  on the selection path),
- a **pack badge / issue note** belonging to the deleted install could stay on
  screen.

The other half: a delete started from a **row of the open Instances manager**
left the dialog mounted and still listing the instance that had just been
deleted - the row only went away when the dialog was closed and reopened.

## The fix

- `main.py`: one owner for the pair's state, `_sync_instance_actions(version_id)`,
  called by `on_version_selected` and by the empty branch; that branch now also
  does `picker.sync_label()`, `version_issue_text.visible = False` and
  `update_pack_badge()`.
- `ui/versions.py`: `InstancesManager` keeps one dialog + body and re-draws its
  rows via `refresh()`, which `on_delete_instance`/`on_rename_instance` call after
  a successful action. `open()` skips re-showing a mounted dialog (Flet's
  `show_dialog()` raises for one), using dialog-stack membership rather than
  `.open` - a barrier-dismissed dialog is removed from the stack without
  clearing that flag, so `.open` alone would have made the Manager stop
  reopening. `_close()` drops our reference so the next open builds a fresh
  dialog and can never race Flet's teardown.

## Bonus: a real crash found on the way

Reproducing this hit a flaky `KeyError: 'fabric-loader-...'` in
`InstanceCards.rebuild`. Root cause: the install/launch workers repaint through
`_rescan_installed -> update_hero -> rebuild` **off the UI thread**, while the
Play tab's own selection path rebuilds on it. Both popped dropped ids before
assembling the row from the same dicts, so an interleaved pair raised on the id
the other had just popped - killing that repaint and its whole handler. Cheap to
hit (1 in 5 runs of the version-UI test once the delete flow ran after a Play
click). `rebuild()` now serializes on a lock; the body moved to `_rebuild()`.
Still worth revisiting some day: `_rescan_installed` mutates controls directly
from worker threads instead of going through `cubeon/thread_safe_ui`.

## How it was verified

- Headless repro before/after (`tools/_fuzz_common` stubs): picker label
  `1.21.11  ●` -> `No versions installed yet`, hero Delete `disabled=False/1.0`
  -> `disabled=True/0.4`, card row hidden + empty notice shown, and the open
  Instances dialog dropping the deleted row.
- `tools/test_version_ui.py` grew sections **4** (manager-row delete of the last
  instance), **5** (the hero's own Delete, the reported path) and **6** (the
  concurrent-repaint race). All three were checked to FAIL against the unfixed
  code and pass with it; sections 4/5 also pin the exact strings/opacity.
- Ran green: `test_version_ui` (45, x8 runs), `test_instances` (36),
  `test_version_art_cache` (15), `test_ui_smoke` (223), `test_startup` (25),
  `test_mega_smoke` (20), `test_launch_indicator` (11), `test_fuzz` (13) and a
  full `tools/app_driver.py explore` pass (0 errors).
- NOT run: the Windows-only and manual-visual suites.
