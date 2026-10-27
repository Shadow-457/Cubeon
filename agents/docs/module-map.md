# Cubeon module map

Read this first, then only the references needed for the task. Public guides live in
[docs/](../../docs/README.md). Detailed earlier findings are preserved in [the implementation
reference](../history/implementation-notes-2026-10-24.md); dated or superseded entries there are not a
substitute for current code.

## Repository entry points

| Path | Responsibility |
| --- | --- |
| `main.py` | Startup, window/session lifecycle, navigation, Play orchestration |
| `launcher_core.py` | Compatibility facade over the launcher modules |
| `cubeon/` | Game/service logic and shared UI helpers |
| `ui/` | Flet tab builders and dialogs |
| `mod/` | Fabric companion client and version-specific overlays |
| `worker/` | Skins, invites, friends, downloads, and waitlist services |
| `packaging/` | Platform build scripts and installers |
| `tools/` | Standalone tests, development harnesses, and release tooling |

## Module ownership

| Area | Modules |
| --- | --- |
| Paths and configuration | `cubeon/paths.py`, `config.py`, `atomicio.py` |
| Game installation and launch | `versions.py`, `mod_loaders.py`, `launch.py`, `jre.py` |
| Instances | `instances.py`, `versions.py`, `content.py` |
| Mods and packs | `mods.py`, `modpacks.py`, `global_mod_cache.py`, `content.py` |
| Content compatibility | `packformat.py`, `doctor.py`, `content.py` |
| Download infrastructure | `net.py`, `global_mod_cache.py`, `local_cache.py` |
| Friends ownership | `friends_service.py`, `friends.py`, `e2ee.py` |
| Mod bridge | `local_api.py`, `cubeonfriends.py`, `mod/brackets.json` |
| World sharing | `p2p.py`, `invites.py`, `server.py`, `minekube.py`, `gate.py` |
| Cosmetics | `cosmetics.py`, `skins.py`, `capes.py`, `gallery.py`, `profile.py`, `appearance.py`, `appearance_scene.py` |
| Chat faces and artwork | `faces.py`, `icons.py`, `version_art.py` |
| Activity and screenshots | `milestones.py`, `activity.py`, `library_stats.py`, `screenshot_gallery.py` |
| UI infrastructure | `thread_safe_ui.py`, `dialogs.py`, `motion.py`, `theme.py`, `scrolling.py` |
| Window and crash handling | `winwindow.py`, `winchrome.py`, `incident.py`, `crash.py`, `logging_setup.py` |
| Input and presentation | `shortcuts.py`, `seasonal.py`, `color_templates.py`, `status_text.py` |
| Release and optional features | `updater.py`, `features.py`, `osnotify.py`, `voice.py` |

Except for explicit paths, names in this table are relative to `cubeon/`. Check source ownership before
assuming a helper is UI-free: the package also contains Flet support modules.

## UI ownership

| Surface | File |
| --- | --- |
| Play version panel, banner, instance rows | `ui/versions.py` |
| Mods, resource packs, shaders | `ui/mods_tab.py` |
| Modpacks | `ui/modpacks_tab.py` |
| Chat | `ui/chat_tab.py` |
| Cosmetics and account previews | `ui/skin_tab.py`, `ui/appearance_preview.py` |
| Servers | `ui/server_tab.py` |
| Activity statistics | `ui/stats_tab.py` |
| Settings | `ui/settings_tab.py` |
| Screenshot gallery | `ui/screenshot_gallery.py` |

Tabs are lazy-built and retained. Shared state and callbacks are wired in `main.py`; keep builders
consistent with the shared `THEME` contract.

## Contracts to preserve

### Flet and UI updates

- Dependencies pin Flet and `flet-desktop` to `>=0.86,<0.87`; a machine-wide installation of another
  version is not the release environment.
- Mutate shared control trees under `thread_safe_ui.TREE_LOCK`; request scoped repaints through
  `thread_safe_ui.refresh()`. Background threads must not invoke a whole-page update directly.
- Use `cubeon.dialogs` for dialog-stack compatibility. Removed APIs include `ft.border.all`,
  `ft.padding.only`, and `ft.margin.only`.
