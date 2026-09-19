# Friends + CustomSkinLoader injection audited across every install path — clean, no leftover bug

Re-examined whether Cubeon Friends (mod/) and CustomSkinLoader install correctly for every
version/modpack Cubeon installs. Walked each flow end-to-end and ran the relevant suites.
No code changed — found nothing to fix.

## What I verified (by reading code, not just notes)

- **Injection is centralized at launch** (`cubeon/launch.py:395` `launch_game`): when `cfg`
  is passed, `csl.ensure_ready` (cubeon/csl.py:458) + `cubeonfriends.ensure_installed`
  (cubeon/cubeonfriends.py:146) run, then `sync_mods_to_game`. Every launcher path passes
  `cfg` + the real `mc_version`/`loader`:
  - main.py Play button (main.py:1822-1832), after resolving a pack's loader/version from
    `list_installed_modpacks` (main.py:1808-1818).
  - friends_service host (`invite`, friends_service.py:571-578) and joiner
    (`_maybe_finish_join`, friends_service.py:956-961) — both forward `cfg`.
- **Modpack install pre-injects** using the PACK's declared loader, not the Play-tab selector
  (cubeon/modpacks.py step 7, ~486-514). Both `.mrpack` (file + URL) and CurseForge-converted
  packs funnel through `_install_from_zip`, so all three routes get the same step 7.
  CSL for any of fabric/quilt/forge/neoforge (`MOD_CAPABLE_LOADERS`); Friends fabric/quilt only.
- **Edge cases behave, not silently break**: vanilla loader -> "no mod loader selected"
  (csl) / no-op (friends); unsupported friends bracket -> explicit status message
  (launch.py:448-450, modpacks.py:504-512); pack self-shipping CSL is detected by
  slug/name (`is_installed`) so Cubeon doesn't double-install; stale/obsolete friends jars
  removed even when nothing installs (cubeonfriends.py:135-143).
- **Protection**: `PROTECTED_MOD_STEM_PREFIXES` (mods.py:417) means the Mods UI can't
  remove/disable CSL or friends and they're re-synced every launch.

## One watch-item (NOT a confirmed bug — did not change code)

`friends_service.invite()` host launch (friends_service.py:571-578) relies on
`state["mod_loader"]` rather than the pack-aware resolution main.py's Play path performs.
It's currently safe because `go_to_pack` (main.py:2282) keeps `state["mod_loader"]` in sync
with the selected pack and the loader toggle is locked to installed loaders. Flagged here so
a future change that lets Play-tab loader state diverge from an installed pack re-checks this
site.

## Verification

All green, exit 0:
- `python3 tools/test_csl.py` — "ALL CSL CHECKS PASSED"
- `python3 tools/test_mod_matrix.py` — 68 passed
- `python3 tools/test_versions_profile_key.py` — 11 passed
- `python3 tools/test_modpacks.py` — 51 passed
- `python3 tools/test_mod_store.py` — 21 passed
- `python3 tools/test_friends_service.py` — 136 passed
