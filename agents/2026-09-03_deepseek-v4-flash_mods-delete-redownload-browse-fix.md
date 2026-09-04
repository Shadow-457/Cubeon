# Mods tab: deleting a mod now flips the browse row back to "Download"

Reported: "when I delete a mod from an instance it doesn't show any other way to
download it again." Cause was a stale Browse section, not a missing feature.

## What changed
- `ui/mods_tab.py`: both delete handlers (`on_delete` for mods, `on_delete_content`
  for resource packs/shaders) only called `refresh_mods_list()`, which re-renders
  the *Installed* list. The Browse/Download section above was never re-rendered,
  so if the just-deleted mod was still on the current browse page it kept its
  disabled "Installed" checkmark - the Download button for it was unreachable
  until the user manually re-ran a search. Each handler now calls
  `_render_browse_page()` after the delete, which re-snapshots
  `installed_slugs()`/`content_installed_tokens()` against the live on-disk
  state, so the row flips back to an enabled "Download" immediately.
- Re-render keeps the current results/page (it does not refetch from Modrinth).
  Late-bound closure to `_render_browse_page` is fine - it is only invoked at
  click time, after the whole tab is built.

## Verification
- `python3 -m py_compile ui/mods_tab.py` clean.
- `tools/test_ui_smoke.py` 40 passed, 0 failed.
- NOT done: live click-through in the Flet app (delete a recommended mod and
  confirm the browse row above changes to "Download" without a manual search).
