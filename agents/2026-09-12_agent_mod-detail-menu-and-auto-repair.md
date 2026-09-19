# 2026-09-12 — Mod detail menu + automatic mod repair

## What the user asked for
1. Clicking a mod should open a full menu for that mod: its pictures,
   description, details, and selectable/custom versions.
2. An automatic function that runs when a mod is installed or when any mod
   problem appears (conflicts, missing dependencies, etc.) and fixes it.

## 1. Mod detail menu
New core data calls in `cubeon/mods.py`, both behind the 6h `local_cache`:
- `get_mod_details(id_or_slug)` — one `GET /project/{id}`: gallery (featured
  image sorted first), `body` markdown, downloads/followers, categories,
  loaders, `game_versions`, licence, links. Returns the project record
  normalized for the UI; raises on an unresolvable project so the caller can
  show a "couldn't load" state instead of an empty menu.
- `get_mod_versions(id_or_slug, mc_version, loader)` — one
  `GET /project/{id}/version`: every release newest-first, each with its
  primary file (filename/url/size/hashes), loaders, game versions, deps, and a
  `compatible` flag for the browsed profile. No per-version requests.

UI (`ui/mods_tab.py:open_mod_detail()`), opened by clicking any browse row or
any installed-mod row (protected/system files and manually-dropped jars with
no Modrinth id have nothing to look up, so they don't open one). The dialog
shows cover art, gallery hero, metadata pills, markdown body, and the version
list with the matching build first, each with an Install button. Install uses
the existing `install_mod_with_dependencies`, then runs the doctor. Dialog
plumbing is `cubeon/dialogs.py` (Flet 0.86 stack); painting from the fetch
thread is `thread_safe_ui.refresh`. No new dependencies.

## 2. Automatic repair — `cubeon/mods.py:mod_doctor()`
Returns `{checked, problems, fixed, unfixed}` and never raises. Three checks,
each corresponding to a real "my mods won't load" cause:
1. **Duplicates** — same Modrinth id => older copy is DELETED (that is what
   updating means); same filename stem only => older copy is DISABLED
   (reversible). `supersede_older_copies` is called ONCE per group, not once
   per loser (a second call finds nothing and would mis-report the rest as
   unfixed).
2. **Missing required dependencies** — resolved through a cached
   `required_dependencies`, downloaded, and tracked in a local
   `installed_ids` set so two mods needing the same dep fetch it one time.
3. **No release for the current loader+mc_version** — the jar can never load,
   so it is DISABLED (`toggle_mod`), never deleted.

Wired in three places:
- After every mod install: browse quick-download, the detail-menu install
  button, and "Install from file".
- The Installed pane's **"Fix problems"** button (a real run with online
  dependency checking).
- At launch in `cubeon/launch.py`, with `check_online=False` (filesystem-only)
  so it can never delay starting the game.

User-facing wording stays plain — "Fix problems", "Fixed N of M problem(s)".
The word "doctor" never leaves the code.

## Verification
- `tools/test_mod_detail.py` (new) 31/31 — details parsing + featured-first
  gallery, version compatibility + primary file, duplicate delete/disable,
  missing-dependency install, incompatible disable, no-op guard, a runtime
  check that a real installed row's click opens the dialog and renders the
  fetch, and a launch-wiring source assertion.
- `tools/test_ui_smoke.py` 105/105.
- Full sweep green: capes 14, client_json 40, csl, friends 37,
  friends_service 213, fuzz 12, gallery 38, invites 127, launch_indicator 11,
  milestones 50, mod_bridge 119, mod_compile clean, mod_matrix 68,
  modpacks_cf_keyless 28, modpacks 51, mod_store 21, net 19, orphan_server 16,
  perf_mods 15, production 13, skins_net, versions_manifest 10,
  versions_profile_key 11.

## Files
- `cubeon/mods.py`: `get_mod_details`, `get_mod_versions`,
  `_required_deps_cached`, `mod_doctor`.
- `launcher_core.py`: re-export the three public functions.
- `ui/mods_tab.py`: `open_mod_detail` + the "Fix problems" action + row click
  wiring + post-install doctor.
- `cubeon/launch.py`: filesystem-only repair before `sync_mods_to_game`.
- `tools/test_mod_detail.py` (new).
- `agents/docs/module-map.md`: mod detail + mod_doctor bullets.

## Note for the next agent
- `supersede_older_copies` deletes/patches every other copy itself; calling it
  per duplicate in a group is a bug (only the first call fixes anything).
- The detail dialog is a new UI surface in `ui/mods_tab.py`; it follows the
  `main.py` version-picker dialog pattern (`cubeon/dialogs.py`). If you add
  another dialog there, reuse `dialogs.open_dialog`/`close_dialog` — do NOT
  touch `page.open()/close()` (gone in Flet 0.86).
- The launch-time repair is deliberately filesystem-only. If you ever pass
  `check_online=True` there, you are adding network calls to the launch path.
