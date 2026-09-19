# 2026-09-11 — Version-list network fix, Update-button crash, and the FPS boost

## What the user asked for
1. A friend's launcher showed a network error loading the Minecraft version
   list even though his network was fine.
2. The launcher should launch Minecraft with the best possible FPS (launcher side).
3. The in-game Cubeon Client should, once activated, give a large FPS boost
   ("like Sodium/Lithium" — 73 FPS → 300+ FPS).

## 1. Version-list network error
`cubeon/versions.py:199` called `mll.utils.get_version_list()`, which is one
bare `requests.get` of one hostname with **no timeout, no retry and no cache**.
Any DNS/TLS/routing hiccup on that single name made the whole list fail and
the UI showed "No internet. Showing installed versions only."

Fix (`cubeon/versions.py`):
- `MANIFEST_URLS` = `piston-meta.mojang.com` then `launchermeta.mojang.com`.
- `_download_manifest()` tries each with `net.get_with_retry` (timeout 15s,
  2 attempts), accepts only a dict with `versions`, and skips a captive-portal
  200 that isn't JSON.
- `_manifest()` wraps that in `local_cache.cached_call("mojang_manifest","v2",
  max_age=3600, stale_ok=True, background_refresh=False)`, so both mirrors
  failing still serves the last good list instead of declaring the user offline.
- `get_available_versions()` / `get_latest_release()` read `_manifest()`, not mll.
- Offline with NOTHING cached still raises → the existing offline notice shows.

## 2. "Update game version" button always raised
`main.py`'s `on_update_version` called `_newest_release_key()`, but that
function **did not exist anywhere** (AST-verified; not in the diff either). The
`except Exception as ex` swallowed it, so the button just printed
"Update check failed: name '_newest_release_key' is not defined".
Added the nested helper next to `_is_legacy_version` (pure numeric parse, skips
snapshot ids, falls back to `core.get_latest_release()` when the online list is
empty).

## 3. Launcher side: JVM / launch flags
`cubeon/launch.py` `build_launch_command` only passed `-Xmx`/`-Xms`.
- Added `CLIENT_JVM_FLAGS` (G1GC, `MaxGCPauseMillis=50`,
  `ParallelRefProcEnabled`, `UnlockExperimentalVMOptions`,
  `DisableExplicitGC`, `G1NewSizePercent=20`, `G1ReservePercent=20`). Kept
  lighter than the server's Aikar set and valid on Java 8–25 (Cubeon launches
  across that range).
- `-Xms` now equals `-Xmx` (was min(ram,1024)) so the heap never resizes
  mid-game — that resize is a visible stutter.

## 4. Client side: the actual FPS boost
The Cubeon Client is a social mod (badge + Friends screen) and contributes
~0 FPS by itself; reimplementing Sodium inside it is neither feasible nor
wise. The honest fix is to make activating the client ALSO bring the real
frame-rate mods. New `cubeon/perf_mods.py`:
- `PERF_MOD_SLUGS = ("sodium", "lithium")`, fetched from Modrinth through the
  normal `get_mod_download`/`download_mod` path, matched to
  (mc_version, loader).
- `_present()` matches slug / display_name / project_id / filename so a
  hand-installed jar is never duplicated (two Sodiums = crash).
- Best-effort: no build, offline, or a download error returns
  `{"installed","kept","failed","detail"}`, never raises.
- `launch.py` calls it before `sync_mods_to_game` when
  `cfg["client_mod_enabled"]` is on (and the config-only `perf_mods_enabled`,
  default True) and loader is Fabric/Quilt. Originally had its own Settings
  checkbox; **removed on request** — no FPS toggle appears in Settings, and
  Sodium's own in-game settings are left alone.

I chose install-at-launch over Jar-in-Jar bundling: JiJ would freeze a single
Sodium build into the mod jar (wrong for every MC version but one), risk Mixin
conflicts, and redistribute under other licenses. The launcher already knows
how to fetch the right build per profile.

## 5. In-game mod hot path (small, honest)
The only per-frame code the mod owns is `Nametag.decorate`, called from
`PlayerNameMixin` via `Player.getDisplayName()` **once per visible player per
frame**. It already cached the name set behind a bridge revision, but the
lookup still did `plainName.toLowerCase(Locale.ROOT)` for every call — a fresh
String per player per frame, even for non-Cubeon names, i.e. pure GC pressure
on the render thread. Switched the cached set to a `TreeSet` with
`String.CASE_INSENSITIVE_ORDER` so `contains(name)` compares in place with no
copy. Everything else the mod does is on the background poll thread (6s idle /
1.2s with the screen open) or only while a menu is open, so there is no other
render-path work to optimize — the large gain is the Sodium/Lithium install
above, and claiming otherwise would be dishonest.

## Verification
- `tools/test_versions_manifest.py` (new) 10/10 — mirror fallthrough, empty
  manifest rejection, type filtering, stale fallback, raise-with-no-cache.
- `tools/test_perf_mods.py` (new) 15/15 — install order, dedupe by every
  field, non-Fabric no-op, failure reporting, G1GC/Xms presence.
- `tools/test_ui_smoke.py` 105/105. Sweep green: test_versions_profile_key 11,
  test_launch_indicator 11, test_production 13, test_csl, test_net 19,
  test_client_json 40, test_friends 37, test_gallery 38, test_invites 127,
  test_modpacks 51, test_mod_store 21, test_milestones 50 (known flake failed
  once, passed on rerun).
- Mod side: `tools/test_mod_compile.py` clean, `test_mod_bridge.py` 119/119,
  `test_mod_matrix.py` 68/68 after the Nametag change.

## Files
- `cubeon/versions.py`, `main.py`, `cubeon/launch.py`, `cubeon/config.py`,
  `cubeon/perf_mods.py` (new), `ui/settings_tab.py`.
- `mod/src/main/java/com/cubeon/client/Nametag.java` (case-insensitive set).
- `tools/test_versions_manifest.py`, `tools/test_perf_mods.py` (new).
- `agents/docs/module-map.md`: perf_mods row + FPS boost / client JVM flags /
  version manifest bullets, and the `_newest_release_key` note.

## Note for the next agent
The "+300 FPS" the user asked for is delivered by Sodium/Lithium, which the
launcher installs; the Cubeon Client itself is a social mod and cannot and
should not try to be a renderer. Don't be tempted to bolt fake "FPS"
optimizations into it to look busy — the Nametag lookup above is the only
per-frame code it has.

Sodium/Lithium are installed but never removed when the FPS toggle is turned
off — deliberately, so we don't delete a mod the user may want. If the product
decides "off must also remove", model it on `csl.remove_pending_entries`, not
on a blind glob.
