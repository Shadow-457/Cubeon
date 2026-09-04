# Mods tab showed installed mods when no instance was selected (stale profile key)

- **Agent:** opencode (deepseek-v4-flash)
- **Date:** 2026-09-03
- **Task:** User reported: "no instance is selected yet I see mods downloaded in the Mods/Download area".

## What I did
Root cause: `state["selected_mc_version"]` is primed from `config["last_version"]` at startup
(`main.py` ~line 241). When `refresh_version_list()` (offline) finds **no installed versions**
it cleared the version dropdown ("No versions installed yet") but never cleared that state key.
The Mods tab keys its Installed list and browse "already downloaded" flags off
`state["selected_mc_version"]`, so it kept pointing at the old version's profile folder
(whose mods are still on disk) and showed "X installed" + green-checked browse rows despite no
instance being selected. On the user's real data: stale key "26.1.2" → profile `26.1.2-fabric`
had **43 mods**; the no-instance state (`None`) reads empty profile `unknown-fabric` → 0.

Fix (`main.py`, `refresh_version_list` offline empty-options branch): when nothing is
selectable, also set `state["selected_version"] = None` and
`state["selected_mc_version"] = None`, then `refresh_mods_list()` /
`refresh_browse_for_new_profile()` / `update_hero()` so every tab agrees there is no instance.
This also covers the delete-last-instance flow, which routes through the same empty branch.

## How I verified
- Read the whole selection flow (`refresh_version_list`, `on_version_selected`, `update_hero`,
  Mods-tab state reads in `mods_tab.py`) and reproduced the mismatch against the user's real
  on-disk state: stale key → 43 mods listed; cleared key → 0.
- `python3 -m py_compile main.py` clean; `tools/test_ui_smoke.py` → 40 passed, 0 failed.

## Notes for the next agent
- The user's machine is mid-migration: `config.json` says `last_version "26.1.2"`, the OLD
  profile `~/.cubeon_launcher/mod_profiles/26.1.2-fabric` is full of mods (hard links into the
  OLD `~/.cubeon_launcher/global_cache/mods/<sha>.jar` hash store), but the NEW private game
  dir `~/.cubeon_minecraft/` has NO `versions/` and its `global_mods/` store is empty. So the
  launcher now genuinely thinks nothing is installed. The stale-UI bug is fixed; the deeper
  question of whether/when old versions+mods migrate into `~/.cubeon_minecraft` is still open
  and probably the next thing the user hits (Play tab will want to re-download 26.1.2).
- My earlier store-routing note said the legacy migrations were removed as dead code — that is
  still true of the CODE (they only ever ran against `mods/`, which is now wiped every launch),
  but the on-disk `.migrated`/`.vanilla_misfile_migrated` markers and the old hash-store
  symlinks predate the restructure and are untouched.

## Question for the next agent
The fresh-vs-migrated split: should Cubeon offer to import versions + the old `global_cache`
mod store into the new `~/.cubeon_minecraft` tree on first run of a build that changed the
game dir, or is starting each private dir clean the intended design? Worth a product call
before the user deletes their 43-mod profile as "junk".
