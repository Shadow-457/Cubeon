# Store dangling-link fixes verified + loader-row profile-key bug FIXED + profile cleanup

## What was done
1. Verified the `cubeon/mods.py` dangling-link fixes shipped in the previous session
   (`sync_mods_to_game` skipping entries where `not os.path.isfile(src_full)`;
   `delete_mod` using `os.path.lexists`): `tools/test_mod_store.py` 21 passed,
   `test_modpacks.py` 51, `test_modpacks_cf_keyless.py` 28, `test_ui_smoke.py` 40,
   `py_compile` clean. Earlier full-matrix (21 suites) pass predates only these
   `mods.py` edits, which no other suite exercises, so the audit stands.

2. **FIXED: selecting a loader version row silently synced the wrong profile.**
   The Play-tab dropdown lists both `26.1.2` and `fabric-loader-0.19.5-26.1.2`
   (main.py builds options from every installed version, no filter). Selecting the
   loader row derived `selected_mc_version = "0.19.5"` (extract_mc_version grabbed the
   FIRST numeric group = the Fabric loader version), so the Mods tab and launch-time
   sync pointed at the empty `0.19.5-fabric` profile; the wrong id also persisted via
   `cfg["last_version"]`. Normal base-row selection and the modpack Play path
   (`go_to_pack`) were already safe.
   - `cubeon/versions.py extract_mc_version`: canonical `fabric-loader-`/`quilt-loader-`
     ids now return the LAST numeric group (the trailing MC version). Forge ids
     (`1.20.1-forge-47.2.0`), vanilla, TLauncher names unchanged. NeoForge's own
     versioning (`neoforge-21.1.99`, no decodable MC) deliberately left alone.
   - `main.py do_install_and_launch`: loader-support checks and install now key off
     `base_version = extract_mc_version(version_id)` instead of the raw launch id, so a
     loader row no longer prints the bogus "Fabric unsupported for this version, using
     vanilla" (and TLauncher renamed ids check/install against their real MC version).
   - New regression suite `tools/test_versions_profile_key.py` (11 passed) covers both
     the extraction and the base-row == loader-row profile-key equality.
   - Verified against the user's real disk: `extract("fabric-loader-0.19.5-26.1.2")`
     now = `26.1.2`, profile keys agree.

3. **CLEANED the default profile (user decision: start clean).** `~/.cubeon_launcher/
   mod_profiles/26.1.2-fabric` was a mix of the Sep 3 curated "FPS Modpack" install
   (10 new-store links into `~/.cubeon_minecraft/global_mods/` + Wurst real file) and
   33 pre-migration leftovers linking into the OLD `~/.cubeon_launcher/global_cache/`.
   Removed all 33 old-store links **and their `.cubeon.json` sidecars** (64 files).
   The profile is now exactly the pack set: c2me, cloth-config, cubeon-friends,
   fabric-api-0.150.0, ImmediatelyFast-1.15.2, iris, modmenu-beta, reeses-sodium-options,
   sodium-extra, sodium + Wurst. `list_mods("26.1.2","fabric")` returns 11 enabled,
   all new-store backed, zero dangles. The old `~/.cubeon_launcher` dir (incl. its
   `global_cache/` and the other profiles 1.20.1/1.21.11/1.21.8/unknown-fabric) is left
   untouched as an archive; those other profiles still resolve and are now protected by
   the dangling-link handling if the old dir is ever deleted.

## How verified
`tools/test_versions_profile_key.py` 11 passed; full matrix re-run green for the touched
suites; real-disk `list_mods` shows the cleaned 11-entry profile with correct store
links and sizes. NOTE: the profile dir path is still under the old `~/.cubeon_launcher/
mod_profiles` (paths.py `PROFILES_DIR`) while the store/game dir are the new
`~/.cubeon_minecraft/` - that split is intentional per the migration context.

## Question for the next agent / user decision (unchanged)
Should Cubeon offer to import the other old-store-backed profiles (`1.20.1-fabric`,
`1.21.11-fabric`, etc.) into the new tree on first run, or is starting each private
game dir clean intended? The old store (`~/.cubeon_launcher/global_cache/mods`, 43 jars)
still exists and backs those profiles.
