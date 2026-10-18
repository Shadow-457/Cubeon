# Smooth animations, the notify tool removed, and real OS notifications (Phase 7)

Three things happened in this session, in this order. The first two were
reactions to the user; the third was the work that was actually planned.

## 1. "the animations made it look stucky buggy and not smooth gng"

The Phase 4 commit (`74b728d`) animated things the wrong way. Three real causes,
all mine, all in `main.py` + `ui/settings_tab.py` (`f06875b`):

| # | The bug | The fix |
|---|---|---|
| 1 | The top-bar underline animated its **real `width`** (0↔24). The column sizes to `max(icon, underline)`, so every frame resized the button and shifted the whole centred nav row a pixel or two. That jitter *was* the stutter. | `width` pinned at 24 forever; the GROW is now a **paint-only `scale_x` 0↔1, centred** (`ft.Scale` + `animate_scale`). |
| 2 | The tab content **cross-fade came back** at 170ms. Rejected twice now (220ms in the 2026-09-09 pass read as "sloppy"), and two live tab trees animate at once. | `TAB_FADE_MS = 0`. Do not try a third time. |
| 3 | The Account panel dipped to `scale_y=0.04` on a 30ms timer and then settled, and the Settings pane faded — **two flushes plus a visible frame** per click. | The panel is **mounted already squashed**, so ONE write unfurls it (close re-squashes for next time). The pane fade is **deleted**; the RAIL tint/icon animation *is* the sidebar motion and it is one flush. |

**The rule that replaced the "two-update" trick: ONE FLUSH PER GESTURE.** Make
the resting value part of the BUILD and animate with a single write. If a
gesture needs a `threading.Timer` in the middle, the user will see it as stuck.

`f06875b` also added **Settings → Cubeon Web** (`https://cubeon.vercel.app`,
`CUBEON_WEB_URL` overrides), which was the open follow-up from the Phase 4 note.

## 2. The owner-notification tool is gone (`7827ede`)

User: *"security flaw ... anyone can fork my repo and just send spam ... remove
it cleanly"*. Removed, not disabled:

- deleted `cubeon/notify.py`, `notify/` (the `python notify` CLI),
  `worker/test-notify.mjs`, `tools/test_notify.py`;
- `git diff 2296ecf -- worker/` is **empty**, i.e. the Worker route, the KV
  binding docs and the `NOTIFY_TOKEN` secret docs are back to their exact
  pre-feature bytes;
- targeted removals from `main.py` (the startup poll hook),
  `tools/test_mega_smoke.py` (`SUITES`) and `agents/docs/module-map.md`, because
  those files also carry Phase 4 work.

Net diff vs `2296ecf` is now only the animation + Cubeon Web work. **Lesson: this
repo should not ship a broadcast surface into every running launcher.** If a
future agent wants in-app announcements, they need a different trust model, and
they should ask first.

## 3. Phase 7 — local OS notifications (`cubeon/osnotify.py`)

Deliberately local: **no server, no push, no account, nothing sent anywhere.**
It shells out to the platform's own notifier and gives up quietly if there
isn't one.

- Windows: `winotify` if importable, else a PowerShell `ToastNotification`
  (both via `winproc.hidden` — a console flash is exactly what winproc exists to
  prevent). Linux: `notify-send`. macOS: `osascript`.
