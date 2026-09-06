# Cubeon module map — read this before reading any source

Last updated: 2026-09-07 (opencode Glm 5.3; tray-reexec + game-survival session finished by Claude Code). If a fact here contradicts the code, the code
wins — but fix this file too. Durable facts belong HERE, not in diary notes.

## Flet 0.86 hard rules (learned 2026-09-06, each cost real debugging time)
- `page.on_window_event` DOES NOT EXIST. Use `page.window.on_event`; `e.type`
  is a `WindowEventType` enum.
- The real X button delivers NO event to Python (X11/KDE verified). End-of-
  session cleanup must run after `ft.run` returns in `__main__`, not in an
  event handler. See `_session_end` dict (module-level!) in main.py.
- `window.prevent_close` makes the window UNCLOSABLE on Linux. Never set it.
- `Window.center()/to_front()/close()` are async coroutines; `run_task`
  requires a coroutine function (TypeError otherwise). `Window.update()` is
  sync.
- Async `window.center()` during first-frame reveal crashes flaky Mesa
  drivers (libgallium SIGSEGV). Center by computing left/top numerically
  BEFORE paint instead.
- The flet client may SIGSEGV in libgallium (Mesa 26.1/AMD Polaris; both hw
  and llvmpipe; ~50% flaky). main.py's `__main__` retry loop handles it:
  pre-paint death → `use_software_gl` marker + relaunch (2 retries).
- After the retry loop: `os._exit(0)` — GLib/pango native threads can hang
  interpreter shutdown.
- System tray = `cubeon/tray.py` (pystray, optional dep, icon-only while
  running; true background-on-close is IMPOSSIBLE on this Flet build).
  Tray callbacks arrive on pystray's thread → marshal via `page.run_task`.
- **`ft.run()` is ONCE-PER-PROCESS on 0.86.** A second `ft.run` spawns a
  new flet client whose engine NEVER initializes (silent hang, no crash,
  no window — verified live). Tray reopen therefore RE-EXECS the
  launcher (`os.execv` in `__main__`, `CUBEON_TRAY_REOPEN=1` env, PyInstaller
  `sys.frozen` handled). Never "fix" this back to an in-process rerun.
