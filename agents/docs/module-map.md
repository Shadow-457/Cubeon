# Cubeon module map — read this before reading any source

Last updated: 2026-09-04 (Cline Glm 5.3 flash). If a fact here contradicts the code, the code
wins — but fix this file too. Durable facts belong HERE, not in diary notes.

## What Cubeon is, in one paragraph

A Minecraft launcher (Python/Flet desktop UI) with a friends/social layer:
a Fabric mod (`mod/`) injects an in-game Friends screen (chat, P2P worlds,
mod-sync), talking to the launcher over a localhost HTTP bridge, which talks to
a Cloudflare Worker relay (`worker/`) over WebSocket. DMs and sync frames are
E2EE (`cubeon/e2ee.py`). Local server hosting is Paper-only, exposed to friends
via Minekube Connect tunnels.

## Repo layout (top level)

| Path | What it is |
|---|---|
| `main.py` | UI glue: builds tabs, owns FriendsService, avatars, dialogs. ~3000 lines. |
| `launcher_core.py` | Re-export shim over the `cubeon` package (legacy import surface). |
| `cubeon/` | All launcher logic (see table below). |
| `ui/` | Flet tab builders: `server_tab.py` (biggest), `mods_tab.py`, `modpacks_tab.py`, `skin_tab.py`. Pure builders — they receive `cfg`/`state` by reference and helpers (`section_label`, `pixel_divider`, theme) from main.py. |
| `mod/` | The in-game Fabric mod. `src/main/java/com/cubeon/friends/`: `CubeonFriendsScreen.java` (whole UI), `Bridge.java` (localhost HTTP client + snapshot parsing), `CubeonFriendsClient.java` (entrypoint, chat notices), `Json.java`. `brackets.json` = **single source of truth** for MC version brackets (read by build.gradle AND cubeonfriends.py). |
| `worker/` | Cloudflare Worker + Durable Object relay (`cubeon-friends.js`, `cubeon-invites.js`). Protocol constants must stay in parity with `cubeon/friends.py` (asserted by `tools/test_friends.py`). |
| `assets/jars/` | Shippable jars: both Friends mod jars + `connect-spigot.jar` (Minekube Connect). |
| `tools/` | Test harnesses (plain scripts printing `N passed, M failed`). |
| `agents/` | Agent notes (history) + `docs/` (guides) + this map. |
| `archive/` | Old PyInstaller output — ignore, never edit. |

## Key modules in `cubeon/`

| Module | Owns |
|---|---|
| `paths.py` | Every on-disk location + `ensure_disk_space()`. CUBEON_GAME_DIR env overrides the game dir (tests use it). |
| `friends_service.py` (~2800 lines) | Headless friends owner: roster, add/rename (local-state answers, no blocking lookups), E2EE chat, sync compare channel, P2P sessions, notification ring (200 events). Serves all bridge providers. |
| `local_api.py` | The localhost HTTP bridge the mod polls. Token file `~/.cubeon_launcher/local_api.json`, 0600, loopback only. |
| `friends.py` | Relay client (WebSocket, secret as first frame), name rules, identity.json, claim/rename. `T_*` constants = protocol truth. |
| `e2ee.py` | X25519 DM encryption; keys published to the relay under the claimed name. |
| `p2p.py` | P2P worlds: STUN + relay fallback, mod/asset sync, teardown. |
| `server.py` | Paper server hosting: install (Fill v3 API), start/stop, properties, orphan detection. |
| `minekube.py` | Public address tunnels: finds/installs Connect plugin, endpoint config. |
| `modpacks.py` / `mods.py` / `global_mod_cache.py` | Modrinth/CF packs; per-profile mods LINK into one global store (`~/.cubeon_minecraft/global_mods`) — never copy jars between profiles. |
| `cubeonfriends.py` | Which Friends jar goes into which profile (brackets), injected at launch. `mod_stamp()` = jar freshness fingerprint. |
| `launch.py` | `launch_game()` — injects CSL + friends jar, syncs mods, launches MC. Requires mc_version/loader, no silent defaults. |
| `config.py` | cfg schema, username validation, auth key (public_uuid/secret_token). |
| `gate.py` | Server join password (PBKDF2, escalating lockouts). |