- Local absolute paths are not valid `ft.Image.src` values. Use cached base64, bundled asset paths, or a
  real URL; do not restore blank local images.
- Reuse installed/browse rows and image controls during metadata updates; chat presence must not remount
  PFPs, and sources change only with real artwork.
- Default hover/click effects are fill/rim fades, not scale or corner morphs; Mods and Modpacks do not
  replay cascade/shimmer animations on refresh.
- Rows with expanding spacers must not use `wrap=True`; Flutter's wrapped layout cannot host flex
  children. Check actual rendering, not only Python builds.
- Tab loads repaint their own region: `ui/mods_tab.py` and `ui/modpacks_tab.py` browse loading,
  cached-page render and content-type switches use `thread_safe_ui.refresh(...)`, not `page.update()`.
  A whole-tree diff in the same moment a tab is built/fetched was the "clicking Mods stalls the app"
  hitch. `tools/test_tab_repaint_scope.py` counts the full updates and fails on one.
- Instance selection is a scoped repaint too: `update_hero()` refreshes `hero_title`,
  `hero_version_text`, `hero_loader_chip_text` and `version_issue_text` itself. Do not add a
  `page.update()` to the row-click path to make a new hero label appear.

### Navigation shell

- The nav is a **compact left icon rail**: `_build_sidebar()` builds fixed-size tiles (`NAV_BTN_W/H/GAP`,
  icon over an uppercase label); `nav_blob` slides **vertically** (`_move_nav_blob` uses `Offset(0, idx *
  (H+GAP) / H)`). The nav area scrolls between the top bar and the pinned account strip, so a short window
  never clips it.
- `top_bar` is the **brand strip** (cube mark + wordmark, moved out of the sidebar 2026-10-26) and, under
  the custom frame, the title bar. Always 52 px; the min/max/close cluster rides it only when
  `_custom_chrome` is on. `ft.WindowDragArea(content=top_bar, ...)` is load-bearing for the smoke test.
- The rail resizes by dragging its right edge (`sidebar_resize` / `_set_sidebar_width`), clamped to
  116..220 px (default 120), no toggle. Account + Settings share a compact foot strip; the 96 px perch
  sets the min.
- The edge uses **horizontal drag**, not pan, and computes the width from `global_position.x - start_x`
  anchored to the drag-start width. Flet's drag events carry **per-event** deltas (`local_delta` is the
  movement since the previous event despite its "since the start" docstring), and a pan recogniser sends
  no `primary_delta` at all — accumulating pan events as if they were cumulative makes the rail look
  un-resizable. The grip is a 10 px transparent strip that tints on hover; double-click resets the default
  width. Width changes mutate the existing controls in place (`button widths`, `nav_blob.width`,
  `nav_stack.width`) and repaint only the sidebar box - never rebuild the nav rows per resize or hide
  labels per width.
- `switch_tab()` runs under `thread_safe_ui.TREE_LOCK` and sets **every** cached `_tab_views` pane to
  `visible = (k == key)`; hiding only the previous pane let a raced/worker transition leave two tabs on
  screen (2026-10-25). Paint the swap before per-tab refreshes; build lazy tabs before mounting.
- The hero PLAY click has a 0.35 s `_PLAY_CLICK_COOLDOWN` gate so a rapid double-press cannot run the
  username/config/Java pipeline twice; CANCEL/QUIT bypass it. A click that returns `False` releases the
  gate immediately (only a click that started work keeps it).
- A launch has three ordered claims: `installing_version` (cancellable install) → `launching_version`
  (install done, game not spawned) → `running_version` (process live). `set_button_mode("play")`,
  `_main_action_click`, `on_play_click` and `_begin_install_and_launch` all honour them, so a repaint
  inside the handover window cannot show PLAY or start a second game. `launching_version` is set under
  `_launch_state_lock` when `installing_version` clears and released in the worker's `finally`.

### Play and content

- **The version picker** is the one instance surface (2026-10-26): a right-hand slide-in panel
  (`ui/versions.py`, in `page.overlay`) with a 2-column grid of square Mojang key-art cards
  (`version_art.src`), title + subtitle below. Cards are **select-only** - Folder/Rename/Delete live on
  the Play card. "New instance" is the same panel with install-time loader chips; `_pick` passes a loader
  only in `"new"` mode, never vanilla.