- On X-close the flet CLIENT process stays alive with a ghost
  "Working..." window (0.86 can't remove its implicit view).
  `_kill_flet_client()` in `__main__` kills children named `flet`
  (SIGTERM→2s→SIGKILL). Match on the NAME — Minecraft (`java`) is also
  our child and must never be touched.
- Tray reopen events are timestamped (`reopen_at`) and honored only if
  newer than `session_ended_at - 5.0`. NEVER blind-clear the reopen/quit
  events — that silently drops every fast Open click made during window
  teardown.
- The launched game gets its own session + real log file
  (`~/.cubeon_launcher/game.log`, `start_new_session=True`, stdin
  /dev/null) so it SURVIVES launcher exit/terminal close. Don't
  "simplify" this back to inherited pipes.
- Repaint profiler: `CUBEON_PERF=1` times every `page.update()` by call
  site (table at exit, in `cubeon/thread_safe_ui.py`). Use it before
  any UI-performance guesswork.
- Startup: `minecraft_launcher_lib` is lazy (`cubeon/lazy.py`); Mods/
  Modpacks/Servers tabs build on FIRST VISIT, not at startup.
- Test-harness gotcha: `tools/test_ui_smoke.py` imports `main` as a module,
  so anything `main()` references must exist at module scope (bit us with
  `_session_end`).



## Loader switcher (main.py, 2026-09-06)
- Loader support/installed lookups MUST use `core.extract_mc_version(version_id)`
  — the raw dropdown id can be a loader-install row (`fabric-loader-…`),
  which makes `find_installed_loader_version` miss and `is_loader_supported`
  lie. The launch path always knew this; the UI path didn't (fixed).
- Loader checks run in PARALLEL (one thread/loader); results cached in the
  session `loader_check_cache` keyed by raw version id. mll timings:
  fabric 0.6s / quilt ~1s / forge ~1.9s / neoforge ~1s, cached 1 week via
  `cubeon/local_cache` (`loader_support` namespace).
- Segment dim rule: only dim when (unsupported AND not installed). Never dim
  just because the version is installed — the pill stays clickable
  (on_loader_toggle_change allows any INSTALLED loader + vanilla).
- Headless diag recipe: extract FakePage from tools/test_ui_smoke.py,
  call `main.main(page)`, walk control tree (see
  agents/2026-09-06_agent_loader-ui-fixes.md).

## KV write discipline (all Workers, 2026-09-06)
- KV free tier: 1,000 writes/day **account-wide**, 100,000 reads/day. Never
  write without comparing first — use `putIfChanged(env, key, value, opts?)`
  (cubeon-skins.js); it returns `"quota"` on limit-exceeded → caller maps to
  429. TTL'd puts can't skip the write (the TTL refresh IS the write).
- Steady state (repeat heartbeat, identical re-upload) costs ZERO writes:
  verified against `wrangler dev --local`.
- Friends worker = Durable Objects (NOT KV-metered). Waitlist/invites dedupe
  by read before writing.
- **Never `git add -A` in worker/ after `wrangler dev`** — `.wrangler/` local
  state (sqlite/blobs) is gitignored now; check `git status` first.

## Window launch (main.py, 2026-09-06)
- `page.window.visible = False` at setup; after `mark_mounted`, a
  `page.run_task(_reveal_window)` awaits `wait_until_ready_to_show()` then
  flips visible → no default-size flash / blank frames.
- Geometry persists to `~/.cubeon_launcher/window_geometry.json`
  (`load/save_window_geometry` in cubeon/config.py); debounced 400 ms saves,
  clamp on restore, maximized saves keep the restore size.
- Flet 0.86: `Window.center()` / `wait_until_ready_to_show()` are async —
  must go through `page.run_task()`; `Window.visible` is a plain field.

## cubeon-skins Worker — face avatars (2026-09-05)
- `GET /faces/<username>.png` — player's head crop, same pointer→uuid→record
  chain as profiles; falls back to the full sheet for pre-face records.
- `POST /api/skin` body may include `face` (128×128 PNG) — content-addressed,
  stored as `record.face`. PNG guard is `isPngWithSize(bytes,w,h)`; **faces
  are 128×128**, sheets 64×64/64×32 — size-mismatched uploads are silently
  dropped, so new texture shapes must update the guard.
- Launcher: `_compose_face_png` (cubeon/skins.py) renders the head crop
  (base + hat layer) from the composed sheet; rides the skin upload, never
  raises (None → omitted).
- Discord presence small_image = `<CUBEON_API_BASE>/faces/<name>.png`
  (external URLs are allowed in RPC asset fields; third-party mirrors like
  minotar are useless for offline names — they only know Mojang accounts).

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
   deployment; no version handshake exists yet. Deploy manually with
   `cd worker && npx wrangler deploy -c wrangler-friends.toml`
   (last done 2026-09-05, version 6b7ac883, repo == live as of then).
2. One live two-launcher in-game end-to-end run has never happened.
   (Launcher↔relay↔launcher IS proven live as of 2026-09-05 — see
   agents/2026-09-05_opencode_live-two-player-relay-verified.md. The
   in-game mod ↔ local bridge hop is the remaining unproven leg.)

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

## Follow-up 20: frozen builds need flet_desktop bundled (2026-09-05)

- **Invariant: `--collect-all flet` is NOT enough for PyInstaller builds** —
  `flet_desktop` is a separate wheel; without `--collect-all flet_desktop`
  the frozen exe tries to pip-install at runtime and exits before a window
  ( symptom: exe closes instantly).
- The PyPI `flet-desktop` wheel ships `flet_desktop/app/` EMPTY — the window
  binary downloads from GitHub Releases on first run. All packaging scripts
  now fetch the client archive at BUILD time into the interpreter's
  `flet_desktop/app/` (that's `get_package_bin_dir()`, the first place
  `ensure_client_cached()` looks), so first run works offline.
- Artifact filename is platform-specific: use
  `flet_desktop.get_artifact_filename()`, not a hardcoded name.
- Windows builds also pass `--windowed` now.

## Follow-up 19: KV write-quota storm (2026-09-05)

- **Invariant: Cloudflare KV writes are ACCOUNT-WIDE (1k/day free tier)
  across ALL workers** — waitlist, skins, invites share one budget. A
  spammy client of any worker starves them all; budget resets 00:00 UTC.
- The username field's on_change fires PER KEYSTROKE → each used to run
  the full skin publish (heartbeat POST). Stale skin_net.json → retried
  forever. Fix: debounce rename publishes in main.py (1.2s/on-blur) AND a
  10-min failure cooldown in skins.py (`retry_not_before` in
  skin_net.json). Both layers are needed.
- Workers translate quota-thrown KV puts into clean 429s (never 500/
  1101): see handleJoin (waitlist), ownsUuid/handleHeartbeat/
  handleSkinUpload (skins). Clients treat non-200 as cool-off.
- Deploy commands: `cd worker && npx wrangler deploy -c wrangler-<name>.toml`
  — configs now exist for friends, waitlist, AND skins (skins previously
  had no repo config; its KV id is in wrangler-skins.toml).
- `web/index.html` waitlist site is complete and pointed at the live
  worker; it needs the public repo/release funnel before promotion.

## Follow-up 18: live UI inspector (2026-09-05)

- `cubeon/inspector.py`: dev-only DevTools for the launcher's own Flet UI.
  CUBEON_INSPECT=1 gates it (public builds never show it). Opens via
  sidebar bug button or F12. Tree browse + text search + live edit of
  Text.value/size/color/weight and tooltip — session-only, points at the
  source string to change for real. Note: this repo's Flet 0.86 uses
  `ft.padding.Padding.only` / `ft.border.Border.all` (NOT ft.padding.only /
  ft.border.all) — got me twice; update() on unmounted controls raises
  RuntimeError, so use the module's _safe_update().

## Follow-up 17: public-build launch crash (2026-09-05)

- Public builds (Friends disabled via features.py) set
  `friends_service = None` in main.py; the launch path called
  `friends_service.set_version(version_id)` unguarded → AttributeError
  AFTER the game process spawned (so MC still started, error spooked the
  user). Fixed with the same `is not None` guard the on_exit path had;
  regression check added to tools/test_ui_smoke.py.
- **Invariant: every friends_service reference outside the
  friends_enabled() block must tolerate None** — public builds are a
  first-class configuration, not an edge case. test_ui_smoke now asserts
  the guard textually.

## Follow-up 16: UI-freeze fix — throttled progress repaints (2026-09-05)

- **The "launcher froze during a download then recovered" bug**: mll fires
  progress once per FILE (~4000 files/version); every report called
  page.update() (full-tree repaint) → thousands of queued repaints
  saturated Flet's loop → window stopped taking input until the install
  ended. Fixed with `thread_safe_ui.throttled_update(page)` (coalesces to
  max 1 repaint / 0.1s) + `final_update(page)` to flush the last state.
  Flood sites: main.py do_install_and_launch callbacks, modpacks_tab
  status/progress/max, server_tab install progress_cb + _smooth_progress.
- Rule going forward: any callback that can fire per-file/per-chunk must
  use throttled_update, never bare page.update(). One-shot handlers can
  keep page.update().
- Verified: 5000 rapid calls → 1 repaint; 30 calls/1.5s → 15 (cap); all
  tools/test_*.py suites pass.

## Follow-up 15: CI green again (2026-09-05, opencode)

- `cryptography>=42.0.0` is now in requirements.txt — test_friends_service
  needs the E2EE path, so "optional at runtime" no longer means "optional in
  CI". Packaged launchers bundle it (no more degrade-to-unencrypted).
- javac lint asymmetry: CI resolves javac 25 (new `dangling-doc-comments`
  lint), local dev box has javac 21. Keep file headers in mod/**/*.java as
  `/*` not `/**` unless attached to a declaration.
- Artifacts from a green Actions run: Cubeon-Windows-x64-ZIP/Folder,
  Cubeon-Linux-x86_64-AppImage, Cubeon-macOS. Release flow unchanged.

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