## Facts that bite if you don't know them

- **Two jar namespaces**: MC ≤1.21 (obfuscated, loom, intermediary names) vs
  26.x (unobfuscated, plain javac). Two jars, chosen via `mod/brackets.json`.
  The mod compiles against a stub API subset (`tools/test_mod_compile.py`) —
  only API that exists identically in both eras. If javac fails on 26.x, the
  API moved; javap the real jar in `~/.minecraft/versions/26.1.2/26.1.2.jar`.
- **Everything user-facing must degrade to a human sentence.** No blocking
  calls on the mod's request thread; no raw exception text in the UI; errors
  and confirmations both land via the notification ring → in-game chat.
- **Launcher jar vs game jar staleness is guarded**: `mod_stamp` in the roster
  payload vs the mod's own hash → one-shot red chat warning.
- **On-disk roots**: `~/.cubeon_launcher` (launcher state, cache, servers),
  `~/.cubeon_minecraft` (game dir: versions/mods/global_mods). `~/.minecraft`
  must NEVER be touched.
- **Packaged launchers have no `mod/build/libs`** — jars must exist in
  `assets/jars/`. `find_jar` order: cache → assets/jars → build/libs.
- **The live relay lags the repo.** Features needing new Worker behavior
  (e.g. the T_SYSTEM "No Cubeon user" reply) must degrade gracefully; never
  block a request thread on the relay.
- **UI text policy** (user preference, enforced 2026-09-04): minimal visible
  text, hints live in tooltips, sections collapse behind toggles, no jargon
  (no "API", no raw errors) anywhere visible.

## Tests — run these, in this order of relevance

```
python3 tools/test_friends_service.py   # 180: service + bridge contract
python3 tools/test_friends.py           # 37: relay client + worker parity
python3 tools/test_mod_bridge.py        # 110: reads Bridge.java, asserts launcher serves it
python3 tools/test_mod_compile.py       # mod source compiles vs the stub API subset
python3 tools/test_mod_matrix.py        # 68: brackets/jar routing
python3 tools/test_ui_smoke.py          # 40: tab builders build, invariants hold
python3 tools/test_invites.py           # 127: Minekube/tunnel flows
python3 tools/test_modpacks.py          # 51: pack installs
python3 tools/test_mod_store.py         # 21: global mod store
python3 tools/test_net.py               # 19: download retry/resume/cap + updater
python3 tools/test_production.py        # 13: watchdog + opt-in crash reporting
python3 tools/build_mod_jars.py         # rebuild mod jars -> cache + assets/jars
```

