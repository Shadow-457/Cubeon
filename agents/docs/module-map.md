# Cubeon module map — read this before reading any source

Last updated: 2026-09-22 (site = `web/` on Vercel at cubeon.vercel.app: landing /
download / help + legal pages sharing web/assets/site.css + site.js; its release
download count has two sources, an API function and a CI-refreshed static JSON —
see the web bullets further down. The waitlist is gone, the repo is private.) If a
fact here contradicts the code, the code wins — but fix this file too. Durable
facts belong HERE, not in diary notes.

## A mixin must name a method its OWN target DECLARES (2026-09-27) — INVARIANT
- **Mixin resolves `@Inject(method=...)` against the methods the TARGET CLASS
  ITSELF declares. An inherited method is not found.** With `require = 0` that
  is a **silent no-op**, not a failure — the mixin loads, the game runs, and
  the feature simply never happens.
- This cost a whole build cycle: `MenuPaintMixin` was written as
  `@Mixin(ModuleMenuScreen.class)` injecting `render`, but `ModuleMenuScreen`
  only INHERITS `render` from `Screen`. The menu never painted — no panel, no
  text, just empty invisible buttons — while every test stayed green.
- **Fix, and the pattern for any inherited method:** target the class that
  DECLARES it and guard on the instance type —
  `@Mixin(Screen.class)` + `if (!((Object) this instanceof ModuleMenuScreen)) return;`
  Per bracket, because `render` is `Screen.render(GuiGraphics,…)` on 1.20-1.21
  and `Screen.extractRenderState(GuiGraphicsExtractor,…)` on 26.x.
- **Guard:** `tools/test_mod_compile.py` now parses every mixin in
  `MOD_SOURCES`, resolves its `@Mixin` target (including unqualified names and
  simple names — a mixin in `…client.mixin` imports its target from
  `…client`), and asserts each injected method is declared in that source.
  Verified it FAILS on the original bug and PASSES on the fix. The `@Mixin`
  regex is line-anchored so a javadoc explaining the bug is not mistaken for the
  annotation — that was a false positive the guard itself had first.
- Every other mixin here is fine *by construction*: their targets declare
  what they inject — `Gui.render`, `LocalPlayer.tick`, `PauseScreen.init`,
  `TitleScreen.init`, `PlayerTabOverlay.getNameForDisplay`,
  `Player.getDisplayName`. Check that list before adding another.


## The mod menu PAINTS itself — never use vanilla widgets for it (2026-09-27) — INVARIANT
- **A lesson paid for once: the first mod menu was built from vanilla
  `Button`/`EditBox` widgets and the user rejected it outright** — grey bevelled
  buttons, a ragged grid, reads as a Minecraft options screen. "Avoid custom
  drawing so one jar serves both brackets" is the WRONG reason to make
  something look bad. The menu now paints its panel, tabs and cards itself.
- **How it still ships one jar:** `MenuPaint` is a two-method interface
  (`fill`, `text`) with one tiny implementation per bracket (`MenuPaintImpl` in
  each `java-overlay-*`). That is the ONLY per-bracket part of the menu. All
  layout, colours, rounded corners and hover live in the shared `MenuPainter`,
  which builds every shape from plain rectangles.
- **`MenuPaintMixin` (per bracket, same FQN) is the paint hook** — 1.20-1.21
  injects `Screen.render(GuiGraphics, ...)`, 26.x injects
  `Screen.extractRenderState(GuiGraphicsExtractor, ...)`. Unavoidable: the two
  signatures are unrelated.
- **Opaque colours only.** 26.x's extractor has no alpha `fill`, so a
  translucent panel would render right on one bracket and as a solid block on
  the other. The palette is deliberately all-opaque so both look the same.
- **Clicks are still vanilla widgets** — invisible Buttons over each painted
  element — because `mouseClicked`'s signature changed in 26.x and widgets are
  the cross-era way to get input. The buttons draw NOTHING; `drawOverlay`
  paints over them.
- **Never hard-code the column count.** It is derived from the panel width;
  the first version fixed two 150px columns and left the toggles floating
  outside their cards. `MenuPainter.clip()` truncates card text with an
  ellipsis instead of letting it run past the card edge.


## Mod menu + module framework (2026-09-27) — INVARIANT
- **The mod menu is `ModuleMenuScreen`, opened by the "Mods" button that
  `PauseScreenMixin` drops in next to the Friends icon.** No keybind: that
  needs `fabric-key-binding-api` and this mod ships **no Fabric API modules**
  (loader only). A keybind is a one-line change IF the user accepts the dep.
- **The whole framework is Minecraft-FREE and unit-tested on a bare JDK**:
  `modules/Module`, `ModuleConfig`, `ModuleCategory`, `HudText` import nothing
  from Minecraft. That is the point — it is what makes the config format, the
  clamping and the category filtering testable at all. Guards:
  `tools/test_mod_bridge.py` (SelfTest moduleFramework/hudTextLines, 164
  checks) and `tools/test_mod_compile.py` (compiles it all).
- **A module that throws in `apply()` reports itself OFF, not on** — a toggle
  that lies is worse than no toggle. Pinned in SelfTest.
- **Option modules go through `Options` ACCESSORS (`gamma()`, `fov()`,
  `bobView()`), never the public fields.** 26.x turned the fields into
  accessors; the field spelling compiles on 1.20-1.21 and fails 26. All three
  were javap'd in both real jars. This is the single most important rule for
  adding a module.
- **`player.input` is NOT cross-era** — 1.20.1 has a public
  `input.forwardImpulse` field, 26.x has `ClientInput.hasForwardImpulse()`.
  Auto-sprint therefore reads `options.keyUp.isDown()`. Do not "fix" it to use
  the input. The real 26 build caught this; the stub would not have.
- **Only the HUD DRAW is per-bracket** (`HudMixin`, same FQN in both
  `java-overlay-*` dirs, exactly as `CornerIcon` does): 1.20-1.21 injects
  `Gui.render(GuiGraphics, float)`, 26.x injects
  `Gui.extractRenderState(GuiGraphicsExtractor, DeltaTracker)`. Everything
  deciding *what* to draw is shared in `HudState`/`HudText`.
  `_check_mixin_wiring` now accepts overlay mixins and asserts a per-bracket
  one exists in BOTH overlays.
- Config lives at `<game>/config/cubeon-modules.json` via
  `FabricLoader.getConfigDir()`; writes are atomic (tmp file + move).
- **Not verified in-game.** The menu has never been opened, and HUD drawing is
  the one part that cannot be compile-checked against the stub. Both jars
  build, but a real launch is the proof.

## Tab-list `[Cubeon]` tag (2026-09-27) — INVARIANT
## Tab-list `[Cubeon]` tag (2026-09-27) — INVARIANT
- **Cubeon players are tagged in the TAB LIST only** — `TabListTag.decorate()`
  prepends a green `[Cubeon]` to each row. The nametag above a head is
  deliberately NOT tagged (see the badge-removal invariant below): the tab list
  is your own screen and nobody else's, so this is private; a floating nametag
  is on display to the whole server, which is why that one went. Guard in
  `tools/test_mod_compile.py::_check_mixin_wiring` asserts the nametag mixin
  stays unregistered.
- **The injection target is `PlayerTabOverlay.getNameForDisplay(PlayerInfo)`**
  and that choice is load-bearing. The tab list *renderer* is the most-reshaped
  thing between eras — 1.20-1.21 has `render(GuiGraphics,…)`, 26.x has
  `extractRenderState(GuiGraphicsExtractor,…)` — but `getNameForDisplay` is
  byte-identical in both (verified with `javap` against the real 1.20.1 and
  26.1.2 jars). One injection, both brackets. **If you retarget it, re-`javap`
  both jars first**; don't assume. The guard fails loudly if the method name
  changes.
- **Exact green, via `TextColor.fromRgb(0x83C13D)`**, not
  `ChatFormatting.GREEN` (a different colour, and all the old nametag badge
  could use on 1.20-1.21). `Style.withColor(TextColor)` and
  `TextColor.fromRgb(int)` are identical in both eras.
- **Only names the launcher can vouch for.** Reuses `BadgeNames` — you, your
  friends' Minecraft usernames, and the `/players` roster. A stranger running
  Cubeon is NOT tagged; the client cannot ask "is this an arbitrary name a
  Cubeon account". The name set is rebuilt only when `Bridge.revision()` /
  `playersRevision()` move (this runs per-row per-frame).
- **`_check_mixin_wiring()` in tools/test_mod_compile.py** is the guard for
  the three moving parts (mixin config ↔ `MOD_SOURCES` ↔
  `build_mod_jars.REQUIRED_ENTRIES`). An unregistered mixin silently does
  nothing in-game; a stale `REQUIRED_ENTRIES` entry fails a real build over a
  class that no longer exists. Verified it actually fails when broken.
- Requires `net/minecraft/client/gui/components/PlayerTabOverlay` and
- **`GameProfile`'s name accessor is resolved REFLECTIVELY**
  (`TabListTag.nameOf`), and this is the one sanctioned exception to the "only
  touch API that has not moved" rule. authlib 7 turned `GameProfile` into a
  **record**, renaming `getName()` -> `name()`. The rename lands *inside* the
  1.20-1.21 bracket's own range (1.20.1 ships authlib 6.0.54, 1.21.11 ships
  7.0.61), so a per-bracket overlay cannot save it — `brackets.json`'s
  "compile against the oldest" assumes the oldest's members still exist in the
  newest, which is **false** for `getName`. Caught by the real 26 build, not
  the stub. The 26 bracket is unaffected (7.0.63/10.0.77 are both records).

## Nametag badge REMOVED from the in-game mod (2026-09-27) — INVARIANT
  `net/minecraft/client/multiplayer/PlayerInfo` in the compile stub.

## Nametag badge REMOVED from the in-game mod (2026-09-27) — INVARIANT
- **The `[#]Shadow` nametag badge no longer exists.** It was drawn by a mixin
  on `Player.getDisplayName()` (per-visible-player-per-frame). Removed because
  it stamped the launcher onto other people's names in a game they did not
  choose to join. `Nametag.java` and `mixin/PlayerNameMixin.java` are deleted,
  `PlayerNameMixin` is out of `cubeon-client.mixins.json`, and the `badge()`
  method is gone from BOTH `CornerIcon` overlays (1.20-1.21 and 26).
- **`BadgeNames.java` is KEPT** (with its SelfTest coverage) even though nothing
  in the mod calls it now. It encodes a hard-won rule — a relay *handle* is not
  a Minecraft *username*, and matching on handles badged nobody. Reachable for
  any future non-name-marking use. Don't delete it as "dead code."