- The Play card's loader control is a **read-only** `loader_readout` + `loader_note`
  (`_paint_loader_readout`); `loader_toggle` survives only as an unmounted mirror of `state["mod_loader"]`
  for the launch path and the smoke/ version tests. The card always shows Folder / Rename / Delete; there
  is **no** Advanced disclosure and no "Play this instance".
- `instances.describe()` is the single source of instance metadata (reads the last-played sidecar through
  the caller's `play_store`). Render from one `list_installed()` call; `mod_count()` is a cheap `scandir`.
  `mark_played()` records the instance that actually launched.
- Version selection repaints only the badge / server-status / loader / instance regions; do not put a
  whole-page `page.update()` back on the row-click path.
- Account and Settings are ONE centered, rounded popup (`account_panel` aligned CENTER + `account_card`),
  not a right-hand sidebar. `_account_panel_size()` scales it to the live window (~88% x 90%, capped
  1320x900, min 640x480) and `page.on_resize` refits it. The top account strip is ultra-compact (small
  avatar, name, one-line username field, Upload/Remove); the "Wearing" previews were removed 2026-10-26
  (`refresh_wearing()` is a no-op). Settings inside is a 188 px vertical rail plus a scrollable content
  pane.
- The online version list merges installed-only ids so opening "New instance" cannot drop an
  isolated/imported instance or move the selection.
- Reserve the loader-status slot and keep hero labels single-line; a notice appearing must not change hero
  height. Late artwork must never replace a newer selection (the banner is an opacity-only 180 ms
  transition).
- Vanilla accepts resource packs, not mods or shader packs. Other loaders are valid when compatible;
  shaders also require Iris/Oculus-style support.
- Content install gating uses the selected INSTANCE's real loader (`ui/mods_tab._instance_mod_capable` ->
  `instances.describe`), not `state["mod_loader"]` (a sibling instance or armed install can make the
  switcher say Fabric). A pending install for this version counts; packs always.
- `build_launch_command` only passes mll an `executablePath` that exists (`_normalize_java_path`); a
  missing/typo'd `java_path` falls back to `find_java_for_version`, never the raw config string
  (FileNotFoundError).
- `custom_jvm_flags` tokens go before the main class; a bare token becomes the main class
  (`ClassNotFoundException: 他他他`, 2026-10-25). `_parse_custom_jvm_flags` drops non-option tokens (keeping
  separate values of `--add-opens`-style options), and the doctor's `launch` section clears bad flags/a
  dead `java_path`; Fix crash reloads `cfg` after repair.
- Mod discovery has explicit compatible/all-Modrinth scope; broadened searches and direct project links
  never bypass install-time version/loader validation. Related-name fallback is labeled and stays on the
  same query across pages. The project detail dialog still lists builds for other game versions/loaders as
  "other version"; only browse rows hard-disable them. Do not describe the dialog as compatible-only.
- A version with no detected loader must leave `state["mod_loader"]` on the switcher's first option
  (vanilla), never `None`; browse/search code formats the loader name and a `None` there drops the
  Modrinth loader facet.
- The local cache stores fetch timestamps, not a caller-independent expiry. Stale reads never mark data
  fresh; empty mod searches retry after one minute.
- Launch-time checking is **config-only and non-interactive** (`include=("launch",)`, `check_online=False`,
  no approver): it repairs launcher-owned settings that kill Java before Minecraft starts, never touches
  content or waits on a question. Selecting an instance starts no scan; the doctor can never block a launch.
- Doctor repairs dependencies, version conflicts and duplicates at install time and on explicit "Check &
  repair" (`open_repair_review`). Old jars are renamed, never deleted; approvals live in `doctor_ui.py`
  and no approver means no destructive repair. Verified jars skip online checks; unavailable
  verification is one advisory, never a per-mod disable. The incompatible check is LOCAL (the jar's own
  `fabric.mod.json`), so a missing Modrinth release disables nothing.
- Launch sync links ONE build per mod and must pick the highest MOD version, not the Minecraft version:
  `_version_key(filename, mc_version)` strips the `+mc…` tail, `mc<ver>` tokens and the instance version,
  then uses the first dotted run; exact ties go to the newer file mtime. Never let our pick and Fabric's
  declared-version pick diverge (`sync_mods_to_game`).
