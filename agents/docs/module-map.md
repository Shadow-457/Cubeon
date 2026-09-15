# Cubeon module map — read this before reading any source

Last updated: 2026-09-14 (bug sweep: atomic JSON writes, mods hardening, worker DM refusals). If a fact here contradicts
the code, the
code wins — but fix this file too. Durable facts belong HERE, not in diary notes.

## Atomic JSON writes + hardening (2026-09-14) — INVARIANT
- Every persisted JSON state file (config.json, skins.json, skin_net.json,
  auth_key.json, ...) MUST be written via `cubeon/atomicio.write_json()`
  (unique temp file in the target dir + fsync + `os.replace()`), or an
  equivalent tmp+replace. A direct `open(path, "w")` is a crash-corruption
  bug: most load_* readers fall back to defaults on JSONDecodeError, silently
  wiping user settings. `save_config`, `_save_skins_meta`,
  `_save_publish_state` were the last three direct writers, fixed together.
- `cubeon/mods.py` `_safe_jar_filename()` sanitizes every user-picked jar
  basename before it becomes a file in a profile dir (also `add_mod_file`).
- `toggle_mod`/`delete_mod` guard on `os.path.lexists` - a stale UI mod list
  must produce a message/no-op, never FileNotFoundError.
- Worker DM refusals are never silent: `onDm` sends `T.ERROR
  {code: dm_bad_recipient|dm_empty|dm_not_friends}` (toasted by
  `friends_service._on_error`). Asserted in `tools/test_friends.py`.


## Chat tab identity card (2026-09-13)
- `ui/chat_tab.py` `_apply_identity` previously crashed on a typo'd control
  name (`you_id_text` vs `your_id_text`); the poller swallows exceptions, so a
  bug in an identity/roster paint path silently leaves the UI stale — never
  assume a blank control means no data, grep for a name error first.
- The Cubeon ID must always be rendered through `_friends.canonical_uid()` to
  keep the zero-padded 12-digit form.
- Flet 0.86 clipboard: `page.set_clipboard` is gone. Use
  `page.run_task(ft.Clipboard().set, value)` (async service). FakePage
  harnesses lack `run_task`, so clipboard handlers must try/except.
- **The launcher can only show a Cubeon ID if the DEPLOYED friends worker
  sends one.** The repo's `worker/cubeon-friends.js` assigns/back-fills the
  12-digit uid and sends it in `hello_ok`/`/claim` — but the live worker at
  `cubeon-friends.hamza-457-shahbaz.workers.dev` must be redeployed
  (`cd worker && npx wrangler deploy -c wrangler-friends.toml`) before any
  client build can display it. Old hello_ok/claim replies have NO `uid`.
- The chat identity card shows ONLY the 12-digit ID (no `Player_xxxxxxxx`
  name — that auto-minted handle is the relay key, internal only; it survives
  as the card's hover tooltip).
- **Two-launcher testing:** `tools/launch_sandbox.py <name>` boots an isolated
  second launcher (fresh HOME → fresh friends account; `--list`/`--wipe`).
  MUST set `PYTHONUSERBASE=<real home>/.local` or flet can't import. Bridge
  uses a random port + token, so instances coexist. Default shares
  `~/.cubeon_minecraft` via CUBEON_GAME_DIR (no re-download); `--isolated-game`
  gives the sandbox its own game dir.
- Chat identity card (ui/chat_tab.py): profile avatar (PFP via
  `cubeon.profile.get_profile_picture_path`) + cfg["username"] as the display
  name (relay name fallback) + the 12-digit ID as a small secondary line with
  a copy button. The pfp path is in `_apply_identity`'s sig so swapping the
  picture repaints without a roster change. Friends' avatars/names stay
  color-initial + relay-name — the protocol doesn't transmit PFPs/usernames;
  changing that means worker + client changes.

 If a fact here contradicts the code, the
code wins — but fix this file too. Durable facts belong HERE, not in diary notes.

## AI app driver + mega smoke (2026-09-13) — read before writing a new test
- `tools/app_driver.py` is the reusable "hands": it boots the REAL UI headless
  (HOME sandboxed, `_fuzz_common.install_safe_stubs`) into a `Driver`, whose
  `tabs()`/`open_tab()`/`click()`/`type_fields()`/`fire_all()` an agent can
  call, and whose `report()` is JSON. Prefer extending it over re-deriving a
  FakePage harness. Its `DriverPage` adds the Flet 0.86 `show_dialog`/
  `pop_dialog` stack that `_fuzz_common.FakePage` still lacks, so
  `cubeon.dialogs`-opened dialogs are reachable. `shots` delegates to the
  windowed `ux_capture.py` (Flet has no headless renderer).
- **`fire_all()` fires the whole handler surface, not just clicks**: on_change/
  on_submit/on_click, plus on_hover (data "true"/"false"), on_focus/on_blur,
  and on_result (FakeEvent.files == [] = the picker-cancelled path). `report()`
  carries `handler_coverage` = fired/seen + the names of anything missed, so a
  shallow pass can't masquerade as coverage. As of 2026-09-13 `explore` =
  325/325 and `fuzz` = 4371/4371 (100%). A real pointer/OS event (physical
  hover, a real file chosen) has no headless analogue - the synthetic events
  above cover the *handlers*.
- **Headless `.update()` noise is filtered, not warned**: `Container.update()`/
  focus handlers raise `RuntimeError: Control must be added to the page first`
  when unmounted; the driver's `_classify` drops that (and "Event loop is
  closed") as an artifact, so hover logic is exercised without false alarms.
- `tools/test_mega_smoke.py` = the one-command gate, cheapest layer first:
  syntax (`compile` all 112 .py) → imports (62 modules) → type/contract
  (launcher_core facade covers every `core.*` in main.py+ui/, forbidden Flet
  APIs, None-in-controls, THEME/signatures, type hints) → AST control flow
  (unreachable, dup defs, bare except) → headless runtime (every tab opens,
  every handler fires, no errors, no None children, second build idempotent).
  `--static` skips runtime, `--json` for machines, `--suites` chains the
  repo's own harnesses.
- `ux_capture.py`'s TAB_ORDER now matches the live nav keys
  (play/mods/modpacks/chat/profile/server_console/server_plugins/
  server_settings/stats); Settings is not in `discover_nav` because its
  handler has no `k=key` default arg — capture it by other means if needed.
- **`_sandbox_home.isolate()` leaks into child processes** via `os.environ`
  (`HOME`/`USERPROFILE`). flet lives in the real user site-packages and is
  only resolved at interpreter STARTUP, so a child launched with a rewritten
  HOME gets `ModuleNotFoundError: No module named 'flet'`. Any harness that
  spawns a GUI suite after isolating HOME must pass the original HOME through
  (`test_mega_smoke.section_suites` does). Each suite re-isolates itself.
- **`install_safe_stubs()` patches `subprocess.Popen` process-wide** (to a
  `SimpleNamespace`), so any `subprocess.run` after it raises `TypeError`.
  Run subprocess-based suites BEFORE the runtime/driver layer, or restore
  `subprocess.Popen` afterwards.
- **Seeded browse hits matter (2026-09-13):** returning `[]` from the browse
  readers means no result row is ever built, so `build_browse_row()`'s
  `on_download` worker (the resourcepack/shader install) and the mod detail
  dialog are UNREACHABLE — the suite passes while that code is broken. The
  stubs return one realistic hit and shape-correct `get_mod_details` /
  `get_mod_versions` / `install_mod_with_dependencies` / `mod_doctor`; keep
  those shapes in sync with `cubeon/mods.py`.
- **The generic `except` in install workers hides defect signatures.** An
  `UnboundLocalError` there is caught and rendered as "Failed" — it never
  reaches `fire()`/`threading.excepthook`, so the defect detectors stay
  green. The only reliable guard is to stub the install leaves to SUCCEED and
  assert no row shows "Failed" (`test_fuzz` scenario D). Do this for any new
  install path.
- **Backend metadata reads go through `net.get_json`, not bare
  `requests.get`** (`mods.py`, `content.py`, `server.py`, `modpacks.py`,
  `minekube.py`). Any harness faking `requests.get` must ALSO route
  `net._do_get` + stub `updater.check_in_background`, `icons.prefetch`, and
  `core.get_mod_icons`, or a headless run silently hits the real network
  (the pooled `requests.Session` is invisible to a `requests.get` monkeypatch).

## Flet 0.86 hard rules (learned 2026-09-06, each cost real debugging time)
- **Dialog API: `Page.show_dialog(dlg)` / `Page.pop_dialog()` — there is NO
  `Page.open()`/`Page.close()` on 0.86.** Dialogs (AlertDialog AND SnackBar —
  both are DialogControls) live in the managed stack `page._dialogs.controls`,
  NOT in `page.overlay`. `show_dialog` raises on an already-open dialog;
  `pop_dialog` closes the top one; a buried dialog closes via
  `dlg.open = False; dlg.update()`. ALWAYS go through `cubeon/dialogs.py`
  (`open_dialog`/`close_dialog`/`show_snack`) — the app previously fell back
  to a pre-0.28 `page.dialog` branch that 0.86 silently ignores, which is why
  popups never closed and toasts never showed (fixed 2026-09-08; smoke §9
  pins it, FakePage mirrors the 0.86 API).
- `thread_safe_ui.final_update(page)` is NOT a generic "repaint now" — it
  only flushes a pending THROTTLED update. To paint one control from a timer
  thread, use `thread_safe_ui.refresh(ctrl)` (the account-panel scrim bug).
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
- The flet client prints one `Atk-CRITICAL **: atk_socket_embed: assertion
  'plug_id != NULL'` line to inherited stderr on every launch (KDE/X11;
  GTK a11y socket with no atk-bridge). Harmless. `NO_AT_BRIDGE=1` does
  NOT stop it, and the env can't be fixed — main.py instead wraps
  `flet_desktop.open_flet_view_async` to pipe the client's stderr through
  a drop-filter (async `readline`; a SYNC read on the asyncio pipe eats
  ALL client stderr — verified). Non-matching lines still reach the log.
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
- **`control.page` RAISES `RuntimeError` on unmounted controls** (Flet
  0.86, `base_control.py` — it walks `.parent` and raises "Control must
  be added to the page first"). `hasattr(ctrl, "page")` returns True (the
  property exists), so it catches nothing. Any generic repaint helper
  must wrap the `.page` read in try/except. Flet sends a control's full
  state when it's mounted, so pre-mount mutations are NOT lost by
  skipping the repaint. Verified 2026-09-07 (Mods-tab click crash).
- The launched game gets its own session + real log file
  (`~/.cubeon_launcher/game.log`, `start_new_session=True`, stdin
  /dev/null) so it SURVIVES launcher exit/terminal close. Don't
  "simplify" this back to inherited pipes.
- Repaint profiler: `CUBEON_PERF=1` times every `page.update()` by call
  site (table at exit, in `cubeon/thread_safe_ui.py`). Use it before
  any UI-performance guesswork.
- **Repaint rule:** one small region changed → `thread_safe_ui.refresh(ctrl)`
  (control-level diff, ~0.35ms avg); structure changed (add/remove/swap)
  → `page.update()` (full-tree, 5-8ms avg). All per-keystroke /
  per-file / per-log-line paths already use refresh(); keep new code on
  that pattern. `refresh()` is thread-safe like page.update().
- Startup: `minecraft_launcher_lib` is lazy (`cubeon/lazy.py`); Mods/
  Modpacks/Servers tabs build on FIRST VISIT, not at startup.
- Test-harness gotcha: `tools/test_ui_smoke.py` imports `main` as a module,
  so anything `main()` references must exist at module scope (bit us with
  `_session_end`).
- **A `None` inside any Flet `controls` list (e.g. `ft.Text(...) if cond
  else None` in `ft.Column([...])`) does NOT raise Python-side.** It
  serializes as a null child; the Dart client fails to build that subtree
  and Flutter's release-mode ErrorWidget paints a giant gray box in its
  place — with zero output in any log. This was the "white thing on
  uploaded capes" bug (2026-09-07). Never put None in controls lists;
  test_ui_smoke §5b walks the built Cape pane asserting None-free lists.



## Version art + new-UI preview (2026-09-08)
- `cubeon/version_art.py`: version id → official banner image (minecraft.wiki).
  Lookup: `<id>_banner.jpg` URL first (covers 1.15.2+, snapshots), then the
  page's lead image via the MediaWiki `pageimages` API (old versions 1.8-1.14
  have no banner file). Disk cache `CACHE_DIR/version_art/<id>.{jpg,png}` is
  FOREVER (banners never change); memory dict short-circuits both hits and
  misses-per-session. UI threads must use `fetch_async()` — `get_version_art()`
  downloads synchronously on miss.
