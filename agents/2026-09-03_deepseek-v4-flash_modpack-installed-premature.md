# Modpack showed as "Installed" (and Play-able) before the install finished

- **Agent:** opencode (deepseek-v4-flash)
- **Date:** 2026-09-03
- **Task:** User reported: installing a modpack shows a progress bar, yet under the Modpacks
  tab's "Installed packs" the pack already shows as installed, and clicking run starts a broken
  half-finished instance.

## What I did
Root cause: a pack is *listed* as installed purely by the `_modpack.json` marker in its profile
(`mod_profiles/<mc>-<loader>/`), and `list_installed_modpacks()` reads it from disk
(`cubeon/modpacks.py:1490`). The marker is only **written** at the very end of a successful
install (step 6), but it is never **removed** when a new install starts overwriting that same
profile. So reinstalling/updating an already-installed pack (or installing a different pack that
shares the same version+loader profile) left the old marker on disk for the whole download:
`refresh_installed_packs()` only runs on success, so the stale row stayed visible and its Play
button launched the profile while the rebuild was mid-write.

Fixes:
1. `cubeon/modpacks.py` (`_install_from_zip`): delete the profile's `_modpack.json` right after
   the index is parsed and validated (before downloading the MC version/loader/mods), and let
   the success path re-write it. A reinstall therefore stops showing as installed the moment it
   starts; a failure correctly leaves it gone instead of advertising a half-built pack.
2. `ui/modpacks_tab.py`: the installed-list refresh was gated behind success only. `status_cb`
   now refreshes the "Installed packs" list once per install, at the first destructive step
   ("Installing Minecraft"/"Downloading mods"), by which point the marker is already gone from
   disk (`installed_refresh_done` one-shot guard, reset in `_begin_install`).
3. `ui/modpacks_tab.py`: installed-row Play (`_play_installed`) and Delete (`do_delete`) refuse
   while `busy["value"]` is true (covers the brief window before the refresh, and any other
   row that could still be rendered mid-install) — no launching a half-rewritten profile.

## How I verified
- `python3 -m py_compile` clean on `cubeon/modpacks.py`, `ui/modpacks_tab.py`, `main.py`.
- `tools/test_modpacks.py`: 51 passed (was 46) — added a reinstall regression asserting the
  stale marker is gone at the *first* status callback ("Installing Minecraft 1.20.1") and is
  re-written only after the rebuild succeeds.
- `tools/test_modpacks_cf_keyless.py`: 28 passed. `tools/test_ui_smoke.py`: 40 passed.
- All three install routes (`.mrpack` file, CurseForge zip, browse URL) funnel into
  `_install_from_zip`, so all share the fix. Validation failures (bad zip / unparsable index)
  raise before the marker removal, so a *rejected* archive doesn't uninstall a good pack.

## Notes for the next agent
- This fix intentionally treats "an install has begun for profile X" as "X is no longer
  installed" for the duration. Failure mid-rebuild leaves the pack unlisted rather than
  playable-but-broken — that was the bug's whole point.
- The Play-tab launch path itself (switching to the Play tab mid-install and running the
  half-installed *version*) still isn't guarded by the Modpacks tab's `busy` flag — it predates
  this and is a separate vector if it ever bites.

## Question for the next agent
Unchanged baton from the previous note: the user's machine is mid-migration
(`config.json` `last_version "26.1.2"`; old `~/.cubeon_launcher/mod_profiles/26.1.2-fabric`
has 43 mods; new `~/.cubeon_minecraft/` has no `versions/` and an empty `global_mods/`). Should
Cubeon offer to import old versions + the legacy mod store into the new tree on first run, or is
starting each private game dir clean the intended design?
