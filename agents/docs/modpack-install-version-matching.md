# Modpack install: version matching fix + future-proofing

Implemented 2026-08-23.

## The bug

Installing a modpack from Modrinth (search/browse or "Install from file" via
URL) could fail deep inside `minecraft_launcher_lib` with a raw, confusing
error like:

```
Install failed: UnsupportedVersion: Version 26.2 is not supported
```

`26.2` isn't a Minecraft version - it's a mod loader build number. The
launcher had installed a `.mrpack` whose declared `dependencies.minecraft`
didn't match anything the user actually had, because `get_modpack_file()`
took `versions[0]` - the newest published file for the project - completely
unconditionally, and `modpacks_tab.py` never told it which Minecraft version
the user actually had selected on the Play tab in the first place. Search
results (`search_modpacks`/`get_popular_modpacks`) had the same gap.

## The fix

- `get_modpack_file(project_id, mc_version=...)` now filters candidate
  versions to ones that actually declare `mc_version` in their own
  `game_versions` list, and picks the newest **matching** one - not the
  newest overall. If nothing matches, it returns `None` rather than
  falling back to an incompatible file.
- `modpacks_tab.py`'s Install handler now passes `state["selected_mc_version"]`
  (the Play tab's current version - already tracked, just never threaded
  through here) into `get_modpack_file`, and shows a plain-English message
  ("this pack doesn't have a version for Minecraft X.Y.Z") instead of
  attempting an install that was always going to fail.
- Any `mll` exception that still slips through (`UnsupportedVersion`,
  `VersionNotFound`, `ExternalProgramError`) is translated into a
  non-jargon message rather than shown raw.

## Future-proofing

- **Search/browse are now version-scoped too** (`search_modpacks`,
  `get_popular_modpacks` in `modpacks_tab.py`), and each result row shows a
  visible (advisory, non-blocking) hint when a pack has no listed version
  for the selected MC version - so a mismatch is visible before tapping
  Install, not just after it's refused.
- **`get_modpack_file` is defensive against Modrinth API drift**: a non-list
  response, malformed entries (missing `files`, wrong types), and a missing
  `date_published` are all tolerated (skipped, not fatal) rather than
  crashing. Version ordering is now explicit (`sort by date_published`)
  instead of trusting undocumented API result order. The chosen file's URL
  is re-checked against the same host allowlist (`_host_allowed`) the rest
  of the installer enforces, before it's ever handed to the UI.
- **`search_modpacks` is defensive** the same way: a missing/malformed
  `hits` list, or a malformed individual hit, is skipped rather than
  raising.
- **Unrecognized mod loader keys now raise instead of silently defaulting
  to vanilla.** `parse_dependencies()` previously fell through to `"vanilla"`
  for any `dependencies` key it didn't recognize (e.g. a future Modrinth
  loader). That's a worse failure than an error: the pack's mods need that
  loader and would just silently never load. It now names the
  unrecognized key and asks for a Cubeon update instead.
- **Modpack format version errors are more actionable** - the message now
  says only format 1 is supported and suggests checking for an update,
  instead of a bare "unsupported format version N".

## Stale "installed" listing after deleting a version

Deleting a modpack's version from the **Play tab** ("Delete instance") only
ever removed `.minecraft/versions/<id>` - by design, per
`versions.delete_version()`'s own docstring, since mod profiles are meant to
be shared/reusable. But that meant the modpack's tracking record
(`_modpack.json`, written under `mod_profiles/<mc_version>-<loader>/`) was
never cleaned up, so the Modpacks tab's "Installed packs" list kept showing
packs the user had already deleted, with a Play button that pointed at a
version that no longer existed.

- Added `modpacks.forget_modpack_for_version(version_id)`: removes only the
  `_modpack.json` tracking record for whichever profile was created by
  installing that launchable version id. Does **not** touch the mod jars,
  configs, or the profile folder itself - same "shared/reusable" reasoning
  `delete_version()` already uses, just applied consistently.
- Wired into the Play tab's "Delete instance" confirm flow, alongside the
  existing `delete_version()` call, and the Modpacks tab now refreshes
  immediately after rather than waiting for the next tab switch.
- **Added a direct Delete button on each row in the Modpacks tab's
  "Installed packs" list** (previously Play-only), with its own confirm
  dialog matching the Play tab's existing delete-instance styling. This
  covers the version-delete + tracking-record cleanup + config/state
  pointer cleanup (`version_labels`, `last_version`, `selected_version`) in
  one place, and degrades gracefully if the version folder was already gone
  by some other means - it still removes the stale tracking record instead
  of erroring out, which is exactly the scenario that caused the original
  stale-listing bug.

## Validation

- `tools/test_modpacks.py`: 45 passed, 0 failed (was 26; added coverage for
  version-matching, malformed/drifting API responses, host allowlist
  enforcement on the chosen file, date-based ordering, the
  unrecognized-loader-key refusal, and `forget_modpack_for_version`'s
  cleanup/idempotency behavior).
- Full suite (all 13 `tools/test_*.py`): all passing.
- `python3 -m py_compile` across the whole tree: clean.
