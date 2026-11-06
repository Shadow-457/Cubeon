# Instance content storage and migration

Implemented in the local source tree and verified with temporary installations.
Native Windows migration/restart validation remains required before stable.

## Layout and scope

Content migration isolates **mods, resource packs (texture packs) and shaders**.
The subsequent organization step gives visible instance folders readable names
and moves shared assets/libraries/version files inside `instances/.runtime/`.
Worlds, configs and settings always stay with their own instance. They are never
merged or reassigned; a folder rename moves the existing files together.

```text
.cubeon_minecraft/
  instances/
    storage.json               version IDs -> visible instance folders
    migration.json             content migration and cleanup journal
    layout-migration.json      folder/runtime move journal
    .runtime/                  shared Minecraft downloads, real folders
      versions/                original loader IDs stay internal
      assets/
      libraries/
    26.3-Fabric/                readable migrated instance folder
      instance.json            stable identity, game_subdir: "."
      .cubeon/mods/            launcher receipts and mod metadata
      mods/
      resourcepacks/
      shaderpacks/
      saves/                   each world is a folder with level.dat
      config/
      options.txt
    My Survival/               custom instance names are preserved
      instance.json
      minecraft/               some instances use this existing inner layout
        saves/
        mods/
        config/
  backups/
    legacy-content/            original content folders/links and shared stores
    interrupted-migration/    copies from interrupted content inventories
```

New instances use readable names from their first folder lookup, with shared
runtime downloads under `instances/.runtime/`. Existing nested `minecraft/`
game directories remain nested. Folder names are separate from immutable
manifest IDs/profile keys and internal Minecraft version IDs. Custom display
labels and pack names take priority when organizing existing folders; collisions
get a numbered suffix, and new-folder collisions use a stable short suffix.

The old root `versions`, `assets` and `libraries` directories disappear through
whole-folder moves after verification, with no duplicate runtime copy or link.
Unrelated Java installations under `runtime/` stay intact. The original global
content stores remain active while any instance migration is pending, then move
to one recovery archive under `backups/legacy-content/`.

## Path contracts

- `storage.initialize()` records existing version IDs as legacy. Before normal
  startup jobs, it recovers an interrupted content switch from its journal.
  It does not inventory or migrate other player data.
- `storage.game_dir()` interprets manifest `game_subdir`: `.` for an instance
  whose original folder was retained, `minecraft` (also the default when the
  field is absent) for the nested layout. Consumers must use this resolver.
- `mods.resolve_profile_dir()` and content resolvers point directly to each
  registered instance's real content folders. Launch sync becomes a no-op.
  Read-only resolution never creates folders or adopts shared worlds.
- Download caches publish independent files. Clearing a cache cannot remove
  installed mods or packs. Manual JAR additions need no metadata sidecar.
- `storage.metadata_path()` puts launcher receipts and pack markers under
  `<instance>/.cubeon/mods/` for both layouts. File-removal receipts preserve
  manual opt-outs from automatically installed client/performance mods.
- Backups use resolved paths for both layouts and include each world once.
  Screenshot discovery deduplicates retained shared screenshot links.

## Migration interaction

The launcher offers **Organize Minecraft files** at startup when legacy instances
remain, and under **Settings → Files**.

1. A read-only content inventory estimates copy space. It scans names and sizes;
   hashing begins only after **Migrate now**. **Later** cancels that scan and
   leaves the current setup active. Root worlds/settings never block the prompt.
2. **Migrate now** checks disk space, game/install activity, launcher sessions and
   a process lock. Normal writes and application updates remain blocked during
   migration. **Pause** stops copying at a recoverable boundary.
3. The instance's profile content and local additions are copied and hashed in
   `instances/.content-migration/`. Files with conflicting destinations stop for
   review; external content links and cycles are rejected. Legacy launch staging
   is not copied into other instances.