- `ui_new/preview.py` is the REDESIGN PREVIEW, launched by `python main.py
  --new-ui` (intercepted in `__main__` before any flet-desktop stderr
  wrapping). It shares NOTHING with the real UI: top-bar nav, cinematic
  banner hero, version card grid. It reuses real palettes through
  `cubeon.color_templates`. Do not build features in the preview — port them
  into main.py only after user approval.
- Launcher's visible name is "Cubeon" (unchanged). The IN-GAME MOD is named
  "Cubeon Client" (fabric.mod.json `name`, screen title + corner-icon tooltip
  in CubeonClientScreen.java) — jar id / package `cubeon-client` /
  `com.cubeon.client`.
- Sidebar brand = cube mark + "Cubeon" + a Feather-style player pill:
  small avatar + in-game username (`sidebar_brand_avatar` /
  `sidebar_brand_username`, refreshed in `refresh_avatars()`), click →
  Profile tab. test_ui_smoke asserts the window title string.
- **Play page composition (2026-09-11 refinement).** PAGE HEADING ("Play" +
  "Launch Minecraft your way.", FONT_DISPLAY only for the heading) → the
  single hero card, top-aligned and compact (padding 20, internal `spacing=0`
  with explicit spacers; NOT stretched to fill the viewport). The card is
  three labelled bands, separated by explicit spacers only - the two
  `pixel_divider()` calls that used to sit under the Mod loader and above the
  footer were removed (2026-09-11): INSTANCE HEADER
  (grass-block emblem, `hero_title`, loader chip + version meta, rename/
  delete) → CONFIGURATION (a row of the two related fields, Game version
  dropdown + Account field, then the Mod loader segmented control) →
  ACTION FOOTER (`update_version_btn` on the left, PLAY right at 280px).
  Below the card sits a full-width OG Minecraft key-art banner
  (`assets/titleimg.jpg`, 2000x1000): wrapped in a `Row` so an expanded
  `Container` stretches it edge-to-edge (the card itself stays compact), fixed
  height 220 + `BoxFit.COVER` + `ClipBehavior.ANTI_ALIAS` so it crops cleanly at
  any window width.
  PLAY text uses the clean UI font (not Minecraftia) — pixel face is reserved
  for branding/page heading/instance title. Delete is TEXT_DIM at rest and
  DANGER only on hover; rename TEXT_DIM→TEXT on hover.
- **Top nav**: icon-only buttons (`build_top_nav_button`) are 21px icons with
  a green underline AND an `ACCENT_TINT` wash for the active tab; tooltips
  carry every destination (test_ui_smoke's `all_text` includes
  `tooltip` attrs, so nav names are asserted from them). Do not change
  tooltip words without updating `nav_labels` in test_ui_smoke.
  Account/Settings icons are 22px.
- **Palette is true black + green, via the `green` template (2026-09-11).**
  The app default is `DEFAULT_COLOR_TEMPLATE = "green"` in `cubeon/__init__.py`
  (was `"carbon"`). `templates/color_green.py` and the fallback `cubeon/theme.py`
  now both carry the user's exact scheme: `BG=#050505` (true black),
  `SURFACE=#0B0D0A`, `SURFACE_HI=#131711`, `SURFACE_MAX=#1A2015`,
  `BORDER=#242B1E`, `TEXT=#DDF6D5` (pale green-white), `ACCENT=#46BA34`,
  `ACCENT_HI=#5FD24B`, `ACCENT_DIM=#2BAF00`, `ACCENT_DEEP=#052400`,
  `ON_ACCENT=#04120A`, `CARD_FILL_HERO=#0C0F0B`. Surfaces are black with a
  faint green cast - never grey. Green stays reserved for
  ACTIVE/SELECTED/ACTION/SUCCESS (`ACCENT_TINT` 0.12 wash; `ACCENT_TINT_HI`
  0.20). The loader segmented-control thumb uses the solid `ACCENT_DEEP`
  (`#052400`) now, not the `ACCENT_TINT_HI` wash of the previous pass.
  `ACCENT_DEEP` is a module-level token (NOT in `THEME`) exported by
  `cubeon/theme.py`; templates that don't declare it get it derived in
  `cubeon/color_templates._derive()` (darkened `ACCENT_DIM`). The old olive
  literals (`#33431E`, `#0E110A`, ...) must not come back.