- **Two build lists must be kept in sync** or the mod silently stops
  building/shipping: `tools/test_mod_compile.py` `MOD_SOURCES` and
  `tools/build_mod_jars.py` `REQUIRED_ENTRIES`. Both referenced the deleted
  mixin; a stale entry there is a build failure, not a warning.
- `net/minecraft/.../Player` stays as a stub class in `test_mod_compile.py`'s
  API surface, but nothing references it now — a future mixin that needs it
  must justify its target surface there.

## Managed Java runtimes (2026-09-27) — INVARIANT
## Managed Java runtimes (2026-09-27) — INVARIANT
- **The launcher OFFERS to download Java; it never downloads unasked.**
  `cubeon/jre.py` fetches a Temurin **JRE** (not JDK — Minecraft never
  compiles) from the Adoptium API into `~/.cubeon_launcher/runtimes/<major>/`.
  `main.on_play_click` calls `jre.java_status(mc_version, cfg["java_path"])`
  and shows `_prompt_for_java` only when the machine has no Java new enough
  AND the version is not already installed. "Not now" (or dismissing the
  dialog) cancels the whole install — it must not fall through and install
  Minecraft anyway. Guard: tools/test_launch_fixes.py §14.
- **A managed runtime is a LAST resort, never a replacement.** They are
  appended to the candidate list in `launch.find_java_for_version` AFTER
  Settings → PATH → JAVA_HOME → the mll scan, so installing one can never
  change what a user who already has Java is running. §14 asserts that
  ordering by source position — do not "optimise" it into an earlier slot.
- **The Temurin archive nests the JRE one level deep**
  (`jdk-17.0.20.1+1-jre/bin/java`). `install_jre` MUST promote that inner
  home to `runtimes/<major>/`, because `managed_java()` looks for exactly
  `runtimes/<major>/bin/java`. This failed on the first real end-to-end run
  ("Java 17 did not install correctly" with a working JVM on disk) — the
  unpack was fine, the move was wrong. Don't "simplify" the staging back to
  moving the extraction root.
- **Atomic + verified:** sha256 from Adoptium is checked before unpacking;
  extraction goes to `<major>.part`, the home to `<major>.part.home`, and
  only then `os.replace` into place. Every failure path removes both temp
  dirs, so a crashed install can never leave something `managed_java()`
  reports as usable. Zip/tar members are checked for path escape (ZipSlip).
- **`SUPPORTED_MAJORS = (8, 16, 17, 21, 25)`** is deliberately exactly the set
  `required_java_major()` can return, so a version can never demand a Java
  the launcher cannot supply. §14 asserts that correspondence.

## Tray / background mode REMOVED (2026-09-27) — INVARIANT
- **There is no system tray and no background mode any more.** `cubeon/tray.py`
  is deleted, the `close_to_tray` setting is gone from `cubeon/config.py`, and
  `pystray` is no longer a dependency. A closed window now ENDS the process:
  `_session_loop` returns on `clean_close` instead of parking, and there is no
  reopen/park bookkeeping. Reason: on Flet 0.86/GTK the X button destroys the
  window/session and delivers no "close" event, so "background mode" could
  only ever mean a headless parked process. Guard: tools/test_ui_smoke.py
  "the tray is gone from the launcher entirely" (asserts `TrayController`,
  `_stop_tray_best_effort`, `_tray_runtime` and `pystray` are all absent from
  main.py). Do not reintroduce it without the user's say-so.
- **`_tray_runtime` is now `_session_runtime`** (same shape minus the tray
  keys): it still holds the process-scoped friends service/client and the
  gamepad watcher's `controller_*` slots, which outlive a single window
  session. Anything reading `app._tray_runtime` must be updated.
- **`CUBEON_TRAY_REOPEN` is now `CUBEON_RELAUNCH`**, set by
  `_relaunch_fresh_process()`; main() pops it to suppress the
  "orphaned Minecraft session" prompt after a deliberate relaunch.
- **`_reclaim_session_signals()` no longer sets an event.** It only counts
  presses in `_session_signal_hits`: the first ^C is swallowed so the bounded
  teardown finishes, the second is `os._exit(0)`. The reclaim itself is still
  load-bearing — flet never removes its own handler, so without it a ^C during
  `_ct.join` raises `RuntimeError('Event loop is closed')` from inside the
  handler (guard: tools/test_ui_smoke.py §4d).
- **`window.prevent_close` is still never set.** It makes the window
  unclosable on this Flet build. Since the tray is gone there is no reason to
  even consider it.

