# 2026-10-14 — Bug hunt: fixed 7 launcher/site bugs (vanilla loader, import dedup, friends UID, error-page status)

## What the user asked for
First: "find and tell me bugs" across the launcher + site. I audited the code,
ranked 7 real bugs. Then: "fix all".

## The 7 bugs and their fixes

1. **Double Play launch (`main.py`)** — `state["installing_version"]` had no
   in-flight guard, so two Play clicks launched two installs. Fixed with an
   atomic claim under `_launch_state_lock` at the top of
   `_begin_install_and_launch` (snack on duplicate), and the thread `.start()`
   is wrapped so a failure releases the claim. The existing `finally` already
   clears per-version state.

2. **NeoForge mod-sync (`cubeon/versions.py`)** — `extract_mc_version` returned
   the wrong key for NeoForge ids (`neoforge-21.1.99` → `21.1.99`), so mods
   synced from an empty folder and `find_installed_loader_version` missed →
   reinstall every launch. Fixed with `_inherited_base_version()` (reads
   `inheritsFrom` from the on-disk version json, traversal-guarded) and a
   `^neoforge-\d+\.\d+\.\d+$` intercept in `extract_mc_version`. No arithmetic
   guess (47.x/26.x era numbers would be wrong). `tools/test_versions_profile_key.py`
   section 3 rewritten → 13/13.

3. **`/linuxdeb` 404 (`worker/cubeon-downloads.js`)** — pinned
   `cubeon_1.0.0_amd64.deb` while `APP_VERSION` was 1.0.4. Now `FILES["/linuxdeb"]`
   uses `{prefix:"cubeon_", suffix:"_amd64.deb"}` resolved through a new
   `pickLatestPrefixed()` (numeric-segment version compare so 1.0.10 > 1.0.9).
   Upload a normally-named deb; no alias needed.

4. **Import dedup (`cubeon/importer.py`)** — `_zip_folder_to_temp` used a
   random `mkstemp` name, so stored packs were `tmpAbC123.zip` and dedup never
   matched → a new copy every rescan. Now stages in a `cubeon-pack-*` dir with
   the exact `<folder>.zip` name (`_safe_name`-sanitized); `_cleanup` removes
   zip + parent; the pack guard in `import_item` consolidates on bytes /
   origin-hash / `_stem`. 17/17 checks.

5. **Error-page assets (`web/{403,404,429,500,502,503}.html`)** — relative
   `href="assets/"` broke at deep paths. All asset refs are now absolute
   (`/assets/site.css`, etc.). 5 absolute refs per page.

6. **Error pages served at HTTP 200 (`web/vercel.json`)** — added a `routes`
   block so each error page is served at its real status (403/429/500/502/503/404)
   instead of 200. **No catch-all** route: the download redirects must keep
   working, and real misses already return a native 404. `web/_redirects`
   rewritten as an honest "NOT APPLIED" note. `tools/test_web_download_count.py`
   → 73/73.

7. **`tools/test_friends_service.py` 4 failures — STALE TESTS, not product bugs.**
   Commit `c28b8f0` shortened Cubeon IDs 12 → 8 digits (`UID_WIDTH=8`,
   `_UID_RE=^[0-9]{8}$`, `cubeon/friends.py:178-179`), matching the worker
   (`worker/cubeon-friends.js`). `canonical_uid` migrates a legacy 12-digit value
   to its 8-digit form, so the fixtures' 12-digit literals no longer matched the
   canonicalized returns. Code is correct; fixtures were stale. Updated the 4
   assertion literals → 8-digit (`00000023`, `00000021`, `00000011`, `00000002`).
   → 372 passed, 0 failed (was 368/4).

## Verification
- Full suite: 47/48 suites green. `py_compile` OK on all 5 changed .py files;
  `node --check` OK on the worker.
- **1 pre-existing failure, NOT mine** (confirmed by `git stash` on clean
  `e5bf6b9`): `tools/test_mod_compile.py` — `YggdrasilSessionServiceMixin.java`
  (cracked-proxy session bypass, added in `95b33b3`) is registered in
  `cubeon-client.mixins.json` but missing from `MOD_SOURCES`
  (`tools/test_mod_compile.py:47`) and `REQUIRED_ENTRIES`
  (`tools/build_mod_jars.py:76`). So `build_mod_jars` can't detect a half-compile
  that drops this required runtime mixin. 2-line fix (register in both lists);
  left out of scope for this bug hunt.
- Live site redeploy still pending (vercel.json + worker fixes need deploy;
  worker via `npx wrangler deploy -c wrangler-downloads.toml`).

## Not touched / still open
- LemonMC Velocity `join` (server-side), JDK 25 needed for the `26` mod
  bracket, `ft.Icon .name` vs `.icon` (unconfirmed).
- 15 files modified, uncommitted (user has not asked to commit/push).