- **Seven kinds, one Settings switch each** (`ui/settings_tab.py` builds the rows
  straight from `osnotify.KINDS`, so a switch can never drift from a kind):
  `instance, mod, modpack, resourcepack, texturepack, friend, update`.
  Config keys `notify_<kind>`, default ON. Plus a "Send a test notification"
  button (`force=True`, because a switched-off kind would make it look broken
  exactly when you're debugging).
- **A texture pack IS a resource pack** in modern Minecraft, so the launcher's
  real third content type (`shader`) rides on the `texturepack` switch via
  `osnotify.content_kind()`. Worth knowing before "fixing" it.
- Hooked at: `main.py::prefetch_version` (version installs are **invisible** —
  background downloads), `ui/mods_tab.py`, `ui/modpacks_tab.py::_end_install_ok`,
  `cubeon/friends_service.py::_on_presence` (False→True only), and startup via
  the previously-unconsumed `cubeon/updater.check_in_background` (marker
  `osnotify_last_update`, so a restart doesn't re-announce the same release).
- "Most-talked-to friend" = `osnotify.top_friend({name: count})` fed from the
  per-conversation history `FriendsService` already keeps. **No history at all
  means stay quiet** — the ask was one friend, not the roster.
- `notify()` never blocks and never raises: the real send runs on a daemon
  thread (both `notify-send` and PowerShell take 100–300ms to start), identical
  `(kind, title)` inside 1.5s collapses, and `CUBEON_OSNOTIFY_OFF=1` kills the
  module outright.

## Verified

- `tools/test_osnotify.py` — **62 passed, 0 failed** (new, in `SUITES`). Fully
  offline: no toast, no subprocess, no socket. §9 source-pins the module against
  importing any network client or flet; §10 pins the Settings wiring.
- `tools/test_ui_smoke.py` **223/0**, `tools/test_startup.py` **25/0**,
  `tools/test_version_ui.py` **22/0**, `tools/test_mega_smoke.py` **20/0**,
  `tools/test_friends_service.py` **372/0**, `tools/test_modpacks.py` **70/0**.

## NOT verified / still open

- **No human has seen a toast fire.** `available()` and `backend_name()` are
  exercised with fakes; the first real install-finished toast is unobserved.
  Try the Settings test button.
- The version-install toast rides `prefetch_version`, i.e. a *background* install.
  If Play is clicked before the prefetch finishes, the visible install path is
  the one that runs and it does **not** notify (deliberate: Play launches the
  game immediately, so a toast there would be noise).

## 4. Phase 3b — the HUD is renamed to the Cubeon Client (`c96cd85`)

The last of the absorbed mod's old name, from the user's original brief ("rename
that keyhud everywhare to cubeon client").

- **Package `dev.keyhud.client` → `com.cubeon.client.hud`.** Not
  `com.cubeon.client`, because the api overlays already define
  **`com.cubeon.client.CubeonClient`** (the mod entrypoint) and a HUD class of
  that name in the same package is a duplicate class. Hence the `hud`
  subpackage and the `CubeonHud*` class names.
- Classes: `CubeonHudClient`, `CubeonHud`, `CubeonHudKeybinds`,
  `CubeonHudMenuScreen`, `CubeonHudConfig`. `MoveOverlayScreen` and `PingProbe`
  never had the name.
- **`MOD_ID` is `"cubeon-client"`** — and it *drives* the translation keys, so
  the keybind category is `key.category.cubeon-client.main` and the key is
  `key.cubeon-client.open_menu`. The rest of the strings are `cubeonclient.*`
  and must match `assets/cubeon-client/lang/en_us.json` exactly.
- **Asset namespace** `assets/keyhud` → `assets/cubeon-client` (where the font
  already lived). **26.x mixin config** `keyhud.client.mixins.json` →
  `cubeon-client-hud.mixins.json`, package `com.cubeon.client.hud.mixin`. Mixin
  handler renamed to `cubeon$onPongResponse`.
- The HUD's config file is `config/cubeon-client-hud.json`;
  `CubeonHudConfig.load()` **still falls back to the old `keyhud.json`** so an
  upgrading player keeps their overlay positions instead of getting the defaults
  back. It is never written — the first save lands on the new name.
- Non-Java files that had to move with it: `mod/build.gradle` (`mixins_extra`),
  `mod/brackets.json` and `cubeon/cubeonfriends.py` prose, `tools/build_mod_jars.py`
  (`REQUIRED_ENTRIES`), `tools/test_mod_matrix.py`, `tools/test_mod_compile.py`,
  `.gitignore`.

**All 24 jars rebuilt** through Gradle/loom (~22s each with a warm loom cache)
and passed `build_mod_jars.py`'s `verify()`. Confirmed by hand as well: the
required entries are present, `cubeon-client-hud.mixins.json` is in the 26.x jars
only, and **no `dev/keyhud` path survives in any jar**. The jars are the only
thing the launcher consumes, so the rebuild is the rename as far as players are
concerned.

Two gotchas worth keeping:

- `mv assets/keyhud assets/cubeon-client` **nested** the old dir inside the new
  one (both existed — the font was already under `cubeon-client`), so the lang
  file ended up at `assets/cubeon-client/keyhud/lang/`. It is fixed, but it is
  the kind of thing to check after any asset-namespace move.
- I edited a shared source file *while* the 24-jar build was running, so the
  first pass produced a mixed set and had to be run a second time. **Do not edit
  mod sources while `build_mod_jars.py` is running** — it is one Gradle
  invocation per bracket and each one re-reads the tree.

## Where this leaves the user's original brief

Every item in `instructions.txt` is now done except the two that were explicitly
deferred: **FPS recording/graph (Phase 5)** — the user skipped it after asking
whether it costs FPS — and the **benchmark re-recording** question the previous
agent left open (still unanswered).

## The full gate, and one extra bug found (reported, not fixed)

`tools/test_mega_smoke.py --suites` = **44 passed, 1 failed**. The one failure is
`test_mod_store.py` (24/3), and it is **not** a regression:

- its three failing checks assert the global mod store holds *exactly one file*,
  but the store path comes from the ambient `CUBEON_GAME_DIR`, so a sandbox that
  other suites have already installed into (the HUD jar alone does it) leaves
  jars behind and the assertions list them;
- re-run with a **fresh** `HOME` and `CUBEON_GAME_DIR`, the same file is
  **27 passed, 0 failed**. CI gets a virgin sandbox per job, which is why this
  only ever shows up locally after a few runs.

That is a real test defect (the file is not hermetic) and it is logged in
`agents/docs/module-map.md` beside the store docs. Left alone rather than fixed
in this session, per the "report, don't silently fix" rule.