## Cancel outgoing requests / reopen dupes / geometry / no-source-leak (2026-09-23, 2nd pass) — INVARIANTS
- **Cancel pending outgoing requests**: one DECLINE frame serves both
  directions — worker `onDecline` MUST delete
  `(requester=? AND target=?) OR (requester=? AND target=?)` (receiver
  declining + requester cancelling). The Chat tab's outgoing row carries a
  "Cancel" pill wired to `service.decline`. Guard: tools/test_friends.py
  parity checks. **DEPLOYED 2026-09-24** (`npx wrangler deploy -c
  wrangler-friends.toml`, version 6514cc53-6a5c-4167-acac-9a2b63e4e58f) and
  verified live with a two-identity probe: add → cancel → both rosters clean
  → reconnect → still clean. Before that deploy the production Worker still
  ran the one-directional DELETE, which is why a cancelled request came back
  on the next launch. The client half is durable too:
  `FriendsClient.decline_request` drops the name from the cached roster and
  rewrites `friends_cache.json` (guard: tools/test_friends.py "durable
  cancel" block).
- **Chat reopen dupe**: `_hydrate_chat_store` MUST keep each message's `id`
  and `envelope` and skip entries already in the ring (id → envelope →
  (dir,text,ts) key, seeded from the room BEFORE the loaded rows, because
  `__init__` hydrates and callers may hydrate again). Dropping those fields
  was why every restart re-played history into the ring forever.
  Guards: tools/test_friends_service.py "S10" block (5 checks).
- **Window geometry**: the save tuple needs BOTH flet spellings
  (`resized`/`resize`/`move`/`moved`); `_reveal_window` re-asserts a saved
  left/top (and size) after the first frame, because the late native write
  that stomps centering also stomps a restore → "always top-left". Guards:
  tools/test_ui_smoke §4c geometry checks.
- **Shipped artifacts must contain NO readable source**: never `--add-data`
  `templates/` (palettes ship as bytecode via `--collect-submodules
  templates`; `apply_template()` imports them as modules, never by path) and
  never `mod/` (only `mod/brackets.json`). Windows/macOS/AppImage/deb all
  inherit this from their build scripts + Cubeon.spec.


## Post-session signals + friends-hub harness (2026-09-24) — INVARIANTS
- **flet leaves its SIGINT/SIGTERM handler installed forever.** After `ft.run`
  returns, `exit_gracefully` pokes a CLOSED asyncio loop, so any ^C raises
  `RuntimeError('Event loop is closed')` *from inside the signal handler* at
  whatever main-thread frame happens to be running (observed live 2026-09-24:
  it escaped `_ct.join(timeout=3.0)` as a `cubeon.fatal` CRITICAL right after
  "quit from tray"). `_reclaim_session_signals()` MUST run immediately after
  every `_run_flet_once()` return: first press sets the tray quit event
  (graceful exit through the normal loop), a second press is an immediate
  `os._exit(0)`. The parked wait therefore polls at 0.5s
  (`_reopen.wait(timeout=0.5)`) - the handler only SETS the event, so a long
  tick makes ^C feel dead; Tray Open still wakes instantly. The in-`ft.run`
  race is caught by its exact message. Guards: tools/test_ui_smoke §4d
  (source ordering + a real SIGINT/SIGTERM fired at the test process).
- **`worker/test-friends-rooms.mjs` is the RUNNABLE Hub harness**: it wires the
  real `Hub` to an in-memory `node:sqlite` and executes request/decline/CANCEL
  semantics (17 checks on that path), not just the source-parity greps in
  tools/test_friends.py. Run `node worker/test-friends-rooms.mjs`. It tracks
  the 8-digit uid format (`0000000X`) - if the worker's UID_WIDTH ever moves,
  this file must too or it fails at the first metadata assertion.

## Windows icon asset (2026-09-24) — INVARIANT
- **`assets/icon.ico` is GENERATED, never hand-drawn.** The source of truth is
  the transparent `assets/icon_512.png` (all PNG variants are already alpha
  clean: corners `(0,0,0,0)`). The checked-in `.ico` had been an OLDER,
  desaturated render baked onto an **opaque white plate** (every corner
  `(255,255,255,255)`, zero transparent pixels) — so every Windows surface
  (exe, Start Menu/Desktop shortcuts, taskbar, the Flet window icon) showed a
  white square around a washed-out cube while Linux/web showed the correct
  vivid transparent art. Rebuild it with:
  ```python
  from PIL import Image
  Image.open('assets/icon_512.png').convert('RGBA').save(
      'assets/icon.ico', format='ICO',
      sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
  ```
  and assert every layer's corner alpha is 0. Only the Windows artifacts embed
  the `.ico` (AppImage/deb/desktop entry use `icon_256.png`, already correct),
  so an icon change needs a Windows rebuild, not a Linux one.
- Every Windows build path passes `--icon=assets/icon.ico` (build_windows*.py)
  and `icon='assets/icon.ico'` in Cubeon.spec EXE — keep that wiring when the
  icon is regenerated, or Windows silently falls back to PyInstaller art.

## Loader installs must pass a VERIFIED Java (2026-09-24) — INVARIANTS
- **A mod-loader install EXECUTES a downloaded installer jar with Java**
  (mll 8.0: `if java is None: java = "java"`, then
  `subprocess.run([java, "-jar", installer, ...])`). Cubeon ships **no JRE**, so
  any call that omits `java=` dies on a keyless Windows box as
  `FileNotFoundError: [WinError 2] The system cannot find the file specified`
  printed raw under the download button (the 2026-09-24 Fabric report).
- `mod_loaders.install_mod_loader()` must therefore call
  **`mod_loaders.loader_java(mc_version, loader_id)` first** and pass `java=`
  (plus a pinned `loader_version=`) to `loader.install(...)`. `loader_java`
  reuses `launch.find_java_for_version()` — Settings path → system java →
  **JAVA_HOME** → every JVM, lowest sufficient major — and verifies the file
  exists **AND is new enough**: `find_java_for_version()`'s deliberate
  bare-`"java"` fallback (so a too-old Java surfaces Minecraft's own error at
  LAUNCH) is exactly what must never reach an installer. No Java ⇒ a readable
  "install Java N+ / set it in Settings" error BEFORE any download starts.
  Guard: tools/test_launch_fixes §8b (fake mll-8 loader; asserts java passes
  through and nothing runs without Java).
- **Java sources are 4, and a JDK FOLDER counts as a java path** (2026-09-26).
  The banner "Java N+ wasn't found" reached users who plainly had a JDK,
  because resolution read only Settings `java_path` → PATH → mll's scan.
  `JAVA_HOME` is now read by `launch._java_home_binaries()` (unquoted, both
  `java`/`java.exe`; a `JAVA_HOME` that isn't a dir is ignored) and
  `launch._normalize_java_path()` resolves a **directory** argument to its
  `bin/java`, so pasting the JDK folder into Settings works. Guards:
  tools/test_launch_fixes §8d/§8e.
- **There is EXACTLY ONE User-Agent string: `paths.user_agent(project)`.** (2026-09-26)
  Modrinth requires a uniquely-identifying UA (a library-only agent gets you
  blocked) and recommends contact info so they can reach us *before* blocking;
  their tiers are `name` → `user/name/ver` → `user/name/ver (contact)`. We emit
  the Best shape, e.g. `Cubeon/1.0.1 (modrinth; https://github.com/Shadow-457/Cubeon)`.
  It used to be a hardcoded literal in 8 places and had already drifted 3 ways,
  one pointing at a non-existent `github.com/cubeon`. Use
  `paths.modrinth_headers()` for api.modrinth.com AND cdn.modrinth.com (the
  mod-art downloaders share it), and `paths.user_agent(<subsystem>)` for
  everything else (Paper, CurseForge, Minekube, Mojang). **Never** hardcode a
  second one. Guard: tools/test_net.py §UA (asserts the shape, the real
  version, and greps all 9 modules for inline `User-Agent` literals).
- **`APP_VERSION` must stay a literal in `updater.py` — do not "tidy" it.**
  `packaging/build_windows_installer.py` regex-greps
  `APP_VERSION\s*=\s*"([^"]+)"` straight out of `cubeon/updater.py`'s SOURCE, so
  re-exporting it from `paths` (or reformatting the assignment) silently breaks
  the Windows installer. `paths.app_version()` therefore imports it lazily
  inside the function, because `paths` is the lowest layer and must not depend
  on a module that does network work — and that also keeps `requests` off the
  startup path.
- **`loader_java` must REJECT a too-old Java, not just a missing one.** Existence
  is not sufficient: an installer jar is EXECUTED, so a Java 8 on PATH (found
  via the deliberate fallback) used to sail through the old `os.path.isfile()`
  check and die on a raw `UnsupportedClassVersionError` instead of the
  actionable banner — i.e. the same banner, on a different code path. It now
  probes `java_major_version()` and appends "Only Java N was found, which is
  too old for <mc>." An **unprobeable** binary (major `None`) is still
  accepted, as before. Guard: tools/test_launch_fixes §8c.
- **The N in that message is the SELECTED MC version's requirement, not the
  user's Java** — `required_java_major()`: ≥26.1→25, ≥1.20.5→21, ≥1.18→17,
  ≥1.17→16, else 8. So one build legitimately shows "Java 17+" on 1.20.1 and
  "Java 21+" on 1.21.x. Not a detection bug; don't go hunting for it.
  Guard: tools/test_launch_fixes §8c last check.

## CurseForge modpacks in the Modpacks tab (2026-09-24) — INVARIANTS
- **Keyless CF access can RESOLVE a project but never LIST/SEARCH one.** Every
  alternative was probed live and is dead: curseforge.com (search page, RSS
  feed, sitemap) = Cloudflare 403; `api.curseforge.com/v1/mods/search` = 403
  without a key; api.cfwidget.com has no list/search endpoint; FTB API = 404;
  ATLauncher = 403; Prism's featured-instances feed = 404. **NEW CurseForge
  packs are therefore only reachable with a key** (free, from
  console.curseforge.com). Don't re-litigate this — it's measured, not assumed.
- **The key must be settable from the UI**: `modpacks.set_curseforge_api_key()`
  + `check_curseforge_api_key()` (both re-exported by `launcher_core`) back the
  "Add free CurseForge key" dialog in `ui/modpacks_tab.py`. Validation runs a
  REAL one-call search first so a wrong key is reported instead of silently
  degrading. `search_modpacks_curseforge()`'s cache key MUST keep its `keyed`
  flag — pasting/removing a key swaps providers, and without it the tab serves
  the other provider's cached page for up to a day.
- **cfwidget payload shapes**: `downloads` is `{"monthly":N,"total":N}` (read
  `["total"]` or every row shows 0), art is `thumbnail`, author is
  `members[0].username`, MC versions live in the grouped `versions{...}` map
  (loader tags like "Forge" appear there too and must be filtered). The curated
  fallback catalogue is `CURATED_CF_PROJECTS` — project IDs, not slugs, because
  slugs get renamed and 404 silently (that rotted the list from 12 to 7 live
  entries). Guard: tools/test_modpacks_cf_keyless.py.

## Chat dupes + latency / restart button / Windows packaging (2026-09-23) — INVARIANTS
- **Chat dupe rule**: a red "Couldn't send" bubble STAYS in `_pending`
  (`failed:True`); a late echo REPLACES it in place instead of appending.
  Dropping failed entries (the old code) re-appended the real line → one
  message rendered twice. Guard: `tools/test_chat_optimistic.py` (12 checks,
  registered in test_mega_smoke SUITES).
- **Chat cadence is adaptive**: `_poll_interval()` = 0.25s while `_pending`
  or within `_CONFIRM_WINDOW_S` after a send, 0.5s with a conversation open,
  else 1.5s. A tick is ~2ms in-process work - do NOT "optimize" back to a
  fixed slow poll; the old fixed 1.5s is why confirmations felt laggy.
- **Restart-to-apply / tray stop**: every execv-bound path (Settings >
  Restart, GPU-crash recovery, tray Open) must stop the tray through
  `_stop_tray_best_effort()` — NEVER a raw `_ctrl.stop()`: pystray/GLib
  teardown hangs (futex_wait on KDE) and used to sit between the Restart
  click and the execv, i.e. window closes, nothing relaunches. Guard:
  tools/test_ui_smoke §4c (also clicks the real button and asserts the
  relaunch request + window close).
## Windows packaging / Installer UI / Version 1.0.1 (2026-09-24) — INVARIANTS
- **Windows icon**: EVERY Windows build path passes `--icon=assets/icon.ico`
  (build_windows*.py and `icon='assets/icon.ico'` in Cubeon.spec EXE).
- **Installer UI (MUI2)**: `packaging/Cubeon.nsi` uses Modern UI 2 with branded
  wizard & header bitmaps (`packaging/graphics/wizard.bmp` and `header.bmp`),
  `ShowInstDetails hide`, `ShowUnInstDetails hide`, friendly non-technical copy,
  and Start Menu + Desktop shortcut registration.
- **Flet Image Fit**: Flet 0.86 uses `ft.BoxFit` (e.g. `ft.BoxFit.COVER`), NOT
  `ft.ImageFit`. Any image fit must use `ft.BoxFit`.
- **Release Version**: `cubeon/updater.py` APP_VERSION is `1.0.1`, reflected on
  `web/index.html` and `web/download.html`.


## Chat face avatars (2026-09-22) — HOW-TO
- `cubeon/faces.get_face_b64(name)` is THE way to show any Cubeon player's
  head (skins Worker `/faces/<name>.png`, disk-cached in `cache/faces/`,
  negative-cached 10 min for non-Cubeon 404s, background download, never
  blocks). Pair it with a `bool(get_face_b64(...))` token inside the
  repaint sig so late-landing faces paint on the next poll.
- Self-avatar fallback chain everywhere: uploaded pfp → face URL
  (`skins.get_skin_face_url` = Cubeon endpoint since 2026-09-22, was
  crafatar which 404s for offline accounts) → color chip.


## AuthMe tuner (2026-09-22) — INVARIANT
- `cubeon/server.py::_tune_authme_config` section tracking MUST be an indent
  stack, not a single "current section": AuthMe 6.x (ConfigMe) writes
  sections at indent 4, legacy AuthMe at 2. The old `indent <= 2` check made
  the tuner a silent no-op on modern configs (guard script in
  agents/2026-09-22_cline_authme-tunnel-reglimit.md).
- `AUTHME_TUNING` includes `restrictions.maxRegPerIp: 0` (unlimited): every
  player through the Minekube tunnel shares one apparent IP, so the stock
  per-IP registration cap (default 1) makes the first registrant block
  everyone. Do not "restore" a per-IP registration cap on tunneled servers.


## Wedged flet client / open-quit truth (2026-09-19) — INVARIANT
- The flet desktop client's bad case is NOT always a crash. It can WEDGE: window
  mapped, not one OpenGL frame, ~180% CPU, and `ft.run` never returning
  (measured live on Mesa 26.1 / AMD Polaris). Everything that recovers a session
  lives AFTER `ft.run` returns, so a wedged client makes tray Open/Quit, the
  software-GL retry ladder and Settings > "Restart to apply" ALL unreachable —
  the frozen window stays forever and the launcher can never be reopened.
- Detection is the client's own evidence: GLib writes
  `** (flet:N): WARNING **: <time>: Timed out waiting for OpenGL frame ...`
  **on stderr**. `_filtered_open_flet_view_async` merges the streams
  (`stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT`) and
  forwards filtered lines to `sys.__stderr__` with an explicit flush. DO NOT go
  back to filtering only stderr: a fake/alternative client logging to stdout
  silently defeats the counter (that exact mistake made a "verified" test
  vacuous on 2026-09-19).
- Measured signature of a real wedge: exactly TWO GL-frame-timeout lines ~0.15s
  apart, then silence forever while alive (rt2.log pid 29728 was a 34-minute
  ghost). Hence `_WEDGE_TIMEOUTS = 2`, `_WEDGE_RECENT = 25.0`, with
  `_WEDGE_GRACE = 12s` / `_WEDGE_WINDOW = 60s`. A threshold of 3 was
  unreachable dead code — do not raise it back without new measurements.
- The watchdog only KILLS the client (SIGTERM, SIGKILL after 3s). It never tears
  down the session itself: `ft.run` is once-per-process. The kill makes `ft.run`
  return and the EXISTING classified ladder does the rest (pre-paint ->
  software-GL retry; painted-but-dead -> re-exec).
- Residual gap (accepted, never observed): a client that wedges WITHOUT logging
  any line is not detected.
- Guards: `tools/test_wedge_watchdog.py` (deterministic fake with the measured
  signature; asserts kill + retry + termination + no ghost), registered in
  `tools/test_mega_smoke.py`'s SUITES.
- `_kill_flet_client()` also sweeps ORPHANED clients at session start (a `flet`
  process whose args carry our assets dir and whose parent is no longer a live
  launcher = ghost from a dead run). Two-factor on purpose, so a second live
  Cubeon instance is never touched.

## P2P stream teardown (2026-09-19) — INVARIANT
- A received `_FIN` must NOT close the local TCP socket immediately: bytes can
  still be queued in `_tcp_in_queue`, and closing there truncates the tail
  (measured: a 120000-byte transfer cut at 118535). `_handle_frame` sets
  `_remote_eof`; `_tcp_delivery_loop` drains, then stops the session with
  "Minecraft TCP connection closed". The FIN we send waits until
  `_unacked` is empty so it can't overtake a retransmission.
  `tools/test_p2p_transport.py::fin_drain_check` is the deterministic guard.
- `RelaySession` (WebSocket relay) still stops immediately on local close with
  `_in_queue` possibly non-empty — same shape, deliberately unchanged
  (documented in docs/bugfix-2026-09-18-ci-red-suite.md).

## Version scan (2026-09-19) — INVARIANT
- `versions.get_installed_versions()` pass 2 dedupes by FOLDER only. Deduping
  on the json's declared `id` made the list depend on `os.listdir()` order and
  silently dropped half-installed folders whose template manifest still named
  another version (they showed as neither installed nor incomplete).
  Guard: `tools/test_version_integrity.py`'s forced-order check.

## CI / release storage (2026-09-19) — INVARIANT
- One run's artifacts (~510 MB) are bigger than the whole free Actions storage
  quota (~500 MB). Artifact upload steps are **tag-only**
  (`if: startsWith(github.ref, 'refs/tags/v')`), `retention-days: 7`, and
  `continue-on-error: true` (publishing must never mark a good build red).
  Branch pushes still build; they do not publish. Do not move uploads back to
  every push.
- The REAL publishing channel is GitHub release ASSETS: on tag builds each
  build job runs `gh release create/upload --clobber` directly (release
  assets are exempt from the Actions storage quota, which stayed exhausted
  even 23h after purging 19 GB of artifacts). The three build jobs carry
  `permissions: contents: write`; the workflow root is `contents: read`.
  Tag builds FAIL if the release upload fails — that's intentional.

## Play-button state machine (2026-09-18) — INVARIANT
- The play button's mode is computed by `set_button_mode()` in `main.py`,
  which repaints ONLY the button subtree (`thread_safe_ui.refresh(play_button)`)
  — never a whole page.update(). If a call site needs a broader repaint, it
  must call `page.update()` itself.
- `state["running_version"]` is the single source of truth for "a game is
  live". Writers: `do_install_and_launch` sets it after spawn; `on_exit()`
  clears it AND resets the button (the old code never reset it — the button
  stuck on GAME RUNNING... forever). `on_version_selected()` re-paints
  "running" when the selected version is the live one, and
  `_reconcile_running_button()` (Play-tab entry) clears a claim the watchdog
  proves dead — needed because re-exec paths lose the in-process on_exit
  watcher. Any new writer must do the same or the button sticks again.
- Defense in depth (2026-09-18 round 2): `on_play_click()` re-verifies a
  running claim against the watchdog before launching (refuses a double
  launch of the same version; overlapping launches of DIFFERENT versions
  remain allowed), and a `running-liveness` daemon thread (one per process)
  self-heals a claim whose game died without on_exit firing. All three
  mechanisms must stay in sync with any change to the claim's lifecycle.

## Instance install cancellation (2026-09-22) — INVARIANT
- The Play-tab progress row carries a `progress_cancel_btn` ("Cancel",
  tooltip "Stop this install"), visible only while an install is
  cancellable. `on_cancel_install()` only SETS a flag; the installing worker
  does the abort and cleanup, so the button can never strand state.
- One `threading.Event` per version id (`_install_cancels` / `_cancel_event`),
  shared by `prefetch_version` and the Play-click `do_install_and_launch` —
  otherwise a cancel during a prefetch would just make the Play worker wait
  forever on `_install_lock`. The prefetch's noop callbacks are now a
  `_guard` that raises when the flag is set. `do_install_and_launch`
  re-checks the flag AFTER acquiring the lock (a cancel can land while it
  waits behind the prefetch).
- The abort mechanism is raising `_InstallCancelled` from the mll progress
  callbacks (`setStatus` is called before each download, so queued tasks bail
  instantly and the executor's `shutdown(wait=True)` drains fast).
  `versions.install_version` re-wraps ANY callback exception as a generic
  RuntimeError, so "cancelled vs failed" is decided from the event, never the
  exception type.
- Cancellation is DISARMED before the launch phase (`cancellable["on"] =
  False`, `state["installing_version"] = None`, button hidden). Launching is
  deliberately not cancellable — `status_cb` is also passed into
  `launch_game`.
- A fresh install cancelled before completion has its whole version folder
  removed (`core.delete_version`, only when `was_installed` was False) so it
  can't resurface as a puzzling "(incomplete)" entry; a reinstall of a
  pre-existing version is left alone (install_version already dropped only
  the jars it clobbered). A `finally` always hides the button and clears
  `state["installing_version"]`.
- `state["installing_version"]` = the launch id with a cancellable install in
  flight (not necessarily the current dropdown selection).

## Tray/session lifecycle (2026-09-18) — INVARIANT
- `_tray_runtime["controller_page"]` tracks the current session page and is
  cleared by session-end cleanup. `_tray_activate()` records Open requests
  unconditionally: Flet 0.86 can leave the page/window looking live after a
  native close, and the session loop consumes the request only after `ft.run`
  ends, so gating on that stale page reference made tray Open unusable.
- Seasonal layer defaults OFF (`seasonal_theme`/`season_pet` are False in
  `cubeon/config.py`); `CUBEON_SEASON=<season>` still pins for tests and
  screenshots.
- **Tray Quit order is load-bearing (2026-09-20)**: `_tray_quit()` must call
  `_kill_flet_client()` (and save geometry) BEFORE the rpc/friends cleanup.
  The cleanup can deadlock on native teardown; when it did, the 3s bail timer
  fired `os._exit(0)` with the flet client still mapped, leaving the reported
  "Quit leaves the window open, spinning Working…". Killing the client first
  means the window is gone no matter how the cleanup goes. Guard:
  `tools/test_ui_smoke.py` asserts the call order.
- **Startup splash (2026-09-20)**: `main()` mounts a small centered
  "Loading Cubeon" `_splash` container right after the theme is applied
  (window 360x200, `resizable=False`) and reveals it immediately, then swaps
  it for `_app_root` (`page.controls.clear()` + append + `page.update()`) once
  the full tree is built. The saved geometry (`_apply_real_geometry()`) is
  applied ONLY in `_reveal_window`, i.e. with the finished UI — never at
  startup, so the splash doesn't open full-size. The seasonal ambience uses
  the saved `_gw`, not `page.window.width` (which is the splash width during
  the build). Do NOT move the geometry assignment back before the splash.

## Minecraft screenshot gallery (2026-09-19) — INVARIANT
- Screenshots live in Cubeon's private game folder at
  `MINECRAFT_DIR/screenshots` (`~/.cubeon_minecraft/screenshots` by default),
  not the user's shared `~/.minecraft`. `cubeon/screenshot_gallery.py` is the
  single boundary for listing, bounded preview decoding, safe clipboard file
  hand-off, safe deletion, and opening that folder. The Images pane inside
  Cosmetics uses this boundary; it is selected from the Cosmetics subtab row,
  never from the top-level nav. Never pass arbitrary paths into Flet images or
  delete callbacks.
- **Gallery perf (2026-09-21)**: both hot paths are cached in the store
  module. (a) `list_screenshots()` is memoized against the screenshots
  DIR's mtime+inode (`_dir_signature`, correct because only the game + the
  delete action change the folder and nothing edits a file in place) —
  re-opening the Images pane scans once, then every open is O(1) instead of
  `Image.verify()`-ing (full file read) every PNG. (b) `image_base64()`
  renders are disk-cached in `paths.CACHE_DIR/screenshot_renders` keyed by
  source mtime + size bucket (tmp+replace write) — first pass decodes each
  screenshot once, later opens re-encode a small PNG (~0.1 ms vs ~80 ms).
  `delete_screenshot()` drops the file's cached renders (dir mtime bump
  invalidates the list). The UI (`ui/screenshot_gallery.py`) caps cache-miss
  decodes at 3 concurrent threads via `_DECODE_POOL` so the first open with
  N shots doesn't fire N full decodes at once.
- **GOTCHA (learned the hard way 2026-09-21): `paths.py` computes
  `CUBEON_HOME` from `Path.home()` and IGNORES any `CUBEON_HOME` env var —
  only `CUBEON_GAME_DIR` is env-honored.** A probe script setting
  `CUBEON_HOME=/tmp/...` silently wrote 41 "Probe" skins into the REAL
  `~/.cubeon_launcher/skins`, and running `tools/test_ui_smoke.py` un-sandboxed
  CLOBBERED the real `capes.json` (it `open(capes.json,"w")`s directly and
  never restores). To sandbox launcher-adjacent work: redirect `HOME` AND set
  `PYTHONUSERBASE=<real home>/.local` (flet lives in the user site, which
  follows HOME), or patch module attrs post-import like
  `test_screenshot_gallery.py` does. NEVER rely on `CUBEON_HOME` env.

## Relay username metadata (2026-09-17, plan step 2)
- `cubeon/friends.py` exposes `minecraft_username(value)` -> the value when it
  matches `[A-Za-z0-9_]{3,16}` (case-preserving, NO reserved-name check) else
  `''`. `FriendsClient.set_minecraft_username()` is nonblocking (bg thread)
  and replays the username on every hello.
- The worker's `names` table carries a nullable `minecraft_username` TEXT
  column (PRAGMA-guarded ALTER, no unique index — duplicate usernames are
  legal and rows stay distinct by handle/UID). T_METADATA updates write ONLY
  that column; fan-out reaches friends AND pending-request counterparts.
- `FriendsClient.roster["peer_metadata"]` is keyed by CANONICAL handle with
  `{uid, minecraft_username}` (fields absent when unknown) and is persisted
  through `atomicio.write_json` — the roster cache write was a direct
  `open(path,"w")` before, which violated the atomic-JSON invariant.
- Identity-bearing worker frames now carry `<prefix>_uid` +
  `<prefix>_minecraft_username` (from/to/peer), and roster requests/groups add
  `*_details` arrays; the legacy string arrays are unchanged.

## Social identity fixes (2026-09-17) — INVARIANT
- **S4 identity cache gapfill**: `_remember_event` now calls `_remember_metadata`
  with `fill_missing_only=True` for "from"/"to"/"peer" prefixes. The client's
  `peer_metadata` cache (authoritative, updated by T_METADATA events before
  dispatch) is mirrored unconditionally; raw friend/request detail rows only
  fill missing UID/username fields and never overwrite a value a live event
  already delivered. `_chat_seeded` dict tracks `{gen, t, attempts}` per
  conversation; `_connect_gen` bumped on reconnect marks all cached entries
  `"retry"` so gaps backfill after disconnect.
- **S6/S7 chat history retry**: `chat_payload` no longer early-returns for
  `after >= 0` without seeding. If the conversation isn't successfully seeded
  (`_chat_seeded[canon] == "done"`), a history request is triggered with
  exponential backoff via `_HISTORY_REQ_TIMEOUT` (10s). Failed/timeout
  requests increment `attempts` and are retried on the next poll. Successful
  relay replies mark the conversation `"done"` to prevent re-requesting.
- **S8 history dedupe by relay ID/envelope**: `_chat_append` returns bool
  (appended vs deduped). Deduplication uses the relay's message ID (`mid`)
  when present, otherwise a fingerprint of the sealed envelope (ciphertext) —
  NEVER the plaintext, which may legitimately repeat. `_on_dm`, `_file_own_echo`,
  and `_on_history` all pass `mid` and `envelope` so the atomic dedupe under
  `_chat_lock` covers live DMs, echoes, and backfilled history uniformly.
- **S15 sync frame pubkey TTL**: `_sync_frame` now calls `_peer_pubkey(peer)`
  instead of reading the raw cache. `_peer_pubkey` enforces `_PUBKEY_TTL_S`
  (900s), re-fetches rotated keys on expiry, and clears the cache on reconnect
  (`_on_state`). Sync frames seal with the fresh key or fall back to plaintext
  with the "open" report so the UI is never silently in the clear.
- **S13 offline invite failure**: Worker's offline reply carries a relay-allocated
  room the host never learned. `_on_call_end` now matches this case when:
  `reason == "offline"`, host is in `ringing_out` with `room == None`, and
  `peer == p.get("to")`. It assigns the relay's room to the session before
  teardown so the host is notified and the session cleans up immediately.
  Peer hangups (no `reason:"offline"`) with unknown rooms do NOT match.

## Seasonal look (2026-09-17) — INVARIANT: a palette is bound at import
- `cubeon/seasonal.py` resolves WHICH palette this launch wears, at startup,
  from the timezone (CUBEON_TZ > TZ > /etc/localtime > /etc/timezone > Windows
  `tzutil /g`) + today's date. It never touches the network. The hook lives in
  `cubeon/__init__.py` and runs BEFORE main.py binds any `from cubeon.theme
  import ...` token — because a template patches theme tokens once at import
  (see color_templates.py), a palette change is a relaunch, never a repaint.
  Don't try to make it live-switch; the Settings > Seasonal pane + the greeting
  card in main.py explain the restart instead.
- Precedence (first wins): `--color` CLI pin (marks source="pinned",
  seasonal=False) > `CUBEON_SEASON` env (pin/off/auto — auto ignores config,
  for deterministic screenshots) > `cfg["seasonal_theme"]=False` >
  `cfg["season_override"]` > timezone detection > northern-temperate default.
- Seasons are METEOROLOGICAL (Mar/Jun/Sep/Dec 1). Southern hemisphere via the
  `SOUTH_ZONES` table in `cubeon/seasonal_geo.py` (generated by
  `tools/make_seasonal_geo.py` from /usr/share/zoneinfo + iso-codes — rerun it,
  don't hand-edit the table). Tropics get wet/dry labels (spring/summer
  palettes) instead of fake autumn.
- The four palettes are ordinary templates (`templates/color_{autumn,spring,
  winter,summer}.py`, aliases --color8..11) with WCAG-AA contrast asserted by
  `tools/test_seasonal.py` (101 checks; run it for any palette change).
- Live season changes: picking a season in Settings re-skins the runtime half
  IN PLACE via `update_badge` / `update_pet` / `reflow_ambience`
  (ui/seasonal_ui.py, wired in main.py's `_season_controls_sync` and
  `_season_runtime_apply`) — badge chip, pet sprite, and weather all visibly
  swap without a rebuild; only the PALETTE waits for relaunch. `reflow_ambience`
  RETURNS a new bounds tuple — bounds are immutable tuples, so it can't be
  updated in place; callers must store the returned value in `_season_rt`.
- JVM FLAGS (cubeon/launch.py CLIENT_JVM_FLAGS): Aikar-derived client G1 set,
  applied to EVERY launch as `-Xmx{ram}M -Xms{ram}M` + flags. Deliberately
  EXCLUDES AlwaysPreTouch (kills low-RAM machines / doubles launch time) and
  G1HeapRegionSize > 16M. Constraint: Java 8–25 compatible. Two values are
  deliberately softer than the server set because a weak client CPU shares its
  cores between GC and the render thread: `MaxGCPauseMillis=200` (not 40 — a
  40ms goal makes G1 shrink young gen and run young GCs far more often) and
  `G1HeapWastePercent=5`. `-Dorg.lwjgl.util.NoChecks=true` skips LWJGL's
  per-call pointer validation. (2026-10-05)
  GOTCHA: `-XX:G1RSetUpdatingIntervalTime` is REJECTED by Java 21 (and newer) —
  it made the JVM refuse to start. Validate flag changes against a real
  `java` before shipping:
    java <flags> -cp <dir-with-T.class> T
  The heap slider is hardware-bounded already (max = detected RAM,
  recommended = half) so -Xmx can't exceed physical RAM.
- SEASON BADGE IS NOT MOUNTED (user request): `season_badge` is still built and
  synced by _season_controls_sync, but the top-bar Row no longer contains it.
  The Settings > Seasonal pane is the entry point. Don't re-add the chip to
  the bar, and don't delete the widget (its sync calls would break).
- CONTENT DIR LAYOUT: MINECRAFT_DIR is `~/.cubeon_minecraft` (Cubeon's own
  private game folder, NOT ~/.minecraft). `CUBEON_GAME_DIR` env wins over the
  default and is THE sandbox hook for content tests (set it before importing
  cubeon.paths — dirs are computed at import). Game staging folders:
  resourcepacks/, shaderpacks/ inside it; stores: global_mods/,
  global_content/ (siblings the sync never wipes).
- PER-INSTANCE CONTENT (commit ec581b9): packs/shaders use the mods model —
  global store + (version,loader) profile of links + launch-time staging
  (launch.py calls content.sync_content_to_game(mc_version, loader)).
  Signature gotcha: `list_content(type, mc_version, version_id=None,
  loader=None)` — the THIRD positional is version_id; always pass loader as a
  kwarg or you silently get [] (cost me two probe rounds).
- `.cubeon-staged.json` state files live INSIDE the staging folders — any
  test counting game-folder entries must filter dotfiles.
- Regression guard: tools/test_content_instance.py (registered in mega_smoke
  SUITES). If "packs don't change between instances" is reported again, run
  it first — it reproduces the whole bug headlessly in ~2s.
- VERSION INSTALL INTEGRITY (commit 60b3c40): mll's downloader has no
  resume/checksums. `versions.install_version` now verifies size+sha1
  post-install, removes partial jars on any failure, and
  `get_installed_versions` runs `_client_jar_problem` over EVERY entry
  (size vs manifest, zip magic) — a truncated jar shows "(incomplete)",
  never "installed". Regression guard: tools/test_version_integrity.py
  (fake mll injection via `V.mll = _Fake`). Loader profiles may have no own
  jar, but their `inheritsFrom` chain must resolve to a valid terminal base
  with cycle/depth guards. Jar selection uses folder/metadata ID, never an
  arbitrary jar. Failed-install cleanup preserves unchanged preexisting jars;
  size-only snapshots cannot distinguish same-size concurrent rewrites.
- PRECEDENCE GOTCHA: `CUBEON_SEASON` env outranks `season_override` config
  BY DESIGN. A user with the var set sees their picker pick ignored. The UI
  surfaces this via `seasonal.env_pin()` (red note in the Seasonal pane +
  snackbar on change). If "my pick reverts" is reported again: check their
  env first, then whether save actually landed on disk (config.json
  `season_override`), then the handler.
- CRITICAL DEPLOYMENT FACT: the user does NOT run this source tree. Their
  desktop entry (~/.local/share/applications/cubeon.desktop) launches
  ~/.local/opt/Cubeon/cubeon — an INSTALLED PyInstaller build. Source-tree
  work is invisible to them until rebuild + reinstall:
  `pyinstaller Cubeon.spec --noconfirm` (~4 min; dist/Cubeon is a single-file
  exe; the spec already bundles assets/ + templates/, so new pets/palettes
  ride along), then `cp dist/Cubeon ~/.local/opt/Cubeon/cubeon`.
  The pre-Sep-17 install is backed up at ~/.local/opt/Cubeon/cubeon.bak-aug31.
  On 2026-09-17 a "my changes do nothing" report was EXACTLY this: a
  month-old installed binary. Check which copy the user runs FIRST.
- Runtime half (`ui/seasonal_ui.py`): badge + pet GIF + optional ambient
  particles, all driven by ONE shared `SeasonalAnimator` thread started in
  main.py's layout section and stopped in the session-end cleanup
  (`season_animator.stop()`). Pet/ambience toggles are live (cfg keys
  `season_pet`, `season_ambience`); the palette is not.
- The pet WANDERS, not hops: `build_perch()` returns `(lane, pet_dict)`; the
  top bar mounts the clipped lane Stack (PERCH_W px) and `add_pet(pet_dict)`
  drives a rest→walk→turn state machine (fixed amble, jittered rests, idle
  hops, scale_x mirror on turn). The bar mounts the LANE; the sprite dict's
  `["ctrl"]` is what visibility/click code touches. `add_pet` still accepts a
  bare control (legacy in-place hop) but nothing in main.py uses that now.
  GOTCHA: `SeasonalAnimator._frame()` acquires the animator's non-reentrant
  lock itself — never call it while holding `anim._lock` (deadlock; the test
  suite calls `_wander`/`_frame` bare).
- Restart-to-apply: module-level `_relaunch["request"]` (threading.Event) in
  main.py. The button saves cfg, sets it, closes the window; the __main__
  session loop checks it right after ft.run returns (ghost client already
  reaped by `_kill_flet_client()`) and execv's a fresh launcher BEFORE any
  crash classification/parking. Do NOT execv from inside main() — it would
  orphan the flet client as a ghost window (see Flet 0.86 hard rules).
- The once-per-season-per-year greeting card (`main.py`, gated by
  `cfg["season_seen"] == "<year>-<season>"`, non-modal, only for onboarded
  users) must stay wrapped in try/except: a missed hello must never break
  startup.

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
  keep the zero-padded 8-digit form.
- Flet 0.86 clipboard: `page.set_clipboard` is gone. Use
  `page.run_task(ft.Clipboard().set, value)` (async service). FakePage
  harnesses lack `run_task`, so clipboard handlers must try/except.
- **Worker deploys lag code (resolved 2026-09-20, but the pattern repeats).**
  The 8-digit-ID repo code sat undeployed for a day: production still ran the
  12-digit worker, so every add-by-ID failed with "No Cubeon user with ID"
  (the /uid/ lookup 404'd any 8-digit ID). Deploy is
  `cd worker && npx wrangler deploy -c wrangler-friends.toml`. Verify the
  deployed shape with `curl <base>/uid/00000001` — 200 = current, 404 with
  `/uid/000000000001` = 200 means the stale 12-digit worker is live.
- Chat identity labels use validated Minecraft usernames with the 12-digit
  Cubeon UID visible separately. Auto-minted relay handles are routing keys,
  never display-name or tooltip fallbacks; missing metadata uses UID/Player.
- **Two-launcher testing:** `tools/launch_sandbox.py <name>` boots an isolated
  second launcher (fresh HOME → fresh friends account; `--list`/`--wipe`).
  MUST set `PYTHONUSERBASE=<real home>/.local` or flet can't import. Bridge
  uses a random port + token, so instances coexist. Default shares
  `~/.cubeon_minecraft` via CUBEON_GAME_DIR (no re-download); `--isolated-game`
  gives the sandbox its own game dir.
- Chat identity card (ui/chat_tab.py): profile avatar (PFP via
  `cubeon.profile.get_profile_picture_path`) + roster `you_minecraft_username`
  + the 12-digit UID as a secondary line with a copy button. Self metadata
  comes from the latest live game's captured username, otherwise the committed
  launcher username (`watchdog.effective_username`), not an editable field.
  Friends/request labels use `FriendsService.peer_metadata` / `peer_label`;
  callbacks, history, and unread markers remain keyed by relay handle.
  PFP/self/peer metadata participate in refresh signatures. Legacy rename
  bridge/service entry points are immutable guards directing users to the
  launcher username setting; `/friends` retains rich request/self metadata.

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
  ACTION FOOTER (PLAY right at 280px).
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
- **Minekube badge = credit card (2026-09-21):** the DNS icon in Settings
  header no longer teleports to the web. Clicking opens an in-app AlertDialog
  (`_open_minekube_info` in main.py) explaining WHY Cubeon backs Minekube —
  they're OPEN SOURCE and give EVERYONE (not just Cubeon) a free public
  address for a home-hosted server, and Cubeon's server sharing runs on their
  network — with a "Open their website" FilledButton (webbrowser.open
  connect.minekube.com, snackbar fallback) and a Close button. Tooltip reads
  "We back Minekube - open source, free addresses". The relationship is
  Cubeon supporting Minekube, NOT Minekube sponsoring Cubeon — keep the copy
  pointing that way.


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
| `p2p.py` | P2P worlds: STUN + relay fallback, mod/asset sync, teardown. INVARIANTS (2026-09-17 wave 1): `_mod_target()` (basename + .jar + realpath containment) is the ONLY way a peer-named jar becomes a file — used by BOTH the download path and the cache-hit path; `_asset_target()` enforces the extension allowlist + symlink-safe containment receiver-side; `_accept_chunk()` bounds seq/total (strict ints, encoded-size cap, base64 validate) — NEVER allocate from peer-declared totals; STUN attrs pad `(-attr_len) % 4`. ModSync/AssetSync have cancel()/journal for cancel-with-rollback and an on_error callback the service wires to session failure. |
| `worldgate.py` | The OPTIONAL password on a P2P LAN world (in-memory only, dies with the session). Host arms it from the mod's password prompt; the joiner proves it via HMAC(PBKDF2(pw,salt), nonce) over the E2EE signal channel - the p2p_offer (LAN port + relay token) is withheld until a proof lands, so the gate is real, not decorative. GATE SIGNALS ARE E2EE-SEALED (2026-09-17): friends_service `_send_gate`/`_open_gate` wrap every gate_* frame in the peer's DM envelope; unsealed/tampered gate signals are refused, and every transport path (`_send_p2p_offer`, `_switch_to_relay`, `_run_host_punch`) checks `_transport_allowed` (per-session `gate_required`/`gate_authorized`) BEFORE creating a transport. Harnesses firing gate frames must seal them (see `gate_build`/`gate_signals` in test_friends_service.py). |
| `server.py` | Paper server hosting: install (Fill v3 API), start/stop, properties, orphan detection. |
| `minekube.py` | Public address tunnels: finds/installs Connect plugin, endpoint config. |
| `modpacks.py` / `mods.py` / `global_mod_cache.py` | Modrinth/CF packs; per-profile mods LINK into one global store (`~/.cubeon_minecraft/global_mods`) — never copy jars between profiles. |
| `cubeonfriends.py` | Which Friends jar goes into which profile (brackets), injected at launch. `mod_stamp()` = jar freshness fingerprint. |
| `perf_mods.py` | FPS boost: fetches the client perf suite (`PERF_MODS`: Sodium, Lithium, ImmediatelyFast, EntityCulling, MoreCulling, BadOptimizations, Krypton, ThreadTweak, Dynamic FPS) into a Fabric/Quilt profile at launch when `client_mod_enabled` AND `perf_mods_enabled`. `_present()` dedupes by slug/name/id/filename; skip-if-present (no auto-update); best-effort, never raises. |
| `game_options.py` | Frame-rate unlocker: flips ONLY `enableVsync`→false and `maxFps`→260 in `MINECRAFT_DIR/options.txt` (atomic, idempotent, no unknown keys). Never rewrites any other game option. |
| `launch.py` | `launch_game()` — injects CSL + friends jar + perf suite + frame-rate unlock, syncs mods, launches MC. `CLIENT_JVM_FLAGS` + matched `-Xms/-Xmx`. Requires mc_version/loader, no silent defaults. |
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
python3 tools/test_seasonal.py           # 98: season tables + precedence + palette AA contrast
python3 tools/test_mega_smoke.py        # deep gate: syntax + imports + contracts + control flow + headless runtime
python3 tools/app_driver.py explore     # AI driver: use the app headless, JSON error/coverage report (`fuzz`, `script`, `shots`)
python3 tools/test_friends_service.py   # 213: service + bridge contract + identity + unique rename + chat tab
python3 tools/test_friends.py           # 37: relay client + worker parity
python3 tools/test_mod_bridge.py        # 137: reads Bridge.java, asserts launcher serves it
python3 tools/test_mod_compile.py       # mod source compiles vs the stub API subset
python3 tools/test_mod_matrix.py        # 68: brackets/jar routing
python3 tools/test_capes.py             # 14: flexible capes + CSL sync
python3 tools/test_ui_smoke.py          # 148: tab builders build, invariants hold
python3 tools/test_invites.py           # 127: Minekube/tunnel flows
python3 tools/test_modpacks.py          # 66: pack installs
python3 tools/test_mod_store.py         # 27: global mod store
python3 tools/test_net.py               # 19: download retry/resume/cap + updater
python3 tools/test_production.py        # 51: watchdog
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
- **Crash reporting REMOVED (2026-09-20, user request)**: `cubeon/crashreport.py`
  and the Settings > Privacy section are gone. Uncaught exceptions are still
  written to the rotating log by `logging_setup._install_excepthooks()`, but
  nothing is ever sent anywhere. `setup_logging()` no longer takes a crash_cfg.
  Do NOT reintroduce a network crash reporter or a Privacy settings pane.
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

- **Cosmetics-tab open freeze (fixed 2026-09-21):** `refresh_profile_tab()` /
  `rebuild_skin_section()` (main.py) used to call `build_skin_section()` from
  scratch on EVERY visit — measured ~130-150 ms of control construction plus a
  full subtree re-serialization to the client (the "freezes for a moment when I
  open Cosmetics" report). The section is now CACHED in
  `skin_section_container` and rebuilt only when its inputs change: the key is
  `(version_dropdown.value or cfg["last_version"], state["mod_loader"])` —
  exactly the two values the rebuild exists to track (the CSL status tooltip).
  The section's own handlers (upload/use/delete) refresh their lists in place,
  so nothing goes stale between visits; `_THUMB_MEMO`/`_IMG_MEMO` now survive
  across visits too, so thumbs are instant instead of placeholder-pop. Do NOT
  revert this to a per-visit rebuild; if a "stale cosmetics" report arrives,
  check the cache key inputs first.
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
- The site lives in `web/` and is deployed on **Vercel at `cubeon.vercel.app`**
  (project root = `web/`, so `web/vercel.json` + `web/_redirects` are the live
  route tables and `web/api/*.js` are the serverless functions). Still NO build
  step. Pages sharing `web/assets/site.css` + `web/assets/site.js`: `index.html`
  = landing (story), `download.html` = the files, `help.html` = the manual, plus
  `404.html` and the legal pages (cookies / licenses / privacy / refunds /
  terms). They cross-link by clean route (`/download`, `/help`, ...) and mark
  the current page with `aria-current="page"` (the old `docs.html` name and the
  `download.html#files` / `docs.html#faq` fragments are GONE). `site.js` is
  shared verbatim: every block bails out when the page lacks its elements (the
  sky canvas + roster only exist on the landing page).
- **EVERY page must load `assets/site.js`** - the page itself is the wiring, and
  a page that forgets the tag loses the counter, the cookie note and the mobile
  menu while still looking fine in review. `index.html` shipped exactly that way
  until 2026-09-22: it kept an inline copy of the old OS-detect + FAQ behaviour
  and never loaded site.js, so the landing page (the one with the download
  buttons AND the counter) showed nothing. The landing-only pane switching
  (`html.js .pane` hidden until a pane carries `.on`, the "Not your system?"
  buttons) now lives in site.js's `markSystem` block. `tools/test_web_download_count.py`
  now fails if any `web/*.html` lacks the tag or keeps a second copy of a handler.
- **Never pair a `/page` → `/page.html` redirect with `cleanUrls: true`** (both
  `web/vercel.json` and the repo-root one): the host already serves the page at
  the extensionless path and rewrites `/page.html` back to `/page`, so the rule
  becomes ERR_TOO_MANY_REDIRECTS. That shipped for `/download`, `/help` and
  `/404` (2026-09-22, removed - the legal pages proved cleanUrls alone works).
  Only the `/<os>download` release-asset routes belong in the redirect list; a
  test asserts no such loop and that all four asset routes survive.
- Every SITE download is a plain anchor to a clean route — `/windowsdownload`,
  `/linuxdownload`, `/linuxdeb`, `/linuxsetup` — which Vercel 307s to the GitHub
  release asset named in `web/vercel.json`; the old `../dist/<file>` hrefs are
  gone (`dist/` is gitignored and absent from the deploy). The public UI offers
  the Windows installer and the Linux trio; macOS is an honest "not available
  yet" card. Byte sizes printed in the cards are hand-written — re-check them
  after any rebuild.
- **The GitHub repo is PRIVATE** (anonymous `github.com/Shadow-457/Cubeon` → 404,
  and anonymous `releases/latest/download/<asset>` → an auth wall too). Visitors
  get the files through the `cubeon-downloads` Worker instead — see the direct
  downloads bullet below. It is also why the page cannot ask GitHub anything
  directly.
- **Release download count on the site (2026-09-22, v2)**: `index.html` and
  `download.html` carry `<p class="download-count" data-download-count hidden>`;
  `site.js` shows the SHARED number of download-button presses for everyone: on
  load it reads Abacus (`https://abacus.jasoncameron.dev/get/cubeon-site/downloads`,
  an open-source cookieless counter) and on a press it calls `/hit` with
  `keepalive: true` so the +1 survives the jump to the release file. A global
  count cannot live in a browser, so this is the one outside request the site
  makes - cookies.html and privacy.html disclose it (a test enforces that they
  do). A failed lookup hides the line; 0 is shown as a real 0. The v1
  GitHub-count plumbing (web/api/download-count.js, download-count.json,
  the scheduled workflow, tools/refresh_download_count.py) was REMOVED the same
  day at the owner's direction - recoverable from git history around commit
  `ddc5374`. Guard: `tools/test_web_download_count.py` (real site.js in Node on
  a DOM stub, zero network).
- **Direct downloads (2026-09-22)**: the repo is PRIVATE, so GitHub's release
  URLs are an auth wall for visitors and signed asset URLs minted from a
  session expire within the hour (one was briefly committed to web/vercel.json
  by mistake). The `cubeon-downloads` Worker (worker/cubeon-downloads.js +
  wrangler-downloads.toml) holds a read-only `GITHUB_TOKEN` as a Worker secret
  and streams the latest release's four installer files straight out with
  `Content-Disposition: attachment`; web/vercel.json + web/_redirects point the
  four `/<os>download` routes at it. The counter's ROUTES in site.js, the
  vercel.json sources and the Worker's FILES list must stay in lockstep - a
  test asserts all three agree.
- The waitlist form + "In line" counter are gone from the site (the
  `worker/cubeon-waitlist.js` Worker still deploys but has no caller). JS only
  stars the button/card matching the visitor's OS with `.rec` — with scripting
  off both pages are still fully usable. Class names that came with the rename:
  `#oven` → `#release`, `.oven*`/`.trays`/`.tray*` → `.board*`/`.tiles`/`.tile*`,
  and `.wl*`/`.countline`/`.countbar` → `.dl-hero*`/`.dl-note`/`.dl-*`.
- `@font-face` in `site.css` must stay `url('fonts/Minecraftia-Regular.ttf')` —
  CSS-relative, NOT `assets/fonts/...` (that path 404s now that the font is
  reached through the stylesheet instead of the page).

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

## Mod bridge hardening (2026-09-19) — durable facts
- `Bridge` is the only localhost transport. It validates the token file's port
  and header-safe token, fingerprints both file mtime and size, invalidates a
  token after HTTP 401, accepts only 2xx `{"ok": true}` action responses, and
  caps response parsing at 1 MB. Chat/sync query values must stay URL-encoded.
- A temporary `/status` failure retains the last session for two polls, then
  clears it; `/friends` remains the liveness check. Event cursors accept only
  finite non-negative integers, while a valid lower cursor is treated as a
  launcher restart so notifications recover after the launcher restarts.
- `CubeonClientScreen` owns a stable notice callback and clears it with
  compare-and-set on close. An old screen therefore cannot silence a newer
  screen during a close/reopen transition; Sync teardown uses the same
  expected-owner guard. The bridge poller resets its own thread handle in
  `finally`, so a later screen can restart it after an interruption or
  unexpected failure.
- Guards: `tools/test_mod_bridge.py` / `mod/tools/SelfTest.java` cover 8-digit
  IDs, port validation, HTTP status handling, cursor poisoning, and malformed
  chat sequences; `tools/test_mod_compile.py` covers the cross-version UI API.

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
- **Browse paging is lazy, one page at a time (2026-09-20)**: both the Mods
  tab (`ui/mods_tab.py`, BROWSE_PAGE_SIZE=5, MAX_BROWSE_PAGES=20) and the
  Modpacks tab (`ui/modpacks_tab.py`, PAGE_SIZE=5, MAX_PAGES=10) advertise a
  full page count but fetch only the requested page — the pager's Next/Prev
  triggers a fetch for that offset, not a 20-page prefetch. `browse_state`
  holds the page cache; a page already in `results` renders without refetching.
  `offset` is part of every search cache key in `cubeon/mods.py`,
  `cubeon/content.py`, and `cubeon/modpacks.py` so pages cache independently.
  Modrinth's per-request cap is 100 (`limit`); a SHORT page clamps
  `total_pages` down (the API over-reports count for filtered queries). The
  curated no-category mod list ignores `offset`, so it sets
  `browse_state["paged"] = False` and slices client-side. Modpacks fetch
  Modrinth + CurseForge in parallel per offset and merge via
  `merge_modpack_hits`; keyless cfwidget returns [] for offset>0.
- **Installed content shows real thumbnails (2026-09-20)**: a bare `.zip`
  carries no Modrinth identity, so `download_content()` records the browse
  hit's `icon_url`/`slug`/`title` (via `content.remember_content_meta`) in the
  `content_meta.json` sidecar under `CUBEON_HOME`, and `list_content()`
  re-attaches it (`_attach_content_meta`); `delete_content()` calls
  `forget_content_meta()` so a reused filename can't inherit stale art.
  Modpacks do the same through their `_modpack.json` meta: the install paths
  take an `icon_url` kwarg (`install_modpack_from_url` /
  `install_modpack_from_cf` -> `_install_from_zip`) and `build_installed_row`
  draws `icons.src(meta["icon_url"])`. No recorded art (hand-dropped file) ->
  keep the quiet type glyph, never a broken image.
- **Shader requirement notice is state-aware (2026-09-20)**: the Shaders view's
  "install Iris/Sodium/OptiFine" banner (`shader_notice`) shows only while the
  requirement is actually missing — `shader_requirement_installed()` scans
  `core.list_mods()` display names for "iris"/"optifine", so installing the
  loader clears the notice on the next `refresh_mods_list`.
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
  no `ft.margin.only/.symmetric` — use `ft.Margin(l, t, r, b)`. "Playing
  since" reports the full date (`%b %d, %Y`), not just month+year.
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
  - **optimistic sends + scroll + emoji (2026-09-20)**: pressing Enter shows
    the bubble IMMEDIATELY (dim, "Sending…"); `_do_send` clears the composer
    before `send_chat` runs (it blocks ~1s on the peer-pubkey lookup). The
    echo-filed line REPLACES its pending bubble by FIFO text match
    (`_append_messages`); a refusal (or 12s silence, `_sweep_pending`) turns
    it red "Couldn't send". Auto-scroll: `auto_scroll=False`, `_stick["at_end"]`
    from `on_scroll` (`extent_after < 48`); `_stick_bottom()` only follows
    when at end (or forced on open) via `page.run_task(transcript.scroll_to,
    -1)` — scroll_to is async and requires auto_scroll=False. Emoji picker:
    `emoji_panel` (32 literal emojis, no plugin) toggled by `emoji_btn`,
    hidden on select/send/clear.
  - **chat conveniences (2026-09-21)**: (a) composer DRAFTS survive friend
    switches and tab closes within the session — `_drafts` keyed by canon
    friend, saved on every keystroke (`on_change`), restored in `_select`,
    cleared on send/remove. (b) `_jump_row` "Newest" pill visible only while
    scrolled up (`_stick`), click = `_stick_bottom(force=True)`. (c) bubbles
    are click-to-copy (`_copy_message` via the Clipboard service; full date
    "Mar 3, 2026 · 14:23" on hover — `_full_date`). (d) the clock line is
    GROUPED: only the first bubble of a same-side run or day shows it
    (`with_time` in `_append_messages_inner`); roster stamps use
    `_short_stamp` ("14:23" today, "Mar 3" older). (e) `find_field` filters
    the Friends rail client-side over the last roster snapshot (no service
    query per keystroke). All pure UI — no protocol changes.
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
- **FPS boost (client perf suite)**: NO Settings toggle (the user explicitly
  asked for it removed 2026-09-11 - don't add it back). It rides the existing
  "Cubeon extras in-game" toggle: when `client_mod_enabled` is on (and the
  config-only `perf_mods_enabled`, default True, is on) and the loader is
  Fabric/Quilt, `cubeon/launch.py` calls
  `perf_mods.ensure_installed(mc_version, loader)` before `sync_mods_to_game`,
  which fetches a hand-picked client FPS suite from Modrinth (`PERF_MODS`: a
  `(slug, project_id, label)` table — Sodium, Lithium, ImmediatelyFast,
  EntityCulling, MoreCulling, BadOptimizations, Krypton, ThreadTweak,
  Dynamic FPS) into the profile exactly like a user-installed mod.
  `perf_mods._present()` matches slug/display_name/project_id/filename so a
  manual jar is never duplicated (duplicate Sodium = crash). Best-effort: no
  build/offline/load error is reported in the return dict, never raised.
  Sodium stays first because it is the load-bearing renderer.
  **Skip-if-present, no auto-update**: a found mod is never re-fetched (so a
  hand-pinned version is respected); this is why an old Sodium can linger.
  (2026-10-05: widened from Sodium+Lithium only, because culling/per-frame
  mods are what actually lift a CPU-bound PvP client.)
- **Frame-rate unlock (cubeon/game_options.py)**: adding mods only raises what
  the machine CAN render; Minecraft's own `options.txt` will still read 60 (or
  ~30, Vsync halving) if `enableVsync:true` / a low `maxFps`. This module flips
  EXACTLY those two keys (`enableVsync:false`, `maxFps:260`, vanilla's top
  slider) on the launch path, atomically and idempotently, and touches NOTHING
  else (render distance / graphics / packs / shaders stay the player's choice —
  same rule as content.py). Only keys already present are changed, so an older
  options.txt without them is not given unknown keys. Called in
  `launch_game` right after `perf_mods.ensure_installed`, gated by the same
  `perf_mods_enabled`. The game is not running yet at that point, so it cannot
  race the game's save-on-exit.
- **Client JVM flags**: `cubeon/launch.py` `CLIENT_JVM_FLAGS` (G1GC,
  MaxGCPauseMillis=200, ParallelRefProc, DisableExplicitGC, G1NewSize/Reserve,
  G1HeapWastePercent=5, `-Dorg.lwjgl.util.NoChecks=true`) are appended to every
  launch's `jvmArguments`, and `-Xms` now equals `-Xmx` (no mid-game
  heap-growth stutter). Deliberately lighter than the server's Aikar set
  (`HIGH_PING_JVM_FLAGS`); flags chosen to exist on Java 8–25.
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
- **"Update game version" REMOVED (2026-09-20, user request).** The Play tab
  button, its `on_update_version` handler, the `_newest_release_key` helper and
  the `all_online_options` cache are all gone; test_ui_smoke section 6b was
  deleted with them. Changing/selecting a version now happens ONLY through the
  version picker dialog - nothing auto-jumps the selection to the newest
  release. Don't reintroduce it without the user explicitly asking.
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
- **Windows-build verification recipe (2026-09-15)**: `wine
  /home/<user>/winpython/py311/python.exe -m PyInstaller ...` works with a
  plain UNIX path - no `Z:\...\` escaping needed, which makes the command far
  easier to run from a shell/agent (the double-backslash form is what silently
  broke earlier attempts). The wine build mirrors `packaging/build_windows.py`
  but bundles only `mod/brackets.json`, not the whole `mod/` dir (verified
  against the produced `_internal/`).
  **A frozen Windows launcher keeps its state in the WINE PREFIX, not the
  Linux home**: `~/.wine/drive_c/users/<user>/.cubeon_launcher/` holds
  `cubeon.log` and the `ui_painted_ok` marker - that is where to prove a
  Windows build actually booted AND painted (a running frozen build also emits
  endless `d3d11_swapchain_Present1` fixme lines, i.e. frames are rendering).
  Checking Linux `~/.cubeon_launcher/` for a Windows run tells you nothing.
  The CLI forms of the two Windows scripts are `packaging/build_windows.py`
  (onedir -> zip) and `packaging/build_windows_single.py` (onefile); both now
  carry `--collect-all minecraft_launcher_lib`. Bundling only
  `mod/brackets.json` instead of the whole `mod/` directory is equivalent
  (build_appimage.sh does exactly that and the app runs fine), but note an
  ad-hoc `--name Cubeon-single` run leaves a stray `Cubeon-single.spec` in the
  repo root - delete it, or invoke the script, which renames its output to
  `dist/Cubeon-Windows-x64-single.exe` for you.
- **Windows distribution choices (2026-09-20)**: `build_windows_single.py`
  emits a portable onefile EXE; it does not create shortcuts. For an actual
  per-user Windows app installation, first build the onedir package with
  `build_windows.py`, then run `packaging/build_windows_installer.py`. That
  wrapper uses native `makensis` or NSIS's `makensis.exe` under Wine and
  produces `dist/Cubeon-Windows-x64-Setup.exe`, which installs to
  `%LOCALAPPDATA%\\Cubeon`, creates Start Menu/Desktop shortcuts, and registers
  an uninstaller without administrator rights.
- **GOTCHA: artifacts go stale silently if you edit sources mid-build.**
  PyInstaller snapshots module sources at ANALYSIS time (~20 s in), so an edit
  made after that is NOT in the bundle even though the build runs for minutes
  more and still says "Build complete". Verify with `stat -c %w` (birth) on the
  build log vs. the newest source mtime, or just rebuild after editing.
  Grepping a built exe for a NEW Python symbol does not work as a check (the
  PYZ is zlib-compressed and the name matches nothing) - use packed data-TOC
  names such as `minecraft_launcher_lib`, which ARE greppable.
- **GOTCHA: `dist/Cubeon` is a contested name.** build_appimage.sh does
  `mv dist/Cubeon/* AppDir/usr/bin/` then `rmdir dist/Cubeon`, so the LINUX
  PyInstaller output must own that path. A wine/Windows onedir build lands on
  the SAME name and gets silently absorbed + deleted by the next AppImage
  build. Keep the Windows onedir as `dist/Cubeon-Windows-x64/` (matches the
  zip name) before running build_appimage.sh; the zip is the durable artifact
  anyway.
- **Modpack install progress, two phases**: `install_modpack_from_url()` /
  `install_modpack_from_cf()` download the pack ARCHIVE first (tens of MB, size
  unknown to the caller) - that phase reports its own whole-percent through
  `_archive_progress_status(prefix, status_cb)` fed to `_download_to`'s
  `progress_cb` (`"Downloading modpack... 42%"`), then `_install_from_zip()`
  drives the real bar via `progress_cb`/`max_cb` with `status_cb` giving
  `"Downloading mods... 12/345"`. `ui/modpacks_tab.py`'s `status_cb` repaints
  the status line + bar on EVERY call, so anything feeding status_cb must
  coalesce to whole percent (net throttles to >= 33 ms / >= 1% on top of that).
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

- `web/` is the site sharing `web/assets/site.css` + `web/assets/site.js` (no build step): `index.html` (landing), `download.html` (the binaries, clean routes to release assets — see the web bullets above), `help.html` (the manual), plus `404.html` + the legal pages. `.btn` must stay `display:inline-block` — it is applied to `<a>` tags too, and inline padding overlaps sibling text. Fonts are Google-hosted Fredoka + local `web/assets/fonts/Minecraftia-Regular.ttf` (@font-face lives in `site.css`, so its url is `fonts/...` — page-relative paths 404 there; Minecraftia ONLY for h1-h3/.brand/.btn/.q-a, line-height ~1.12 — illegible <16px, keep Fredoka for body); images lazy-swap from `/tmp`-independent `web/assets/` paths.

- `ui/skin_tab.py` (Profile > Skin/Cape panes) has NO browse/gallery area anymore (removed 2026-09-14): each pane is preview + installed card grid + upload CTA. `cubeon/gallery.py` survives only as core bookkeeping (`forget_file` in delete flows) + its tests; do not re-add library browsing without asking.

## Content compatibility + the unified doctor (cubeon/packformat.py, cubeon/doctor.py)
- **packformat.py** is the single source of truth for "will the game accept
  this file?": `pack_verdict(zip, targets)` for resource packs (pack_format /
  supported_formats / min-max keys, nested-wrapper and corrupt-zip detection)
  and `shader_verdict` (shaders/ folder structure). `repair_pack` widens the
  declared range to cover the installed versions — it NEVER invents a format
  for packs that declare none, and `_rewrite_zip` is temp-file + os.replace
  (a crash mid-repair can't leave a half-written pack).
- **doctor.py `run_doctor(mc, loader, auto_fix, include=...)`** is the ONE
  entry point covering mods (delegates to mods.mod_doctor), resourcepacks,
  shaders, modpacks (marker-vs-profile) and server plugins. Sections are
  independent; `include=` scopes a run. Report contract: `{checked, problems,
  fixed, unfixed, sections}` per-entry keys `section/kind/item/detail/fixed/fix`.
  Unfixable things (corrupt zips, gutted packs) are REPORTED, never deleted.
- **Browse filtering:** `content.py` drops search results whose file list has
  no build for the selected MC version BEFORE they render, and `get_content_download`
  re-checks at download time (defense in depth). Installed-but-incompatible
  items still show — with a badge + one-click doctor fix.
- **Launch pre-repair:** `launch.py` calls `run_doctor(..., include=("mods",
  "resourcepacks", "shaders"), check_online=False)` before every game start —
  best-effort, a failed check must never block playing.
- Suite: `tools/test_content_doctor.py` (88 checks, offline, sandboxed home).

- **Folder packs are first-class (2026-09-16):** packformat verdicts/repair,
  the doctor's content scan (`_iter_content_packs`), and
  `content.list_content`/`delete_content` all accept UNZIPPED pack
  directories (the game loads those too). Dir repair = atomic pack.mcmeta
  write + `_flatten_dir` (refuses to merge over an existing root entry).
  list_content items carry `folder: True`. CONTENT_TYPES keys are singular
  ("resourcepack", "shaderpack") - list_content('resourcepacks') raises.
  GOTCHAS hit while testing: run_doctor's auto_fix defaults TRUE (a detect
  probe must pass auto_fix=False); test fixtures that install fake versions
  leak their pack formats into every later section's targets - clean them up.

## Polish surfaces (cosmetics/settings/stats/server)
- ui/skin_tab.py renders card thumbs LAZILY (one worker per refresh batch,
  mtime-skipped; _THUMB_MEMO closure state) - never call _render_thumb on the
  UI thread. Big previews are single-flight off-thread. Upload handlers park
  their button while working.
- ui/stats_tab.py refresh_stats: milestone block is sync (1 JSON read); the
  directory-scan counters run on a worker guarded by _stats_gen. Tests must
  not expect scan counters synchronously after refresh_stats().
- settings persist on on_change_end (RAM) / on_blur/on_submit (fields), not
  per tick.
- Onboarding (_onboard_finish) publishes the username via the shared
  _publish_username synchronously - do not reintroduce a debounced fire there.

## Hats (REMOVED 2026-09-16)
Hats are gone: cubeon/cosmetics.py deleted, no cosmetic_hat config key, no
hat/unlock code anywhere. cubeon/milestones.py is now ONLY the activity-stats
store (seconds_played, sessions_hosted, friends_count_high, first_seen_at in
milestones.json + play_session.json crash-survival) - the Stats tab reads it.
The base-skin composer lives in cubeon/skins.py (compose_skin: active skin or
built-in default Steve) - vanilla players still publish a sheet so the shared
Cubeon cape resolves.
- ui/mods_tab.py installed rows: toggle/delete handlers are guarded and report
  through installed_status; mod delete re-renders the browse page. Local
  "Install from file" runs on the cubeon-local-mod-install worker with the
  button parked - never call core.install_local_* on the UI thread. The
  slug->icon worker repaints mods_list_view only, never the full page.
- Gotcha: test_ui_smoke source-pins read raw source; avoid the literal
  "page.update()" in comments inside pinned functions (it trips the pins).