- **Copy rule (binding, 2026-09-11):** all user-facing text is plain and
  gamer-friendly — no jargon (`jar`, `process`, `PID`, `hash`, `config.json`,
  `UUID`, `endpoint`, `.zip`, `OS`, `plugin stack`, "in this build"). Settings/
  Stats captions, mods/modpacks/shader notices, server tooltips and the legacy
  note were all rewritten. Keep new strings short and non-technical.


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

## Skins identity guard rails (2026-09-07)
- `ownsUuid` returns `"quota" | "claimed" | true | false`: check quota
  first; `"claimed"` = first-contact TOFU (race-fixed: re-reads owner
  after put). Heartbeat uses it to exempt the INITIAL name claim from the
  move cooldown.
- Pointer moves are per-identity rate-limited: `lastmove:<uuid>` stamp,
  3600s cooldown (`429 name_move_cooldown`). Rename costs 2 KV writes
  (pointer + stamp); first claim 2 (owner + pointer, no stamp); steady
  state 0.
- Heartbeat responses carry `name_contested: bool` (computed from the
  PRE-move holder + their lastmove stamp — post-write holder would always
  be self). Client persists it in skin_net.json → `skins.name_contested()`
  → status-bar note on rename (main.py, 3s-delayed daemon thread).
- Unlocks POST on KV quota → real `429 kv_write_budget_exhausted` (was
  200-with-stale-set; milestones.py still tolerates both shapes).

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
a Cloudflare Worker relay (`worker/`) over WebSocket. The launcher ALSO has its
own top-nav **Chat tab** (`ui/chat_tab.py`, 2026-09-11) that drives the same
process-scoped `FriendsService` directly, so the social layer works without
launching the game. DMs and sync frames are E2EE (`cubeon/e2ee.py`). Local
server hosting is Paper-only, exposed to friends via Minekube Connect tunnels.

## Repo layout (top level)

