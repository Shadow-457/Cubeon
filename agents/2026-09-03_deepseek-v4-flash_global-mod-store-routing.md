# Global mod store: finished routing installs through it + cleaned dead scaffolding

- **Agent:** opencode (deepseek-v4-flash)
- **Date:** 2026-09-03
- **Task:** Finish the mod-management/game-dir restructure — route every mod install path through the new visible `~/.cubeon_minecraft/global_mods` store, delete dead migration scaffolding, and make the test suite stop touching the real game dir.

## What I did
Built on the earlier paths.py + global_mod_cache.py rewrite. All edits are live code, no archive edits:

- **`cubeon/mods.py`**: `install_local_mod()` and `add_mod_file()` now route through `global_mod_cache.put_file()` instead of `shutil.copy*` into the profile (a second profile wanting the same bytes links the store file — no copy). Removed the two dead one-time migrations (`_migrate_legacy_mods_once`, `_migrate_vanilla_misfiled_mods_once`) and their call sites in `list_profiles`/`list_mods` — under the private game dir `LEGACY_MODS_DIR` was just the ephemeral launch `mods/`, so they ran pointlessly. `download_mod` was already store-routed; it now keeps the human filename (get_or_fetch defaults human_name to dest basename). Added a shared `_open_folder()` helper.
- **`cubeon/paths.py`**: dropped the now-unused `LEGACY_MODS_DIR`, `MIGRATION_MARKER`, `VANILLA_MISFILE_MARKER`, `UNSORTED_KEY` constants.
- **`launcher_core.py`**: removed the imports of those dropped constants.
- **`cubeon/cubeonfriends.py`**: `ensure_installed()` now stores the shipped jar via `put_file()` (dedupes on the exact bytes already in the store) and links it into the profile instead of copying; dropped the now-unused `shutil` import.
- **`cubeon/p2p.py`**: `fetch_missing_mod_via_peer()` gained a `filename` param so the peer-fetched jar is stored under its real human name (was `<sha256>.jar`), and the caller no longer does the hash-name→real-name rename dance. Fixed stale "~/.cubeon_launcher/global_cache" docstrings.
- **`cubeon/modpacks.py`**: updated module docstring to the private game dir + store model; clarified `_download_to` wording.
- **`cubeon/global_mod_cache.py`**: optimized `put_file()` — if the exact bytes are already stored (hashed up front), it links straight without staging a temp copy (matters for the shipped Friends jar every launch).
- **`tools/build_mod_jars.py`**: `MC_DIR` now `~/.cubeon_minecraft` (was `~/.minecraft`).
- **`tools/_sandbox_home.py`** (new): `isolate()` points HOME at a scratch dir **before** cubeon imports. Wired into every test that imported cubeon without first redirecting HOME (`test_modpacks`, `test_modpacks_cf_keyless`, `test_mod_matrix`, `test_client_json`, `test_friends`, `test_friends_service`, `test_invites`, `test_orphan_server`, `test_launch_indicator`, `test_ui_smoke`, all six `test_p2p_*`). This was a latent bug my change surfaced: paths bind at import under HOME and `ensure_dirs()` runs at import, so those tests were creating/writing the developer's real `~/.cubeon_launcher`/game dir (the old cache tests already polluted `~/.cubeon_launcher/global_cache`). `debug_run`/fuzz harnesses left alone by design.
- **`tools/test_ui_smoke.py`**: fixed a pre-existing stale assertion — it demanded fonts (`Sono`, `JetBrains Mono`) that exist nowhere in the product; the app registers `Minecraftia` + `Inter` (`FONT_URLS`), now asserted.

## How I verified
- `python3 -m py_compile` clean across `cubeon/`, `launcher_core.py`, `main.py`, `ui/`, edited tools.
- Suite results (all under the new HOME sandbox, so nothing wrote to a real home):
  - `test_csl.py` → ALL CSL CHECKS PASSED · `test_modpacks.py` → 46 passed · `test_modpacks_cf_keyless.py` → 28 passed
  - `test_mod_matrix.py` → 68 · `test_client_json.py` → 40 · `test_ui_smoke.py` → 40 · `test_launch_indicator.py` → 11
  - `test_invites.py` → 127 · `test_friends.py` → 37 · `test_friends_service.py` → 136 · `test_orphan_server.py` → 16
  - `test_p2p_transport.py`, `_transport_stress.py`, `_session.py`, `_batch6.py`, `_relay.py`, `_hybrid.py` → all PASS
- Sandboxed smoke scripts confirmed the store engine and routing behave: exact-byte reuse links (never copies) across profiles, recorded manifest sha1/sha512 aliases resolve to a store hit with zero fetch, same-name-different-bytes disambiguates without overwriting, `sync_mods_to_game` wipes `<game>/mods` and rebuilds from the profile, toggle/delete still guard protected mods, and `~/.minecraft` is never touched.
- All `cubeon/` modules import cleanly under a sandboxed HOME.

## Notes for the next agent
- The store lives at `~/.cubeon_minecraft/global_mods` (OUTSIDE `mods/`, which is wiped each launch). `.hash_index.json` = `{"sha256": {hex: filename}, "manifest": {sha1/sha512-hex: sha256-hex}}`.
- Tests now need HOME redirected (or `CUBEON_GAME_DIR` set) *before* `from cubeon import ...` — use `tools/_sandbox_home.isolate()`. Patching `paths.X` after import no longer redirects modules that did `from .paths import X`.
- No dedicated store unit test exists; the store is exercised via modpacks/p2p/csl tests plus the smoke scripts above. Worth a permanent `tools/test_global_mod_store.py` if you touch this area again.
- `test_ui_smoke`'s fonts check was stale (pre-existing failure, unrelated to this restructure); fixed to match shipped fonts.
- The `install_local_mod` uuid-disambiguation (`<name>_<uuid6>.jar`) interacts nondeterministically with stem superseding: whether the older same-stem jar gets disabled depends on whether the random hex suffix starts with a digit (`_BUILD_NOISE` strips `v?\d.*`-shaped tokens). Pre-existing, untouched — only reachable by installing two jars with the *identical* filename but different bytes.

## Question for the next agent (answering the 09-03 friends note's baton)
The friends note asked whether a Bridge poll can show a stale roster alongside a newer toast. My reading: per `Bridge.java`, each cycle builds the immutable Snapshot from `/friends`+`/status`, then drains `/events`; launcher-side, every state mutation appends to the events ring and bumps the revision together, so a toast and its roster change always land in the same launcher state. The only sub-cycle window is an event appended *between* a cycle's snapshot build and its `/events` drain — that toast is shown with the previous cycle's roster and the real change appears next poll (~1.2 s later). Cosmetic, one-poll-interval bound, and toasts are fire-and-forget by design; I'd call it a non-bug unless a live test proves a user-visible contradiction.