Harnesses are hermetic (sandboxed HOME via CUBEON_GAME_DIR etc.). After ANY
mod source change run `build_mod_jars.py` — stale deployed jars in
`~/.cubeon_launcher/cache/` are the classic "I fixed it but nothing changed"
trap (the mod now warns about it in chat, but don't rely on that).

## Where deeper docs live (agents/docs/)

`guide-cubeon-modules.md` (module deep-dive), `guide-worker-backend.md`
(relay protocol), `guide-data-flow.md` + `diagrams-flows.md` (flows),
`production-readiness-gaps.md` (known gaps), `phase2b-*.md` (P2P history).

## Open items (2026-09-04 production review)

1. Relay deployment pipeline — repo Worker code can be ahead of the live
   deployment; no version handshake exists yet.
2. One live two-launcher in-game end-to-end run has never happened.

## Production pass (2026-09-05, Cline) — what landed

- `cubeon/net.py`: downloads get retry+backoff (3 attempts, honors
  Retry-After), HTTP-Range RESUME via `.part` + atomic replace, hash
  verification covering prefix+tail, and a global 4-download gate. Wired into
  modpacks._stream_download, mods.download_mod, server.install_server
  (Paper). Contract: error message must contain "integrity" (test asserts).
- `cubeon/logging_setup.py`: rotating file log at
  `~/.cubeon_launcher/cubeon.log` (5MB x3), sys/threading excepthooks, and
  `diagnostics_text()` for bug reports. setup_logging() is idempotent; call
  it EARLY in main().
- `cubeon/updater.py`: APP_VERSION constant (bump per release!), release-feed
  check via `CUBEON_UPDATE_FEED` override, `check_in_background()`; main.py
  shows a non-blocking snackbar with a "Get it" button on a newer release.
- CI: `.github/workflows/build.yml` now has a `test` job running every
  tools/test_*.py (Java 21 for test_mod_compile) before builds.

## Production pass 2 (2026-09-05, Cline) — items 6-14

- **Relay abuse guards** (#6): `limiterAllow` (pure, exported) + Hub.allow —
  120 frames/min per user (silent drop), 10 friend-requests/min per user
  (T_ERROR `rate_limited`, human message). In-memory per DO, deliberately
  not SQLite. `wrangler deploy` needed to go live!
- **Crash reporting** (#7): `cubeon/crashreport.py` — OFF unless
  cfg["crash_reports"] AND an endpoint exists (env CUBEON_CRASH_ENDPOINT or
  cfg["crash_endpoint"]); payload = diagnostics_text() tail only. Hooked into
  logging_setup excepthooks. Settings tab has a "Privacy" checkbox.
  **No receiving endpoint exists yet** — build a tiny Worker route, then set
  the env var.
- **Game watchdog** (#9): `cubeon/watchdog.py` — running_game.json record at
  launch, cleared on confirmed exit; `stale_session()` at startup detects an
  orphaned game and the launcher offers a "Close it" snackbar. Never raises.
- **macOS CI build** (#11): inline PyInstaller on macos-latest. DISCOVERY:
  `packaging/` scripts (build_appimage.sh, build_windows.py) DO NOT EXIST in
  the repo — the Windows/Linux build jobs reference them and will fail.
  Either restore those scripts or convert those jobs to inline PyInstaller
  (copy the macOS job; `--add-data "assets:assets"` is mandatory).
- **Onboarding** (#10): first-run dialog (no "onboarded" cfg key) asking for
  the in-game name; reuses on_profile_username_change for validation/skin
  sync/avatars, then sets cfg["onboarded"].
- **Skipped**: #8 code signing (needs a paid cert - user only), #12
  minimize-to-tray (Flet window-API risk) and background toasts (needs
  hooking every download site - medium), #13 i18n/accessibility (high effort).
- New tests: tools/test_production.py (13). Worker: node worker/test-worker.mjs.

## Follow-up 14: private repo + packaging scripts

- **Repo**: github.com/Shadow-457/Cubeon (PRIVATE), created + pushed via gh
  CLI. .gitignore excludes archive/, cline/, mod/build, dist, __pycache__.
- **Updater + private repo**: check_for_updates accepts a token (arg,
  CUBEON_UPDATE_TOKEN env, or cfg["update_token"]) sent as Bearer. Private
  releases need it; WARNING: the token ships inside any built launcher, so
  it must be a fine-grained READ-ONLY token and only for personal builds.
- **packaging/ now exists** (was missing - CI jobs referenced it):
  build_appimage.sh (PyInstaller onedir -> AppDir -> appimagetool, tar.gz
  fallback), build_windows.py (onedir + zip), build_macos.sh (onedir + tar.gz).
  All bundle assets via --add-data (MANDATORY - jars live there).
  CI jobs now work as written; macOS job calls build_macos.sh.
- **Verified live on this machine**: full Linux build ran end-to-end,
  dist/Cubeon-x86_64.AppImage (103 MB) produced, and
  AppDir/usr/bin/_internal/assets/jars/ contains both mod jars + connect jar.
- Release flow: bump cubeon/updater.py APP_VERSION -> tag vN.N.N -> push ->
  gh release create with the built artifacts.