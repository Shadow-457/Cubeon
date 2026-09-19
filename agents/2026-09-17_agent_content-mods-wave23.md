# 2026-09-17 — content/mods/UI bug wave 2+3 (verified bug list)

Scope: cubeon/{mods,content,perf_mods,csl,version_art,modpacks,gallery}.py,
ui/mods_tab.py, ui/modpacks_tab.py + matching tools/ harnesses. No commits.

## Fixed (file:line approx)
- **C2** content.py `_sync_content_type` (~852-895): recorded staging entries
  are now replaced atomically (temp sibling in the staging dir + os.replace,
  dir case swaps via backup). Only entries in `.cubeon-staged.json` are
  re-pointed; foreign files still untouched (adoption unchanged).
- **C3** mods.py get_mod_versions (~991-1036): cache stores RAW releases
  (project-keyed); `compatible` recomputed per call from mc_version/loader.
  allow_network=False reads the stale tier and recomputes too.
- **C4/C5** ui/mods_tab.py build_browse_row + open_mod_detail: content type,
  mc_version, version_id, loader snapshotted at click; lookup/install/detail
  all use the snapshot; row click passes the captured type so a pack detail
  dialog installs via download_content with fix_cb/progress, not the mod
  installer. Detail install now checks result["failed"] and routes through
  on_error ("Installed, but dependencies failed: …") instead of clean success.
- **C7** modpacks.py `_content_profile_dest` (~285): strips only the leading
  content-type dir; nested folder-pack paths survive, containment via
  _safe_relpath on the full relative path.
- **C8** content.py `_store_entry` (~250-270): copies into a unique
  .store-* temp sibling then os.replace; failure leaves no partial final file.
- **C9** mods.py installed_project_ids (~1567): only ENABLED jars satisfy;
  a disabled dep is downloaded/enabled by install_mod_with_dependencies.
- **C12** content.py list_content third param keyword-only (`*`); all
  mods_tab call sites pass loader=/version_id= as kwargs.
- **C13** mods_tab browse generation token (query, mc, version id, loader,
  type, category); stale search/recommend completions are dropped.
- **C14** modpacks_tab run_search: per-generation provider maps + lock;
  merge re-rendered after each completion (either order survives).
- **C15** mods_tab install worker per-chunk page.update() →
  thread_safe_ui.refresh(download_btn) (5 sites).
- **C16** detail-dialog partial-success surfaced via on_error; doctor only
  for the mod type.
- **C17/C18** csl.py install(): passes hashes=; catches Exception (net
  DownloadError + wrapper failures) returning the documented statuses.
- **C19** mods.resolve_profile_dir + content.resolve_content_profile_dir
  (no mkdir); list_mods/list_content/is_installed/content_compat use them.
- **C20** perf_mods._present: exact slug/project-id/stem identity match
  (name_stem("sodium-extra-...") = "sodium-extra" ≠ "sodium").
- **C21** version_art get_version_art: `hit is None or isfile(hit)` — misses
  now memoized.
- **Gallery stale preview** gallery.py `_ensure_previews`: per-dst memo keyed
  on (path, mtime_ns, size); _library_files signature now (mtime_ns, size)
  so same-size rewrites invalidate the catalog; _save_installed now uses
  atomicio.write_json (peer's fix, untouched otherwise).

## C6 note
C6 source fix (mkstemp + staged link_into_place) was applied by main in
global_mod_cache.py; I added the regressions in test_mod_store
(concurrent same-dest fetch via Barrier, copy-failure preserves dest).
27/27 there.

## Test results (this session)
- test_content_instance 18/0 (was 9: +read-only scans, same-name staging
  swap link+copy paths, failed-copy atomicity)
- test_mod_detail 81/0 (was 66: +per-profile compatible, disabled-dep,
  browse snapshot, stale render, C16, C15, C12, C14, art memo)
- test_mod_install_progress 39/0 · test_mod_store 27/0 · test_modpacks 64/0
  (61 baseline + fixed stale assertion + 2 folder-pack checks)
- test_perf_mods 17/0 · test_gallery 32/0 · test_csl 59 checks ·
  test_mod_matrix 68/0 · test_capes 19/0 · mega --static 12/0 ·
  ui_smoke 148/0
- app_driver explore: 562 actions, 0 errors, 0 None-children (blocked only
  by the pre-existing main.py NameError below).

## SUSPECTED / out-of-scope findings
- **main.py:2768** `launch_session["id"] = session_id` in
  do_install_and_launch — NameError (session_id unbound in that scope;
  launch.py hands it to on_exit only). Reproduces in explore + full mega.
  Posted to main/launch owner.
- test_content_doctor.py currently crashes at import/run with
  `ValueError: Can't manage resource packs: no Minecraft version selected.`
  — identical on a stashed tree (pre-existing, unrelated to my diff);
  needs the content-doctor owner's attention.
- transient mid-session reverts of peer-edited files (minekube syntax error,
  skin_tab signatures) were observed and later cleared on rerun.