- `sync_mods_to_game` writes `.cubeon-synced.json` in the shared `mods/` folder; only jars listed there
  are launcher-owned and may be removed. Any other jar is the user's: it is moved to
  `MINECRAFT_DIR/mods_user_backup/`, never deleted. A missing/corrupt manifest means "the launcher owns
  nothing". A locked launcher jar raises the "Another Minecraft window is using these mods" error instead
  of being skipped.
- The pack-install Play guard fails CLOSED: if `pack_install_for_instance()` raises, `on_play_click` and
  `_begin_install_and_launch` refuse and start nothing. Do not restore `except Exception: pass` there.
- Modpack UI: after `_end_install_ok()` paints "Installed … ✓", every refresh/handoff it calls must be
  wrapped and logged individually. `run_install()`'s worker has a broad `except Exception`, so one
  unguarded UI refresh makes an installed pack report as "Install failed".
- Modpack update pruning is `old − new`, and it must run ONLY after the new jars are on disk
  (step 6). The owned-jar list is `_modpack.json["jars"]` = manifest basenames ∪
  `_extract_overrides(..., written=set)` basenames. Deleting earlier loses a working pack when a
  download fails. `_extract_overrides` returns the int count (tested); the basenames come via the
  `written` out-param.
- Modpacks tab lag: `refresh_installed_packs()` only builds the Installed rows while the Installed pane
  is showing; rows live in `_render_installed_rows()`. One cached
  `_scan_installed_packs()` feeds the list, the tab count and the browse badges. Do not reintroduce a
  per-render `list_installed_modpacks()` call.
- A pack rebuild HIDES the marker (`_modpack.json` → `.bak`, `_hide_pack_marker`) instead of deleting
  it; `_install_from_zip` restores it on any failure/cancel and a successful install deletes the
  `.bak`. Never delete the marker up front again: that is what made a failed update "uninstall" a
  working pack. Marker backups are keyed by thread id.
- A failed pack download must leave the working pack's jars alone (8.1's prune runs only after the new
  set is on disk), and the restored marker keeps the old `jars` list so a retry can prune.
- `cubeon/local_api.py` `do_GET` must keep the top-level `try/except` around `_dispatch_get`:
  a provider that raises has to answer 500, never die with the socket. A bodiless reply is what the
  in-game mod reports as "Cubeon launcher isn't running".
- **Fix crash** (`play-fix-crash`) opens `open_crash_check`: read the NEWEST crash log, say what happened,
  then run the existing dependency/conflict/launch-config checks and fix what they can (`cubeon/crash.py`).
  No separate crash engine; clicking it is consent for safe reversible repairs. Mods -> Installed's
  "Review" opens `open_repair_review`.
- A modpack that needs isolation owns a cloned version folder plus `_cubeon_instance.json` (profile key,
  pack name, loader, base version, `built_from`). All mod/content/CSL/Friends/perf calls take that
  instance's `version_id`; no sidecar means the legacy `(mc_version, loader)` profile. Only an empty
  legacy profile or the same pack may be reused. `instances.list_installed` hides `built_from` build
  inputs so one pack is one instance; a user label keeps an install visible.
- Runtime `ft.Scale` must set both `scale_x` and `scale_y`: a null axis becomes an invalid Flutter
  matrix (`TransformLayer` spam). `test_repository_hygiene.py` enforces it.
- Shared storage must not leak one instance's active content into another. Installs/cancellation must
  respect instance ownership and atomic writes.
- FPS boost is the Play-menu toggle. Turning it off restores the previous settings; do not replace
  Sodium's defaults with unsupported tuning claims.

### Configuration and identity files

- `config.json` and `auth_key.json` are durability surfaces, not best-effort caches. Reads retry
  `OSError` before giving up; a readable-but-corrupt file is copied to `<name>.corrupt-<time>` (config
  keeps at most three) instead of being silently replaced.
- Losing identity changes who the player is to friends/skins/servers. `auth_key.json` identity is cached
  per path under `_AUTH_LOCK`, an unreadable file is never overwritten, and rewrites use unique
  `mkstemp` temp names. Do not "repair by rewrite" an unreadable identity file.