4. After verification, a journal records the intended replacements. The three
   original content folders/links are renamed intact to `backups/legacy-content/`,
   then replaced with verified real folders at the same paths. Launcher mod
   metadata and `instance.json` are published alongside them. Only then does the
   atomic registry update commit the instance. Worlds/settings are never renamed.
5. Once every instance is committed, cleanup verifies that their three content
   folders contain no links. It renames only `global_mods`, `global_content`,
   `mods`, `resourcepacks` and `shaderpacks` from the main root into
   `backups/legacy-content/shared-<id>/`. Whole-folder renames preserve original
   bytes without extra copy space. Unassigned old content is retained too.
   The journal records intent and folder identity before moving; interrupted
   cleanup resumes without overwriting a conflicting destination. The registry's
   `content_cleanup: 1` marks completion and `content_backup` records the archive.
6. Existing completed installations get **Organize folders** when folder/runtime
   organization is pending, or **Finish cleanup** for cleanup alone. Neither
   repeats completed content copies. Ordinary launches/downloads use the new
   instance/cache paths and do not recreate root global content folders.
7. `storage_layout.organize_locked()` renames visible instance folders in place
   and moves official `versions/assets/libraries` into `instances/.runtime/`.
   `runtime_dir()` switches only after all runtime moves complete. Instance IDs
   and profile keys are preserved. `previous_game_dirs` resolves the saved active
   instance even when its old folder name no longer exists.
8. **Restart Launcher** / **Exit** appears after a committed switch or cleanup. Normal writes
   stay blocked until a fresh process reloads the paths.

## Recovery and compatibility

- A failed uncommitted switch restores the prior content folders/links. If the
  process dies mid-switch, startup rolls back before legacy launch sync can run.
  If the registry already committed, recovery keeps the installed folders and
  any newer changes. Failed rollback blocks normal use until restart/recovery.
- Partial content copies can resume. Changed inventories preserve prior copies
  under interrupted-migration backups. Old broad-migration journals and stages
  are retained, but never reused to copy worlds/settings/runtime. Old in-memory
  plans are rescanned under the content-only scope.
- Missing/corrupt registry or manifests fail closed. `instances/.layout-v2.json`
  guards against silently reactivating an unregistered old game directory.
- Cleanup is limited to the five known legacy content folders. It must not
  rename arbitrary root entries, old profiles, worlds/configs or skin folders.
  The separate approved organization step moves only official runtime folders
  and complete registered instance folders. Legacy profile links become inactive; restoring archived folder
  names to their original root reactivates those recovery links. The archive's
  `recovery.json` records this. Deleting an instance archives its game folder.
  Pack transactions restore metadata and undo only their own new registration.
- Older launcher binaries may still run legacy content sync and do not understand
  the registry. Downgrading is not a migration rollback.

## Verification

`tools/test_instance_storage.py` covers exact preservation of unrelated file
bytes/identities/timestamps and game paths, UI without ownership selection,
content independence, local additions, conflict/disk/source-change failures,
copy interruption, replacement/registry failure, killed-process startup recovery,
old journals, committed nested instances, backups and shared screenshot routing.
Cleanup checks cover clean roots, exact retained originals, partial migration,
previously completed migrations, active links, interruption after rename/before
journal progress, registry failure, resumability and no recreated global paths.

Related checks: `test_instance_game_dirs.py`, `test_content_instance.py`,
`test_local_mod_import.py`, `test_modpack_integrity.py`,
`test_screenshot_gallery.py`, and the default `test_mega_smoke.py` gate.
Native Windows locked-file/junction/restart checks and representative upgrade
copies remain release prerequisites. No FPS recording is part of this work.

Folder/runtime organization has its own intent journal. Rename failure restores
an instance's prior name and manifest; runtime failure restores every moved
runtime part before old paths can be used. Startup recovers killed operations
before registering the launcher session. Once a registry switch commits,
recovery retains that location and newer player changes. Tests cover these
boundaries, readable/custom/colliding names, active-world paths, backup/deletion,
and real mll command generation and existing-version installer lookup.