| Path | What it is |
|---|---|
| `main.py` | UI glue: builds tabs, owns FriendsService, avatars, dialogs. ~3000 lines. |
| `launcher_core.py` | Re-export shim over the `cubeon` package (legacy import surface). |
| `cubeon/` | All launcher logic (see table below). |
| `ui/` | Flet tab builders: `server_tab.py` (biggest), `mods_tab.py`, `modpacks_tab.py`, `skin_tab.py`, `stats_tab.py`, `chat_tab.py`. Pure builders — they receive `cfg`/`state` by reference and helpers (`section_label`, `pixel_divider`, theme) from main.py. |
| `mod/` | The in-game Fabric mod. `src/main/java/com/cubeon/client/`: `CubeonClientScreen.java` (the Friends UI: FRIENDS/REQUESTS/ACCOUNT tabs only - chat was removed 2026-09-12 and lives in the launcher's Chat tab; Bridge chat plumbing is dormant, nothing calls setChatFriend), `Bridge.java` (localhost HTTP client + snapshot parsing), `CubeonClient.java` (entrypoint, chat notices), `Json.java`, `Nametag.java`, `WorldPlayers.java`; per-era overlays add `CornerIcon.java`. `brackets.json` = **single source of truth** for MC version brackets (read by build.gradle AND cubeonfriends.py). |
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
| `friends.py` | Relay client (WebSocket, secret as first frame), name rules, identity.json, claim/rename. `auto_name()`/`ensure_identity()` = the secret-derived automatic handle (no claim prompt). `T_*` constants = protocol truth. |
| `e2ee.py` | X25519 DM encryption; keys published to the relay under the claimed name. |
| `p2p.py` | P2P worlds: STUN + relay fallback, mod/asset sync, teardown. |
| `worldgate.py` | The OPTIONAL password on a P2P LAN world (in-memory only, dies with the session). Host arms it from the mod's password prompt; the joiner proves it via HMAC(PBKDF2(pw,salt), nonce) over the E2EE signal channel - the p2p_offer (LAN port + relay token) is withheld until a proof lands, so the gate is real, not decorative. |
| `server.py` | Paper server hosting: install (Fill v3 API), start/stop, properties, orphan detection. |
| `minekube.py` | Public address tunnels: finds/installs Connect plugin, endpoint config. |
| `modpacks.py` / `mods.py` / `global_mod_cache.py` | Modrinth/CF packs; per-profile mods LINK into one global store (`~/.cubeon_minecraft/global_mods`) — never copy jars between profiles. |
| `cubeonfriends.py` | Which Friends jar goes into which profile (brackets), injected at launch. `mod_stamp()` = jar freshness fingerprint. |
| `perf_mods.py` | FPS boost: fetches Sodium + Lithium (`PERF_MOD_SLUGS`) into a Fabric/Quilt profile at launch when `client_mod_enabled` AND `perf_mods_enabled`. `_present()` dedupes by slug/name/id/filename; best-effort, never raises. |
| `launch.py` | `launch_game()` — injects CSL + friends jar + Sodium/Lithium, syncs mods, launches MC. `CLIENT_JVM_FLAGS` + matched `-Xms/-Xmx`. Requires mc_version/loader, no silent defaults. |
| `capes.py` | Custom capes: any image accepted, auto-fitted onto the cape layout, synced into CSL's LocalSkin. Static images only — the animated-cape system was removed 2026-09-07. No Worker/KV involvement at all. |
| `config.py` | cfg schema, username validation, auth key (public_uuid/secret_token). |
| `gate.py` | Server join password (PBKDF2, escalating lockouts). |

## Facts that bite if you don't know them

- **Two jar namespaces**: MC ≤1.21 (obfuscated, loom, intermediary names) vs
  26.x (unobfuscated, plain javac). Two jars, chosen via `mod/brackets.json`.
  The mod compiles against a stub API subset (`tools/test_mod_compile.py`) —
  only API that exists identically in both eras. If javac fails on 26.x, the
  API moved; javap the real jar in `~/.minecraft/versions/26.1.2/26.1.2.jar`.
- **Animated capes were REMOVED (2026-09-07).** Custom capes are static
  images only now: no `AnimatedCape.java`, no `.frames.json`, no
  `GET /cape/frames`, no `animated` flag in capes.json. If it ever comes
  back, the historical contract (CSL `(LOCAL_LEGACY)` texture-hash trap,
  1.21.x reflection traps) is documented in
  agents/2026-09-07_agent_animated-cape-static-fix.md and
  agents/2026-09-07_agent_flexible-animated-capes.md — read those before
  re-deriving anything, they cost real debugging time to learn.
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
python3 tools/test_mega_smoke.py        # deep gate: syntax + imports + contracts + control flow + headless runtime
python3 tools/app_driver.py explore     # AI driver: use the app headless, JSON error/coverage report (`fuzz`, `script`, `shots`)
python3 tools/test_friends_service.py   # 213: service + bridge contract + identity + unique rename + chat tab
python3 tools/test_friends.py           # 37: relay client + worker parity
python3 tools/test_mod_bridge.py        # 119: reads Bridge.java, asserts launcher serves it
python3 tools/test_mod_compile.py       # mod source compiles vs the stub API subset
python3 tools/test_mod_matrix.py        # 68: brackets/jar routing
python3 tools/test_capes.py             # 14: flexible capes + CSL sync
python3 tools/test_ui_smoke.py          # 97: tab builders build, invariants hold
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
  **2026-09-13 additions:** a lazy process-wide pooled `requests.Session`
  (connection/TLS reuse; `requests.get` makes a new Session per call),
  `net.get_json()` (retry-wrapped metadata/API GET — a blip must not read as
  "no matching file"), and `net._do_get` is now the SINGLE transport seam:
  production = pooled session, tests monkeypatch `net._do_get`. Harnesses that
  fake `requests.get` (test_modpacks) must route `net._do_get` back through it
  or they'll hit the real network.
  **Also now wired:** `content.download_content` (resource packs + shaders —
  was the last bare single-attempt `requests.get`, hence the "network error"
  on install), `server.download_plugin`, `minekube` Connect plugin. Modpack
  mod-file downloads run in a `ThreadPoolExecutor(max_workers=4)` so the
  gate is actually used (the old serial loop made it decorative);
  `global_mod_cache` index writes + store-name choice are lock-guarded for
  that concurrency.
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

## Follow-up 21: cosmetics = LOCAL library folders (2026-09-14, replaces the real-player gallery)

The Mojang "browse REAL players" system was REMOVED by user request (2026-09-14).
Browse is now two local drop-folders; the only network skin path left is the
skins-worker publish (cubeon/skins.py, worker/cubeon-skins.js).

- **cubeon/gallery.py (reworked)**: the catalog is the contents of
  `~/.cubeon_launcher/skin_library/` and `~/.cubeon_launcher/cape_library/`
  (image extensions png/jpg/jpeg/webp/gif/bmp). One item per file; `id` = file
  name; fuzzy search over stems (`_norm`/`_match_score`); previews rendered
  from the actual pixels once and cached under `gallery/previews/` (memoized
  per folder signature in `_CATALOG_MEMO`). `install_gallery_skin/cape`
  run the file through the exact upload pipeline (`_skins.add_custom_skin` /
  `_capes.add_custom_cape`) and wear it. `gallery_id_for_file/forget_file/
  ensure_gallery` keep their shapes. The old featured/Mojang names
  (`featured_count`, `featured_cached_count`, `prefetch_featured`,
  `suggest_player`, `load_player`) remain exported as honest no-op stubs
  because launcher_core re-exports them and harnesses probe them.
- **cubeon/remotes.py**: dead code - nothing imports it anymore. Kept in the
  tree (test_skins_net.py does NOT cover it; it tests skins.py). Do NOT call
  it from new code.
- **ui/skin_tab.py**: hat/Cosmetics pane REMOVED entirely (user: "remove the
  hat BROWSE shit too") - the section is Skin | Cape panes only, and
  `build_skin_section` no longer takes `start_prefetch`. Each Browse pane has
  a search box + an "open folder" button (`_open_folder` -> xdg-open/open/
  os.startfile). `core.ensure_gallery()` runs at every section build so the
  drop-folders exist on first run. `cubeon/cosmetics.py` hat drawing helpers
  still exist (launcher_core re-exports) but have no UI.
- **build_skin_section signature**: `(..., file_picker, cape_file_picker)` -
  NO `start_prefetch`. test_ui_smoke's six call sites were updated.
- **Tests**: test_gallery.py rewritten for the local-library pipeline (25
  checks); test_ui_smoke hat checks replaced with "hat browse is gone" and
  the search/pane-flip checks re-pointed at the local library ("your skin
  library folder" caption).
- GOTCHA from the 2026-09-13 session: a mid-refactor skin_tab.py shipped to
  the user's RUNNING launcher and crashed with `NameError: _img_b64` at
  import-time call `refresh_skins_list()` (line ~429) - in the current tree
  `_img_b64` is defined INSIDE build_skin_section at line ~312, before the
  first statement-level `refresh_skins_list()` call, which is correct. If you
  move those defs, check statement-call order, not just name resolution.

Still-true invariants from the pre-local era:

- **Installed lists show previews as a wrapping card grid (2026-09-11)**:
  `_owned_card(...)` builds each card (real preview via `_skin_card_b64` /
  `_cape_card_b64`, name, optional sublabel, hover-revealed Use/Delete, and an
  accent border + ACTIVE pill for the active item). `skins_list_col` /
  `capes_list_col` are `ft.Row(wrap=True)` grids; the built-in Cubeon cape is
  the first card (no delete, `on_delete=None`). `_grid_scroll(grid, height=290)`
  wraps a grid in a fixed-height scrolling Column so a long list never
  stretches the tab. NO pager anywhere in the cosmetics tab.

- **Cosmetics theming matches the Mods tab (2026-09-11)**: the tab used to be
  the only one wrapped in its own bordered SURFACE card in `main.py`, and every
  inner stage/tile was another solid bordered box - i.e. "box in a box".
  `main.py`'s `profile_tab` is now a plain `ft.Column([skin_section_container])`
  (padded by the tab switcher), exactly like Mods/Stats/Settings. `ui/skin_tab.py`
  paints its panels with the Mods-tab translucent tokens: stages / tiles / cards
  use `CARD_FILL` + `CARD_BORDER` (no more solid `SURFACE`/`SURFACE_HI` + hard
  `BORDER`/2px `ACCENT_DIM`), cards/tiles lift to `ROW_HOVER` on hover and
  selected hats/cards wash with `ACCENT_TINT`; the search fields use
  `CARD_FILL`/`CARD_BORDER` + `focused_border_color=ACCENT_DIM` + faint hints.
  Reuse these tokens when adding new cosmetics surfaces - do NOT reintroduce a
  solid nested panel.

- **Browse/Installed visibility BUG (fixed 2026-09-10)**: `_view_tabs`'
  `switch_view` used to update `view_state` + the tab highlight but NOT the
  two columns' `.visible`, so clicking "Installed" moved the underline and
  left Browse on screen - users reported "Installed shows nothing". The
  columns now register in `view_panes` and `_apply_view(pane_id)` flips
  `.visible`. Keep that registry when touching the pane builders.

- **Browse grid is built ONCE, search flips `.visible` (2026-09-11)**:
  `refresh_skin_gallery`/`refresh_cape_gallery` used to `controls.clear()` +
  re-render + re-base64 every preview on each keystroke (janky search, image
  flicker), and the empty-result state offered a "Look up ... on Mojang"
  button (removed). They now build all tiles once from `gallery.all_gallery_items`
  (cached + uncached recommended, memoized per cache signature), stash
  `{skin,cape}_gid` on each tile's `.data`, and toggle `.visible` via
  `gallery.matches_query`. The module-level `_img_b64` memoizes base64 by
  path+mtime. Install/delete paths reset the `{skin,cape}_tiles_sig` dict to
  force the one rebuild that reflects the new INSTALLED pill. `skin_empty_hint`/
  `cape_empty_hint` carry the "no match / still loading" line so install status
  text in `*_browse_status` is not clobbered. Both browse grids also sit in
  `_grid_scroll(...)` so a long result set scrolls inside a fixed-height region
  instead of stretching the tab.

- **HONEST LIMIT - there is NO hat API.** Vanilla Minecraft has no hat slot;
  hats are pixel art the launcher paints into the skin's hat layer, and they
  are only visible to you (like a custom skin), not other players.
- **List functions must stay network-free**: refresh_*_gallery in skin_tab
  runs at build time; remotes.cached_player_ids + _snapshot_from_profile must
  never hit the network (they short-circuit on fresh cache). Keep it that way.
- **os.path.isfile(None) crashes**: _snapshot_from_profile must guard paths
  with `path and os.path.isfile(path)` - a player with no cape has cape_path
  None.

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

## Mod in-game UI (2026-09-08; menu removed 2026-09-11) — durable facts
- **The full Cubeon in-game menu is GONE** (Profile/Skins/Capes/Cosmetics/
  Statistics/Chat/Online). It was `CubeonMenuScreen.java` plus the per-era
  overlay `CharacterView.java` + `mixin/CubeonMenuRenderMixin`. All five files
  were deleted, the mixin deregistered, and both `PauseScreenMixin` and
  `TitleScreenMixin` now add ONLY the Friends corner icon
  (`CubeonClientScreen.menuButton`). Do not reintroduce a second menu button
  under the Friends icon. The overlays still exist for `CornerIcon` (the
  Friends glyph), which is unrelated to the menu.
- **authlib split**: GameProfile is a record on 26 (`.name()`) but a class on
  1.20.1 (`.getName()`), and PlayerInfo exposes no name — WorldPlayers resolves
  it reflectively. Do not "simplify" that back to a direct call.
- New bridge endpoint GET `/players` (local_api.py `_providers["players"]` ←
  `FriendsService.players_payload`). Fail-soft contract: no provider or a raise
  must answer an empty `players` list, never a 404 the mod crashes on; the mod
  treats null/empty as "nothing known". Skin/cape are display strings only —
  the launcher never ships pixels over the bridge; a friend's skin lives on
  their launcher.
- test_mod_compile's stub includes LivingEntity, ClientPacketListener,
  PlayerInfo, GameProfile and Minecraft.getConnection() for WorldPlayers. The
  now-removed character preview's GuiGraphics + InventoryScreen stubs were
  deleted with the menu.

## Mid-session GPU-crash auto-recovery (2026-09-08; discriminator fixed 2026-09-11)
- The Mesa 26.1/libgallium SIGSEGV also happens **mid-session** (during a GTK
  paint), not just pre-paint. A pre-paint death is retried in-process (safe:
  the engine never initialized); a mid-session death must NOT re-run ft.run
  (once-per-process → silent hang). `_session_loop` classifies the end via
  `_classify_session_end(ui_painted, client_exit)` → arm `use_software_gl`,
  bump `CUBEON_GPU_RESTARTS` (env, survives execv, reset on clean close) and
  **re-exec the whole launcher** (the tray-reopen trick), max 2 restarts, then
  park like a user close.
- **The old discriminator was wrong and made every close reopen the window
  (fixed 2026-09-11, live bug).** `_kill_flet_client()` returning "a live flet
  child" can NEVER be true: flet 0.86's `ft.run()` reaps the desktop client
  itself (`await fvp.wait()` inside `flet/app.py`) and only returns after the
  child is gone. So the "live child = user close / no child = crash" test always
  said "crash" and re-exec'd on every normal X-close. The reliable signal is the
  client's **exit status**, captured by `_capture_flet_client_exit()`, which
  wraps `flet_desktop.open_flet_view_async` so the process object's `.wait()`
  records `returncode` while flet awaits it: `0` (or any `>=0`) = normal close,
  negative = signal death (`-11` SIGSEGV, `-6` SIGABRT), `None` = unobservable →
  treat as clean close (never a surprise relaunch). Verified live under Xvfb:
  window close → 0 → exits with no relaunch; `kill -SEGV` on the client → -11 →
  restarts with software GL. Regression covered by `test_ui_smoke.py` §4b.
- `_kill_flet_client()` is kept only as a best-effort ghost-window cleanup; its
  return value no longer classifies the session. Zombie flet children are still
  excluded from the scan (state `fields[0]` of /proc stat after
  `rpartition(b")")`).
- The parked `_reopen.wait(timeout=30)` can be interrupted by flet's
  exit_gracefully handler after the asyncio loop closed → spurious
  "Event loop is closed" RuntimeError (logged CRITICAL cubeon.fatal twice
  live). Now caught: teardown noise, treated as quit.
- **The software-GL fallback must NEVER reach the game** (2026-09-08, live
  bug: Minecraft ran at 4 FPS). The launcher's `LIBGL_ALWAYS_SOFTWARE=1` +
  `GALLIUM_DRIVER=llvmpipe` used to be inherited by the java child (verified
  in /proc/<pid>/environ). Two guards: (1) `cubeon/launch.py` strips
  `LIBGL_ALWAYS_SOFTWARE`/`GALLIUM_DRIVER`/`LIBGL_DRM_DEVICE` from the game
  env; (2) `_reveal_window` deletes the `use_software_gl` marker as soon as
  the UI paints (the fallback only needs to survive until first paint, not
  until clean close — waiting let it linger armed across kills/crashes).
- **Not every /dev/input/js* is a gamepad** (2026-09-08, live bug: "🎮 Baseus
  K03 Keyboard connected"). Some keyboards expose a js HID interface (that
  one: 3 buttons, 1 axis) for media keys. `cubeon/controller.py` now probes
  each device's INIT-event shape (`_probe_shape`) and gates it through
  `_looks_like_gamepad(name, buttons, axes)`: keyboard/mouse-named devices
  are refused outright; named pads need ≥4 buttons; unnamed devices need
  ≥8 buttons + ≥4 axes. Rejected paths go to `_rejected` so the 2s scan
  doesn't re-probe them. Verified against the real js0 on this box.
- **No Material ink ripples** (user preference, 2026-09-08): every clickable
  `ft.Container` uses `ink=False`. ui_smoke §10 asserts no `ink=True` /
  `ink=not ` anywhere in main.py, ui/*.py, cubeon/theme.py, cubeon/inspector.py
  (archive/ and ui_new/preview.py are exempt: dead dist copies and the
  --new-ui mock).
- **Account panel toggles must diff, not page.update()** (2026-09-08): the
  open/close handlers repaint ONLY the two overlays via
  `thread_safe_ui.refresh(account_scrim)` + `refresh(account_panel)`. A
  `page.update()` there re-synced every mounted control — user saw the whole
  app "reload" on each panel toggle. General rule for animation-y overlay
  choreography: always per-control refreshes. ui_smoke §10 asserts no raw
  `page.update()` line inside the two handlers.
- **Tab switching is a hard cut with a scoped diff** (2026-09-09, "snappier"
  pass): `switch_tab` ends with `thread_safe_ui.refresh(tab_switcher)` +
  `refresh(subnav_bar)` + per-nav-button refreshes — NOT `page.update()` (a
  whole-tree diff hitched the frame exactly at the switch). The
  AnimatedSwitcher's fade is `duration=0, reverse_duration=0` (kept as a
  switcher only so `.content` assignment code is unchanged).
  `refresh_installed_packs` (ui/modpacks_tab.py) likewise diffs
  `installed_view`/`installed_count` instead of the page. Measured in the
  FakePage harness: steady-state switch = 0 page.update calls, ~3ms wall;
  first visit to a lazy tab builds it (~87ms once). Remaining `page.update()`
  calls live in one-shot action handlers (install buttons, filter toggles) —
  fine. The one at switch_tab's tail was the "sloppy rendering" complaint.
- **Download progress is throttled at the SOURCE** (2026-09-09 efficiency
  pass): `net.stream_to_file` fires progress_cb per 64 KiB chunk — hundreds
  of UI repaints/sec on fast links. It now emits at most every 33ms OR every
  1% of the file, with one guaranteed final callback carrying the exact byte
  count (resume/hash callers rely on that). Measured: a 100 MB instant
  download = 101 callbacks (was 1600). All progress bars route through this
  (version installs, mods, modpacks).
- **Worldgate (2026-09-12): the LAN-world password gates the OFFER, not the
  invite.** Host states: hosting_wait_port -> gate_wait (mod prompt) ->
  ringing_out -> (accept) verifying -> connected. Joiner: connecting ->
  password_needed -> connecting. Signal kinds: gate_challenge/gate_proof/
  gate_fail (carries the FRESH nonce + salt for the next round)/gate_ok.
  MAX_ATTEMPTS=3 then the room closes; a 60s watchdog closes an
  unanswered round; the password (hash included) never touches disk.
  The offer precedes any fallback decision, so the gate covers both.
- **Mod-diff report calls out version clashes (2026-09-12):** the sync
  report's missing-mod list splits a mod the joiner HAS at a different
  hash into its own "You have a DIFFERENT version of" block, by matching
  filename stems (_mod_stem: tokens before the first digit-led one).
  Purely presentational - never gates can_download. The Fix-button
  label in the mod is now "Fix" (was "Download mods").
- **LAN worlds NEVER hand the joiner to Minekube (2026-09-12, behavior
  change).** connect-spigot is a tunnel for the host's PAPER SERVER (verified
  in the shipped jar - no target/local-port config key), so a joiner pointed
  at <endpoint>.play.minekube.net would land in the server's world, not the
  LAN world. `_switch_to_minekube` now only ANNOUNCES the address into the
  host's Minecraft chat (copyable, labelled as the server); the punch-failed
  session stays on Cubeon's relay, which carries the world correctly. The
  joiner's `p2p_use_minekube` handler is kept for OLD-launcher hosts.
- **Address into Minecraft chat:** `FriendsService.notify_active()` (class
  seam; `_active` set in start(), cleared in stop()) lets any module push a
  line into the mod's event ring - the Server tab's public-address watcher
  uses it, one line per resolved address. Host also gets world-live lines at
  worldgate_set; the password is never echoed into chat (streamers).
- **P2P outbound loop is event-driven** (2026-09-09): `_tcp_outbound_loop`
  polled `time.sleep(0.01)` forever (~100 wakeups/sec per session). Now waits
  on `_outbound_wake` (Condition on `_state_lock`), nudged by ACK-freed
  window space in `_handle_frame` and by `close()`. A 0.2s wait timeout
  covers the window-full backpressure case. `test_p2p_*` suite green.
- **Content surfaces are Browse/Installed toggle views** (2026-09-09): mods
  (incl. resource packs + shaders, which share the tab), modpacks, and
  server plugins each show ONE pane at a time — `view_segment_row` underline
  tabs (`text_tab`) above `browse_pane` / `installed_pane`, both mounted,
  only `.visible` flips on `on_view_change` (no rebuild, no re-fetch). The
  Installed tab label carries a live count ("Installed (7)"), refreshed by
  the same refresh_*_list() calls that rebuild the list. Pattern is identical
  in all three files; server_tab's panes are built AFTER the market controls
  exist (plugin_search_field etc.) — `refresh_plugins_list` may be defined
  before them but only CALLS `_build_plugins_view_segment` at runtime. The
  old stacked layout (browse results with installed list a full scroll
  below) is gone. ui_smoke §11 asserts the pattern in all three files.
- **Browse rows share ONE visual pattern everywhere** (2026-09-09): the mods
  tab's row style is the canonical one — `attach_hover(container,
  "transparent", ROW_HOVER)` (transparent at rest, faint lift on hover, no
  permanent slab), 15px W_700 title / 12px TEXT_DIM description / 11px
  TEXT_FAINT FONT_MONO metadata, and the action button a restrained
  ACCENT_TINT wash with ACCENT text (solid ACCENT is reserved for the one
  hero action per screen). `build_pack_row` (ui/modpacks_tab.py) and
  `_plugin_result_row` (ui/server_tab.py) follow it exactly. Tab builders
  only receive the fixed THEME kwarg set — extra tokens (ROW_HOVER,
  ACCENT_TINT, TEXT_FAINT, attach_hover) are imported directly from
  cubeon/theme.py; do NOT add keys to THEME (TypeError at every call site).
- **Stats tab** (2026-09-09, ui/stats_tab.py): top-nav "stats" key, lazy
  tab like the others. Read-only counters over existing state
  (milestones.json, versions scan, folder globs, skins/capes meta) in
  three sections (Playtime / Library / Cosmetics). RULE: never call
  get_profile_dir() / get_plugins_dir() / content_dir() from a read-only
  scan — they CREATE directories as a side effect; glob PROFILES_DIR /
  SERVERS_DIR / RESOURCEPACKS_DIR / SHADERPACKS_DIR directly
  (ui_smoke §12 enforces via a comment-stripping matcher). Flet 0.86 has
  no `ft.margin.only/.symmetric` — use `ft.Margin(l, t, r, b)`.
- **Chat tab + automatic identity** (2026-09-11, ui/chat_tab.py): top-nav
  "chat" key, inserted at index 3 ONLY when `features.friends_enabled()`, so a
  public no-Friends build has no dead entry. It talks to the process-scoped
  `FriendsService` directly (roster/chat/requests), NOT the mod bridge, and:
  - `build_chat_tab(page, cfg, state, service, *, section_label, **THEME) ->
    (root, refresh)`; `service is None` returns a static notice (never crashes).
  - polls on its own daemon thread via `cubeon/thread_safe_ui.py` (service
    reads block on the websocket — never touch Flet from them); `refresh()` is
    main.py's on-open reconcile hook.
  - auto name: `friends.auto_name()` = `"Player_" + sha256(stable_secret())[:8]`
    (deterministic per auth_key.json, 15 chars, allowed name set, never
    reserved). `friends.ensure_identity()` mints it only when no identity has a
    name, so it can never silently rotate a name a friend already knows; the
    server binds it claim-on-connect at WS hello. No claim prompt exists.
  - the tab shows the server-assigned 12-digit **ID**, not a name: a name is
    only a cosmetic label and there is NO rename field (the old
    `rename_unique`/"Your name" flow was removed 2026-09-12; test_ui_smoke
    pins `name_field`/`rename_unique` OUT of chat_tab.py). Add a friend by ID
    via `friends.canonical_uid(raw)` -> `FriendsService.add_friend(uid)`.
  - main.py startup connects only if an identity ALREADY existed; a brand-new
    one connects when the Chat tab first opens (keeps headless UI builds from
    opening real websockets with throwaway identities).
  - **layout reworked 2026-09-11, professional pass 2026-09-13**: left rail =
    "Chat" header + connection dot, identity block (avatar + name, and the ID
    in a bordered badge chip), add-friend field, requests section (only when
    non-empty), then Friends. Roster rows are chat-style: avatar ringed green
    when online, name, last-message preview ("You: ..." for outbound) or
    presence when there is no history, and a right-aligned clock + accent
    unread badge. Right pane = conversation header (avatar + name + presence)
    with a centered empty state until a friend is picked, day separators and
    grouped spacing in the transcript, content-hugging bubbles ("mine" =
    `ACCENT_TINT` wash, theirs = `SURFACE_HI`), an inline send-error line, a
    rounded composer (`shift_enter=True`: Enter sends, Shift+Enter newline),
    a square accent send button, and a warning banner while the socket is
    down. Avatars are per-name `theme.AVATAR_COLORS`. Bubble width is measured
    from the longest line, capped at half the window. Message/name text uses
    the body font, not mono.
  - **roster rail data contract (2026-09-13)**:
    `FriendsService.roster_payload` decorates each friend with
    `last_text`/`last_ts`/`last_dir` and `unread` (inbound msgs after that
    peer's read marker). `FriendsService.mark_read(friend)` advances the
    marker monotonically; the Chat tab calls it on select and on every poll
    while a conversation is open, which clears the badge. The tab's
    `_mark_read` uses `getattr(service, "mark_read", None)` so stub services
    (test_fuzz/app_driver) keep working. GOTCHA: a multiline Flet TextField
    with default `shift_enter=False` makes Enter insert a newline and never
    fire `on_submit` - the composer must set `shift_enter=True`.
    `test_friends_service.test_chat_read_rail` and the ui_smoke chat checks
    pin the rail contract, the Enter-to-send rule and the day separators.
- **Playtime is a durable on-disk play session (fixed 2026-09-11)**: the game
  outlives the launcher (launch.py `start_new_session=True`) and a GPU-crash
  re-exec (main.py `os.execv`, sets `CUBEON_TRAY_REOPEN`) replaces the process,
  killing the in-process on_exit watcher. So playtime is persisted, not just
  credited in memory:
  - `launch_game` calls `milestones.begin_play_session(pid)` right after
    `watchdog.register` → writes `~/.cubeon_launcher/play_session.json`
    (`{started, pid}`).
  - `main.py` on_exit / the startup reconciler call
    `core.milestones_end_play_session()`, which credits `min(now, mtime of
    game.log) - started` (the log mtime bounds idle time when the launcher was
    off for hours) and clears the record. Idempotent under `_session_lock`, so
    on_exit and a reconcile poll can't both credit.
  - `main()` calls `core.milestones_reconcile_play_session()` on EVERY start
    (including re-execs - do NOT gate it on `CUBEON_TRAY_REOPEN`, which is set
    on exactly the crash path that needs it): a dead pid is credited and
    cleared; a live one is left on disk and watched by a 30s poll until exit.
  - GOTCHA: `core.add_play_seconds` does not exist; launcher_core re-exports
    `milestones.add_play_seconds` as `milestones_add_play_seconds`, and session
    helpers as `milestones_begin/end/reconcile_play_session`. A bare rename
    fails silently under `except Exception: pass` (that was the original
    "Time in game stays 0" bug). ui_smoke pins the session wiring + a real
    3661s accumulation; test_milestones §7 pins the durable-session semantics.
- **Browse/installed PANE anatomy is the mods tab's** (2026-09-09): bare
  Columns with NO enclosing SURFACE slab, a quiet search field (CARD_BORDER,
  ACCENT_DIM focus, CARD_FILL fill, 46px, TEXT_FAINT hint, no separate
  solid-green Search button — Enter/typing carries it), a 12px TEXT_DIM mono
  caption line ("Recommended" / "Popular modpacks" / "Plugin picks") sharing
  a row with the status text, and transparent-until-hover rows everywhere
  (browse AND installed). Hero headers (big ACCENT icon + Minecraftia title)
  are gone from these panes — the one hero per screen rule.

## Top-bar layout + mod deps + legacy gate (2026-09-08, later)
- **The sidebar is gone.** Navigation is now a top icon bar (`_build_top_bar`):
  Play / Mods / Modpacks / Cosmetics / Servers centered (icon + green
  underline for active, marker attr `cubeon_top_icon` on those buttons),
  Account + Settings icon buttons on the right. The top-bar "Servers" icon is
  an entry point that maps to `server_console`; the Console/Plugins/Settings
  chips live in `subnav_bar` between the top bar and the content surface and
  are visible only while a server tab is active. The identity card moved out
  of the old Profile tab into an `account_dialog` opened by the Account icon
  (`_account_open["fn"]` holder is filled after the dialog is built).
- **The old "profile" tab is now Cosmetics** (skins/capes/hat only) - key is
  still `"profile"` internally, switch_tab/refresh_profile_tab unchanged.
- **Required-dependency auto-install**: `mods.required_dependencies()` reads
  Modrinth's latest-version `dependencies` (only `dependency_type ==
  "required"`), resolves each with the cached `get_mod_download()`;
  `mods.install_mod_with_dependencies()` downloads main mod + missing deps
  (skips by project_id/slug via `mods.installed_project_ids()`), returns
  `{installed, skipped, failed}` and never raises for a failed dep.
  `ui/mods_tab.py` on_download uses it and reports "Installed +N deps" /
  per-dep failures. Verified live: iris→sodium resolved, junk→[].
- **Batch install progress is in FILE UNITS (2026-09-15)**: `install_mod_with_
  dependencies()` amortises the whole batch as `(whole files finished + the
  current file's fraction, TOTAL FILE COUNT)` - a total that is FINAL before
  the first byte moves - so one click climbs 0→100 once instead of restarting
  per dependency (the reported "1-100% doesn't work" bug). Success finishes at
  exactly 100; a failed dep holds the floor short of 100. The UI label is
  `ui/mods_tab.batch_progress_text(value, total)` → "Downloading… 42%
  (file 2/3)" (plain percent when total <= 1). Single-file callers
  (resourcepack/shader via `content.download_content`) still report BYTES and
  pass their own `_bytes_label`; don't feed byte counts to
  `batch_progress_text`. Contract pinned by `tools/test_mod_install_progress.py`
  (39 checks, offline, fakes cubeon.mods).
- **Legacy gate**: versions below 1.20 (numeric only, `_is_legacy_version`)
  are hidden from BOTH the installed and online lists until the user enables
  it. The **Legacy toggle lives in Settings → "Game versions"** (a real
  on/off toggle via `_set_legacy_ui` + `state["legacy_ok"]`; the choice
  PERSISTS as `cfg["legacy_versions"]`, seeded at startup). The "Show
  snapshots" checkbox also lives in that card (always visible,
  re-fetches on toggle). The Play tab and the version picker dialog no longer
  carry either control - test_ui_smoke asserts their absence on the Play tab.
- **Cubeon Client mod off-switch**: Settings → "Game versions" →
  "Install the Cubeon Client in-game mod" checkbox, `cfg["client_mod_enabled"]`
  (default True). cubeon/launch.py treats off like a public build: no jar
  install AND `cubeonfriends.remove_installed()` sweeps stale jars (a
  leftover would still load). Smaller blast radius than
  features.friends_enabled(), which is a BUILD-time switch removing the whole
  backend.
- **FPS boost (Sodium + Lithium)**: NO Settings toggle (the user explicitly
  asked for it removed 2026-09-11 - don't add it back). It rides the existing
  "Cubeon extras in-game" toggle: when `client_mod_enabled` is on (and the
  config-only `perf_mods_enabled`, default True, is on) and the loader is
  Fabric/Quilt, `cubeon/launch.py` calls
  `perf_mods.ensure_installed(mc_version, loader)` before `sync_mods_to_game`,
  which fetches Sodium + Lithium from Modrinth (`PERF_MOD_SLUGS`) into the
  profile exactly like a user-installed mod. `perf_mods._present()` matches
  slug/display_name/project_id/filename so a manual jar is never duplicated
  (duplicate Sodium = crash). Best-effort: no build/offline/load error is
  reported in the return dict, never raised. The Cubeon Client itself is a
  social mod and contributes ~0 FPS; Sodium is the actual frame-rate engine and
  its own in-game settings are intentionally left untouched.
- **Client JVM flags**: `cubeon/launch.py` `CLIENT_JVM_FLAGS` (G1GC,
  MaxGCPauseMillis=50, ParallelRefProc, DisableExplicitGC, G1NewSize/Reserve)
  are appended to every launch's `jvmArguments`, and `-Xms` now equals `-Xmx`
  (no mid-game heap-growth stutter). Deliberately lighter than the server's
  Aikar set (`HIGH_PING_JVM_FLAGS`); flags chosen to exist on Java 8–25.
- **Mod detail menu + auto-repair (2026-09-12)**: clicking any mod row
  (browse OR installed, except protected/system files) opens a full menu via
  `ui/mods_tab.py:open_mod_detail()`. It fetches `mods.get_mod_details()`
  (one cached `GET /project/{id}`: gallery/featured art, body markdown,
  downloads, categories, loaders, game_versions, licence, links) and
  `mods.get_mod_versions()` (one cached `GET /project/{id}/version`: every
  release, each marked `compatible` for the current profile, with its primary
  file url/filename/hashes and dependencies). Both use the 6h `local_cache`
  so reopening is instant and works offline via the stale tier. Detail
  install buttons call `install_mod_with_dependencies`, then the doctor.
  The dialog uses `cubeon/dialogs.py` `open_dialog`/`close_dialog`
  (Flet 0.86 stack), `cubeon/icons.py` for art, and background threads +
  `thread_safe_ui.refresh` for painting.
  **Layout (2026-09-12, friendliness pass)**: 720px wide; scrollable height
  adapts to `page.height` (capped 640). Order = gallery strip (all screenshots,
  sideways scroll) → compact meta pills (downloads / loader / Minecraft) →
  **"Install latest" quick action** (or "You're up to date") → collapsed
  description (`Read more` reveals the full `ft.Markdown`) → version list.
  Version list shows at most **8 compatible** builds, then a "Show all N
  versions" toggle that also reveals incompatible builds tagged
  "other version". A shared `_install_button()` drives both the quick action
  and every row; on success all cached repaints in `quick_state["repaints"]`
  fire so the banner and rows stay in sync.
- **mod_doctor() auto-repair**: `cubeon/mods.py:mod_doctor(mc, loader,
  auto_fix=True, check_online=True)` returns `{checked, problems, fixed,
  unfixed}` and NEVER raises. Four checks: (1) duplicate copies - same
  Modrinth id => older copy DELETED via `supersede_older_copies`; same
  filename stem only => older copy DISABLED (reversible). Run once per
  duplicate group, not per loser, and `fixed` is computed PER LOSER (the
  file is really gone) rather than group-level, so a partial failure is not
  reported as success. (2) missing required dependencies
  (`_required_deps_cached`, 6h) => downloaded, tracked in `installed_ids` so
  two mods needing the same dep fetch it once. (3) no release for the current
  loader+mc_version => the jar is DISABLED (`toggle_mod`), never deleted.
  `get_mod_download` skips a newest release whose `files` list is empty so a
  usable older build isn't mistaken for "no release" (which would wrongly
  disable the mod). (4) **version conflicts** - see next bullet.
  Wired four places: automatically after every mod install (`ui/mods_tab.py`
  browse quick-download AND the detail dialog AND "Install from file"), by
  the Installed pane's **"Fix problems"** button, at launch in
  `cubeon/launch.py` with `check_online=False` (skips the per-mod API passes;
  duplicate + conflict repair still runs), and **proactively** by
  `main.py:_proactive_mod_repair()` when an (mc_version, loader) profile is
  selected - full `check_online=True`, once per profile per session, in a
  background thread, silent unless it changed something. Regression:
  `tools/test_mod_detail.py` (66 checks).

- **Version-conflict detection (`breaks`)**: Fabric records "this mod will not
  work with mod X version Y" in the jar's own `fabric.mod.json` `breaks`, and
  the **Modrinth API does NOT expose it** (`dependencies` only lists required/
  optional/embedded/incompatible PROJECTS, never version ranges) - so the jar
  is the only source of truth. `read_mod_metadata(jar)` unzips
  `fabric.mod.json`/`quilt.mod.json` (local, offline; returns `depends`,
  `breaks`, id, version, name). `version_satisfies(version, predicate)`
  implements Fabric/Maven ranges (`<=1.10.7`, `0.8.x`, `[1.0,2.0)`, `*`,
  `||`). `mod_doctor` builds an id->installed-version map, and for every jar
  whose `breaks` matches an installed mod it reports `kind="conflict"`.
  Resolution (`_resolve_mod_conflict`): (1) update the TARGET if a compatible
  build escapes the predicate; else (2) replace the DECLARER with the newest
  compatible build (stable before beta, compatibility filtered BEFORE any
  cap) whose own `breaks` no longer matches - e.g. Sodium 0.8.14 breaks Iris
  <=1.10.7, and the newest Iris for 1.21.11 *is* 1.10.7, so Sodium is
  downgraded to 0.8.12 (breaks Iris <=1.10.6). Remote candidate jars are read
  via `_read_remote_mod_metadata` (temp download, discarded). If neither side
  has a compatible replacement, `mod_doctor` falls back to DISABLING the
  target (`toggle_mod`, reversible) so the game still launches; a
  `disabled_targets` set stops a second declarer of the same target from
  toggling it back on. Never deletes blindly; `download_mod` supersedes the
  replaced copy.
- **Version manifest fetch**: `cubeon/versions.py` `MANIFEST_URLS` /
  `_download_manifest()` / `_manifest()`. Both Mojang hostnames are tried
  (`piston-meta` then `launchermeta`) via `net.get_with_retry` (timeout 15s,
  2 attempts); the raw manifest is cached in `local_cache` under
  `mojang_manifest` / `v2` for 1h and served STALE when both mirrors fail.
  `get_available_versions()` and `get_latest_release()` read that cache, NOT
  `mll.utils.get_version_list()` (single bare request, no timeout/retry).
  Regression: `tools/test_versions_manifest.py`.
- **"Update game version"** button (Play tab, next to Legacy): loads the
  online list if needed, picks the newest stable release
  (`_newest_release_key`, pure numeric ids, list-first then
  `get_latest_release()` fallback - the function was referenced but never
  defined until 2026-09-11, so the button used to always raise), selects it -
  the existing prefetch path installs it in the background. Hardened
  2026-09-12 to never dead-end: if the newest release isn't in the current
  (offline/filtered) list it is added to the dropdown + `pick_source` before
  selecting; if it's already selected but not installed it (re)starts the
  install and says "Getting <v>..."; if selected AND installed it says
  "Already on the latest release (<v>)". The old "Latest is <v> - pick it
  from the list" branch (which fired when it was already picked) is gone.
  The visible picker label is repainted in the handler's `finally`.
  Regression: `tools/test_ui_smoke.py` section 6b drives the real handler.
- test_ui_smoke now asserts nav via lowercased all_text (which includes
  tooltips - all_text already walked them); nav labels are
  play/mods/modpacks/cosmetics/servers/account/settings + the two buttons.
- **Version picker dialog**: the Play tab's config band is one compact row -
  GAME VERSION (button) | ACCOUNT (username field), both 48px. The `ft.Dropdown` is still
  the source of truth but is NOT mounted; the button (`version_dropdown_button`,
  label mirrored by `_sync_version_button()` from `on_version_selected`) opens
  `version_pick_dialog`: the search field `version_filter_field`
  (on_change = on_pick_search), scrollable `pick_list` rows, and a
  "Browse all versions →" link (refresh_version_list(online=True) + rebuild).
  (The "Show snapshots" checkbox lives in Settings now, not the dialog.)
  **Invariant (2026-09-11 fix):** the dialog filters its OWN snapshot,
  `pick_source["value"]` (installed-only offline, full online list when
  fetched), and `_rebuild_pick_list()` reads only that. It must NEVER rewrite
  `version_dropdown.options`/`.value` while filtering - the old `_filter_versions`
  did, so every keystroke could reassign the selection to the first match and
  call `on_version_selected()` (silently starting a prefetch/download), and
  closing the dialog left the dropdown stuck on a narrowed list. Selection
  commits only via `_pick_version` (a row click). `refresh_version_list` keeps
  both `all_online_options` (update-version path) and `pick_source` current.
  An empty `pick_source`/zero-match renders an explanatory row, never a blank
  box. test_ui_smoke guards this with a source assertion.
- **Version strings are shown verbatim; "1.21.11" is not a typo for "1.21.1".**
  Verified 2026-09-11: the installed folder/JSON id on this machine is
  literally `1.21.11` (alongside `1.21.8`, `26.1.2`), and `extract_mc_version`
  is non-destructive for it. Do not "fix" the displayed version without first
  checking `~/.minecraft/versions/<id>/<id>.json`'s `id` field.
- The `_reveal_window` GPU-marker NameError (from the mid-session recovery
  work) is fixed: `_CUBEON_HOME` is imported inside the coroutine; the fuzz
  suite (12 checks incl. run_task coroutine scan) catches this class.



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
- **Windows EXE can be cross-built on this Linux box via Wine** (2026-09-07):
  `~/winpython/py311/python.exe` is a Windows embeddable Python 3.11.9 with
  pip + all requirements + PyInstaller installed, and flet-windows.zip
  pre-fetched into its flet_desktop/app/. Build from repo root:
  `wine Z:\\home\\fuckarch\\winpython\\py311\\python.exe -m PyInstaller
  --noconfirm --onedir --windowed --name Cubeon --add-data=...;...
  --collect-all flet --collect-all flet_desktop --collect-submodules
  templates main.py` (Z: drive paths; `--add-data=` EQUALS syntax only —
  space syntax is mangled by wine). Output identical to CI's
  packaging/build_windows.py layout. See
  agents/2026-09-07_agent_wine-windows-build.md for the full recipe. Re-run 2026-09-14 for the launcher-lib fix: add `--collect-all minecraft_launcher_lib` to the wine command (bundled + verified).
- Release flow: bump cubeon/updater.py APP_VERSION -> tag vN.N.N -> push ->
  gh release create with the built artifacts.

## Invariant: ft.Image never loads absolute filesystem paths (Flet 0.86)

- `ft.Image(src=...)` only accepts asset-relative paths (resolved against
  assets_dir) or http(s) URLs. A `~/.cubeon_launcher/...` absolute path
  silently fails and renders a PERMANENT BLANK BOX (this bit the chat
  tab's self-avatar; skin_tab hit it earlier). Three working patterns:
  1. base64 str (skin_tab previews, chat_tab `_set_you_avatar`)
  2. raw bytes via `ft.CircleAvatar(foreground_image_src=...)` (main.py)
  3. bundled asset-relative path (skin_tab DEFAULT_CAPE_PREVIEW_SRC)
- Chat tab gotcha: visible-toggled header chrome (avatar, remove button,
  header hairline) must be flipped together in `_select` AND
  `_clear_conversation` and listed in BOTH refresh tuples — an always-on
  divider rendered as a stray floating line in the empty right pane.

## Worker/relay invariants (2026-09-14 sweep)

- **`decodeURIComponent(url.pathname)` throws URIError on malformed escapes**
  (e.g. `/name/%zz`) and an unhandled throw in a Worker fetch surfaces as a
  Cloudflare "error 1101" page. All four workers route through `safePathname()`
  which falls back to the raw (always-valid) pathname. Keep that pattern for
  any new worker.
- **Durable Object race audit rule:** message handlers run one at a time, so
  code with NO `await` between a read and its write is race-free by
  construction (`onAdd` mutual-add auto-accept). Only `await`-crossing
  sections are candidates — e.g. `onHello`'s claim-on-connect INSERT, guarded
  by a catch + re-read on the PRIMARY KEY violation.
- **Pre-auth WS flooding:** the per-user `frames:` limiter only exists AFTER
  hello authenticates. Unauthenticated sockets are gated per-IP (30/10min),
  with the IP captured into the socket attachment at upgrade time
  (`CF-Connecting-IP`) because headers are unavailable in
  `webSocketMessage`. `serializeAttachment` REPLACES the attachment, so any
  later write must re-include `ip`.
- **Chat history SQL:** newest-N-then-reorder needs a subquery, and `rowid`
  must be PROJECTED out of the subquery (`rowid AS rid`) or the outer
  `ORDER BY` fails with "no such column". Verified against real SQLite.
- **KV write budget:** every worker must keep the compare-then-write / body-
  cap discipline; the waitlist worker's `request.json()` was the one uncapped
  body parse (fixed 2026-09-14). invites' `RATE_LIMITER` binding is now
  actually consulted (`.catch(() => null)` → degrade to no limit, not 500).
- Deploy note: relay fixes require `cd worker && npx wrangler deploy -c
  wrangler-friends.toml` (plus -skins/-waitlist as touched) to go live.

- `web/index.html` landing page is a single self-contained file (no build, inline CSS/JS). `.btn` must stay `display:inline-block` — it is applied to `<a>` tags too, and inline padding overlaps sibling text. Fonts are Google-hosted Fredoka + local `web/assets/fonts/Minecraftia-Regular.ttf` (@font-face; Minecraftia ONLY for h1-h3/.brand/.btn/.q-a, line-height ~1.12 — illegible <16px, keep Fredoka for body); images lazy-swap from `/tmp`-independent `web/assets/` paths.

- `ui/skin_tab.py` (Profile > Skin/Cape panes) has NO browse/gallery area anymore (removed 2026-09-14): each pane is preview + installed card grid + upload CTA. `cubeon/gallery.py` survives only as core bookkeeping (`forget_file` in delete flows) + its tests; do not re-add library browsing without asking.
