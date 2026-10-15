# 2026-10-15 — Version management: cleaner files, clearer picker, real manager

## What the user asked for
"make the version managment better" — and, from the follow-up list, all of it:
a clearer version picker, a real Instances manager, richer "Jump back in"
cards, better online browsing, any version-management bug, and a better file
structure.

## What changed

### File structure (the "in the file structure" half)
The Play tab's version-management surface was ~350 lines of Flet closures
stranded inside `main()`'s 4,000-line body, which made it impossible to reuse
or test. It is now two modules:

- **`cubeon/instances.py`** (new) — pure data, no Flet. One place answers
  "what loader is this, how many mods, how big, when did I last play it":
  `detect_loader`, `describe` / `list_installed`, `instance_size_bytes`,
  `format_size`, and a `mark_played` / `last_played` sidecar. The recursive
  size walk is deliberately kept OUT of `describe` — the Play tab rebuilds its
  cards on the event loop, so callers that want the size (the manager) ask for
  it explicitly and off-thread.
- **`ui/versions.py`** (new) — the view half: `VersionPicker`, `InstanceCards`,
  `InstancesManager`. Pure view code: callbacks + descriptor dicts in, no
  config / network / game-dir access.

`main.py` now just wires those in; the old inline
`_instance_card` / `_rebuild_instance_cards` / `_sync_version_button` /
`_rebuild_pick_list` / `version_pick_dialog` are gone.

### The user-visible improvements
1. **Picker** — rows are grouped `Installed` / `Available to download`
   (headers only appear once the online list actually mixes both), each row is
   tagged with its loader, a `snapshot` badge and its release date, and a
   "Latest release" shortcut jumps straight to the current release. The search
   still filters the dialog's own snapshot and never touches the live dropdown.
2. **Richer cards** — each "Jump back in" card now shows a loader chip, its
   mod count and "played 3h ago". The card is still built once and only
   restyled / has its (imageless) chip row refreshed, so the no-reload
   invariant holds.
3. **Instances manager** — a `Manage` button next to "Jump back in" opens a
   dialog listing every install with loader, mod count, on-disk size (computed
   on a worker) and last-played, plus per-row **Play / Rename / Delete**.
   `on_rename_instance` / `on_delete_instance` now take an optional `vid=` so a
   row can target any instance, not just the selected one.
4. **Last played** is recorded at launch into a tiny
   `~/.cubeon_launcher/instance_play.json` sidecar (`instance_info.mark_played`).
   Not config.json — that is the most-written file in the launcher and churning
   it on every launch for a cosmetic label is wasteful.
5. `cubeon/versions.get_available_versions()` now carries `releaseTime` (already
   in the manifest we fetched — free) so the picker can show dates.

## Verification
- New `tools/test_instances.py` → 36/36 (loader detection incl. the
  forge-vs-neoforge whole-word trap, size formatting, describe/list, size walk,
  last-played round-trip and relative-time labels).
- New `tools/test_version_ui.py` → 22/22 (boots the REAL UI headless with a
  vanilla + a Fabric instance carrying 2 mods: card chips, picker grouping /
  tags / dates / snapshot badge / search, and the manager's list + actions).
- `tools/test_ui_smoke.py` → 196/196. Updated the "version picker filters its
  own list" check to assert the invariant against `ui/versions.py` now that the
  implementation moved.
- `tools/test_version_art_cache.py` → 15/15 (the no-rebuild card invariant).
- `tools/test_mega_smoke.py --suites` → 39/39; added `test_instances.py`,
  `test_version_art_cache.py` and `test_version_ui.py` to the sub-suite list.

## Note for the next agent
- The `ft.Dropdown` in `main()` is still the source of truth (dozens of paths
  read/write it); `refresh_version_list` feeds `picker.set_source(...)` richer
  entry dicts while keeping the plain option text. Don't make the picker mutate
  the dropdown.
- `instances.mod_count` calls `cubeon.mods.list_mods`, which reads
  `resolve_profile_dir` — that is why `tools/test_version_ui.py` seeds mods
  through `resolve_profile_dir` and not `get_profile_dir` (the fuzz stubs only
  redirect the latter).
- "Last played" only shows for versions launched since this change; older
  installs legitimately have no record.