- A failed config load falls back to `_LAST_GOOD_CONFIG`, not hardcoded defaults; `_LAST_GOOD_CONFIG` is
  updated only after a successful load/save. Config I/O is UTF-8 explicitly.

### Chat, cosmetics, and account data

- Chat is BETA-labelled in the sidebar and tab heading. Chat and the companion mod consume one
  process-scoped FriendsService; keep adaptive polling, draft preservation, read markers, and optimistic
  send/echo intact.
- `roster_payload()` refreshes peer metadata once and resolves every friend against that snapshot; never
  call `peer_metadata()` per row (it re-scans the roster and re-reads identity.json, making the poll
  O(n^2)). The whitelist is cached by `whitelist.json`'s stat signature, roster faces by `(identities,
  faces.revision())`; a download bumps the revision.
- Self-avatar fallback is uploaded PFP, cached skin face, then initials; detect real source changes
  without re-reading unchanged bytes per poll.
- Cosmetic libraries are local folders. `remotes.py` is still used by the offline-session explanation's
  premium-name lookup; it is not dead code.
- Screenshots have their own Settings section, not the main Settings pane. Servers has no Browse view.
  Stats uses a compact recent-playtime histogram.
- Public UUIDs and display names are not private capability tokens. The loopback mod bridge is
  authenticated; never publish identity or token files.

### Cosmetics (shoulder and back items)

- `cubeon/cosmetics.py` owns the catalogue, preview quads, thumbnails, selection and
  `<game>/config/cubeon-cosmetics.json` (atomic, change-only; the mod polls it every 250 ms).
  `tools/gen_cosmetics.py` is the ONLY art source: it writes both `assets/cosmetics/` and the jar bundle,
  so never hand-edit a PNG or `catalog.json` - change the generator and rerun it.
- Preview (`preview_faces`) and Java `CosmeticGeometry.java` are ONE contract; `tools/test_cosmetics.py`
  compiles the Java classes and compares every quad and tile. Box space: +x left, +y down, -z front; pivot
  (0,12,0); preview uses `y' = 24 - y`, `z' = -z`.
- A wing's edge faces follow the cut-out silhouette at final atlas size; a full-rectangle top/bottom face
  is the "floating bar" bug, and a 16x16 edge tile loses its 1 px thickness line when downscaled to 3 px.
- Per-era overlays: `cosmetics-1.20` (1.20-1.20.4, manual normal), `cosmetics-1.20.5` (1.20.5-1.20.6,
  `Entry`), `cosmetics-1.21` (1.21-1.21.1), `cosmetics-1.21.2`, `cosmetics-1.21.5`, `cosmetics-1.21.9`,
  `cosmetics-1.21.11`, `cosmetics-26`; `next()` exists through 1.20.6, gone from 1.21. Map them in `brackets.json`.
- Local player only, back before shoulder. Unknown ids = no cosmetic, never a crash. Missing Fabric API
  costs cosmetics only (registration is try/caught). `assets/jars/cubeon-client-*.jar` is what ships, so
  refresh it after every mod build; `test_repository_hygiene.py` fails a tracked jar without the catalogue.
- Skin/Cape "None" is local: skin None writes the built-in Steve sheet to LocalSkin (beats a published
  Worker skin); cape None writes a transparent LocalSkin cape (`hide_cubeon_cape`). Friends keep theirs.

### Windows, Java, and packaging

- Preserve all three Windows reveal paths: forced visible transition, `to_front()` call, and the native
  `winwindow.py` backstop. Flet's default-value suppression can make a plain `visible=True` assignment
  ineffective.
- Hide consoles on every Windows child-process spawn. Custom window chrome works on **Windows and Linux**
  (`winchrome.custom_chrome_enabled`): Windows defaults OFF (needs a real-Windows reveal check), Linux
  defaults ON since 2026-10-26, `CUBEON_CUSTOM_CHROME=0/1` overrides either way, an explicit
  `custom_window_chrome` config value wins, and the one-time `custom_window_chrome_chosen` marker keeps a
  user's OFF from being migrated back on. macOS keeps the native frame. Maximize/fullscreen need explicit
  state.
- Verify Java by running it; the launch-time check is config-only and must never prompt. Do not blame Java
  for a graphics failure without evidence.
- The game must not inherit launcher-only software-graphics overrides. Crash text must not promise a fix
  that has not been verified.
- `mod/brackets.json` is the version-routing authority. Per-version source overlays are intentional; do
  not collapse them as accidental duplication.
- Current mod assembly needs JDK 25+ for Gradle, while bytecode targets Java 17.
- Bundle the Flet desktop client, color templates, required mod jars, and
  `assets/jars/connect-spigot.jar`. The large tunnel JAR is a runtime dependency.

## Documentation and repository hygiene

- Public documentation has one home under `docs/`; no duplicate agent mirrors. The player guide is
  `docs/user-guide.md`, platform checks are under `docs/release/`, and dated reports are under
  `docs/reports/`.
- The README uses `web/assets/cubeon-play.png`, the website's launcher image. Flat-square Shields badges
  show release, edition, and platforms; the version badge reads releases dynamically rather than
  hardcoding a stale version.
- Source licensing is Apache 2.0. Keep company/private checkout paths out of public instructions and do
  not add fabricated support or performance claims.
- Logs, compiled classes, captures, virtual environments, and build caches stay untracked. Historical
  local task notes are preserved under `archive/agent-history/`; Git retains their previously committed
  versions. Runtime JARs are not generated clutter.
- UI captures default to `archive/ui-captures/`, not the agent-reference tree. Old diagnostic snapshots
  are kept locally in `archive/agent-history/generated/`.
- Do not delete build caches while a build or worker is active. Local cleanup does not shrink existing Git
  history; do not rewrite history without approval.
- The repository lives at `~/Ylet_Productions/products/cubeon`; old `Products/Cubeon` or
  `Downloads/Cubeon` paths are obsolete. Do not create a parent-company Git repository or assume the old
  `.venv-build` is usable.

## Verification

Tests are standalone scripts, normally isolated with `_sandbox_home` and safe fixtures. Run the affected
script first, then the smoke gate.

```bash
python tools/test_mega_smoke.py
python tools/test_mega_smoke.py --static
python tools/test_mega_smoke.py --suites
node worker/test-worker.mjs
```

The default smoke gate does not run all registered suites; `--suites` does. See
[testing](../../docs/development/testing.md) for prerequisites and exclusions.

| Change | Focused checks in `tools/` |
| --- | --- |
| UI/tree contracts | `test_ui_smoke.py`, `test_motion.py`, `test_scrolling.py` |
| Play/selection/banner | `test_version_ui.py`, `test_version_art_cache.py` |
| Mods and artwork | `test_mod_ui_stability.py`, `test_loader_content_rules.py` |
| Instance isolation | `test_modpacks.py`, `test_instances.py`, `test_versions_profile_key.py` |
| Mod discovery | `test_mod_search.py`, `test_mod_detail.py` |
| Doctor and crash repair | `test_crash.py`, `test_doctor_consent.py`, `test_launch_fixes.py` |
| Chat | `test_chat_avatar_stability.py`, `test_chat_optimistic.py`, `test_faces.py` |
| Cosmetics | `test_cosmetics.py`, `test_appearance_preview.py`, `test_capes.py` |
| Windows/startup | `test_winwindow.py`, `test_winchrome.py`, `test_startup.py` |
| Mod sources and jars | `test_mod_compile.py`, `test_mod_matrix.py`, `test_mod_bridge.py` |
| Releases | `test_release_version.py`, `test_release_pipeline.py` |
| Repository cleanliness | `test_repository_hygiene.py` |

## Releases and hosted services

- A push to `main` starts the release workflow. Publishing, committing, deploying, and rewriting history
  require the user's explicit request.
- `tools/release_version.py` owns stamping/channel policy. Zero-patch versions are stable; nonzero-patch
  versions are beta. Preserve concurrent release metadata and do not force-push over another change.
- Publishing verifies the required assets. Test jobs are separate; a published release does not establish
  that every test or desktop smoke check passed.
- Worker configuration is not proof of current deployment health. Preserve client/Worker protocol parity,
  authentication, write budgets, and rate limits.
- See [builds](../../docs/release/build.md), [security](../../SECURITY.md), and
  [Worker deployment](../../worker/README.md) for the current public references.
