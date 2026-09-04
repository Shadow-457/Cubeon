# Friends feature: finished verification, fixed 5 stale contract tests, rebuilt + deployed jars

- **Agent:** Cline GLM 5.3
- **Date:** 2026-09-04
- **Task:** relay from the user's request to Claude — make the friends mod fully
  work: (1) Add button stuck, (2) rename gives no "you are set" feedback,
  (3) friend profile needs Chat / Play / Sync buttons, (4) Sync shows
  incompatibilities (version/mods/loader), download-mods into the global store,
  relaunch notice on version change — all over the E2EE relay.

## Finding: the features were already implemented; the remaining work was validation

Audited the whole stack end-to-end and confirmed every requested item is present
in current source:

- **Add stuck** — `cubeon/friends_service.py` `add_friend()` is now
  local-state-only (microseconds, no blocking REST pre-flight). A typo'd name is
  answered asynchronously by the Worker (`worker/cubeon-friends.js:362`,
  `T_SYSTEM 'No Cubeon user named "X".'`) through `/events` → status line.
- **Rename feedback** — sticky status-line confirmation in the mod
  (`CubeonFriendsScreen.java` `statusSticky`, "You are now X." outranks the
  launcher's own toast) plus the launcher's unambiguous
  `"Your Cubeon name is now X."` notice (`friends_service.rename()`).
- **Chat / Play / Sync** — all three actions exist on a selected friend's rows;
  Sync is a full compare view (`POST /syncstart` → E2EE compare channel →
  pre-rendered lines: your/friend's version+loader+mod count, missing/extra
  mods, `POST /syncdownload` fetches missing mods into the global store and
  reports `"Done. Relaunch Minecraft to load the new mods."`, version-mismatch
  guidance included; `POST /syncclose` cleans up).

## What I actually changed

- **`tools/test_friends_service.py`** — 5 failures were stale expectations
  against the deliberate new contracts (not product bugs):
  1. add-friend pre-flight removal (the stuck-Add fix): test now asserts the
     add frame is sent and the Worker's async system reply reaches the feed.
  2. rename wording: expects `"Your Cubeon name is now NewName."`.
  3. chat unknown-friend / keyless-friend refusals: `_peer_pubkey` now caches
     per process, so the test pops `service._peer_pubkeys` before asserting.
- **Rebuilt both mod jars** with `tools/build_mod_jars.py` (the deployed
  `~/.cubeon_launcher/cache/` jars predated the last `Bridge.java` /
  `CubeonFriendsScreen.java` edits — this is likely why the user still saw old
  behaviour): `cubeon-friends-1.0.0+mc1.20-1.21.jar` (gradle+loom) and
  `+mc26.jar` (javac), both verified and copied to the cache.

## Verification

- `tools/test_friends_service.py` → **179 passed, 0 failed** (was 174/5)
- `tools/test_friends.py` → 37 · `tools/test_mod_bridge.py` → 110 ·
  `tools/test_mod_compile.py` → clean · `test_mod_matrix.py` → 68
- Not done: a live two-launcher in-game run (no GUI session here). User-facing
  step: **restart the launcher** so local_api serves the new add/rename logic,
  and relaunch Minecraft so `ensure_installed` swaps in the fresh jar.

## Follow-up (same day): ACCOUNT tab pre-fills your name

The user asked for a visible place showing their name when they press Rename.
In `CubeonFriendsScreen.java`:

- The ACCOUNT tab's text box is now **pre-filled with the current name** and
  editable in place (rename = edit the box, press Rename). Seeding happens once
  per name (`nameSeeded` field), never overwrites a draft the player is typing,
  and re-seeds after a successful rename so the box tracks the new name.
- Prose updated to say the name is in the box below.
- Pressing Rename with an unchanged name now flashes "That's already your
  name." instead of doing a pointless round trip.
- Verified: `test_mod_compile.py` clean, `test_mod_bridge.py` 110 passed, both
  jars rebuilt and redeployed to `~/.cubeon_launcher/cache/`.

## Follow-up 2: guaranteed answer for adding an unclaimed name

User reported they never see the "No Cubeon user named X." answer when adding
a name nobody has claimed. The async answer relies on the relay's T_SYSTEM
reply (worker/cubeon-friends.js:362) — an older deployed Worker would drop the
add silently. Made the launcher self-sufficient in `friends_service.py`:

- `add_friend()` now spawns `_verify_add()` (worker thread, bounded REST
  `check_name`): if the name doesn't exist, it emits the same
  `'No Cubeon user named "X".'` error notice itself. Never blocks the mod's
  request thread.
- `_notify()` now dedupes identical text within `_NOTICE_DEDUPE_SECONDS`
  (10 s), so the relay's reply and the local fallback can't double-toast.
- Regression test added (fallback answers "Ghost" without any system frame);
  `test_friends_service.py` → 180 passed, `test_friends.py` → 37. Launcher-side
  only — no jar rebuild needed; user must restart the launcher to pick it up.

## Follow-up 3: notices now land in Minecraft chat; Server settings decluttered

1. **Chat delivery** (`CubeonFriendsClient.java`): toasts went to the hotbar
   overlay line, which faded in ~3 s — how the user kept missing the
   "No Cubeon user named X." answer. Notifications now go to the real chat
   window via `LocalPlayer.sendSystemMessage(Component)`, the one chat entry
   point with the same shape in BOTH eras (verified against the real 26.1.2
   jar with javap: `displayClientMessage(Component, boolean)` was renamed away
   in 26.x; `sendSystemMessage` was not). First attempt with
   `displayClientMessage` failed the mc26 javac build and was caught by it.
   Compile stub updated; both jars rebuilt + redeployed.
2. **Server settings cleanup** (`ui/server_tab.py`): the settings card was one
   long wall. Basics (server name, port, limits, distances, gamemode,
   difficulty, switches, whitelist) stay visible; Public address, Security
   password, Smooth mode, Server power and the folder/delete buttons now
   collapse behind an "Advanced options" toggle that starts closed. Wordy
   hints trimmed (gate status, Smooth-mode hint). All controls remain in the
   tree, so refresh/disable logic and the smoke tests are unaffected.
3. Verified: `test_ui_smoke.py` 40, `test_friends_service.py` 180,
   `test_mod_bridge.py` 110, `test_mod_compile.py` clean, both jars rebuilt
   and deployed.

## Follow-up 4: even less text in Server settings

Second pass at the user's "less text" request (all in `ui/server_tab.py`):
- Switch hints are gone from the cards — they're tooltips now; cards shrunk
  86 → 60 px. Labels tightened: "PvP", "Whitelist only", "Premium accounts only".
- The visible distance-cap caption was deleted; its explanation moved to
  tooltips on the "Render distance" / "Simulation distance" dropdowns
  (labels shortened from "Render distance cap (chunks)" etc.).
- Section label "Allowed players (whitelist)" → "Whitelist"; seed field
  "World seed (optional)" → "World seed"; advanced subtitle →
  "Address, password, RAM"; gate hint removed from the layout (now a tooltip
  on the password field).
- `test_ui_smoke.py` → 40 passed after the pass.

## Follow-up 5: install area decluttered too

- Removed the page subtitle ("Install, EULA, and the common server.properties
  edits...") and the two type lines ("Server type: Paper (plugins)" +
  "Paper with plugins. Vanilla compatible.") from the Install card. The card
  is now just: Install button (+ status/progress) and the EULA checkbox.
  The Paper explanation rides on the Install button's tooltip.
- EULA label shortened to "I accept the Minecraft EULA" with the URL moved
  into its tooltip.
- `test_ui_smoke.py` → 40 passed.

## Follow-up 6: Profile tab decluttered (`ui/skin_tab.py`)

- The three always-visible italic paragraphs (skin-visibility note under Your
  Skins, hats note, capes note) are gone from the layout; each now rides as a
  tooltip on its section label ("Your Skins", "Cosmetics - hat", "Cape",
  "Your Capes"). One intermediate state had a stale `cape_note` reference that
  tripped `build_skin_section` in the smoke test - fixed (the capes column
  needed its own label helper).
- `test_ui_smoke.py` → 40 passed, `test_skins_net.py` all green.

## Follow-up 7: Modpacks tab de-jargoned (`ui/modpacks_tab.py`)

- The "CurseForge API key" sentences are gone from the page. The popular-load
  status now reads "Includes CurseForge classics." and the search status
  "N packs found." — both carry a tooltip with the optional-key detail for
  power users.
- Other status strings shortened and de-tech'd: "Searching Modrinth..." →
  "Searching...", "Modrinth search failed: {ex}" → "Search failed - check
  your internet.", "Couldn't load modpacks: {ex}" → "Couldn't load the list -
  check your internet.", "N pack(s)" → "N packs", search hint shortened to
  "Search modpacks... e.g. better mc".
- `test_ui_smoke.py` → 40 passed; no "api" string remains in visible UI text.

## Follow-up 8: stale-jar tripwire (production-readiness fix #3)

The "I fixed that but I'm still seeing the old bug" class of failure - an
updated launcher running against an old injected mod jar - is now detected and
announced instead of silent:

- `cubeon/cubeonfriends.py` gains `mod_stamp(mc_version)`: short sha256 of the
  jar `find_jar()` would install, cached per (path, mtime).
- `friends_service.roster_payload()` serves it as `mod_stamp` (via a
  module-level `_mod_stamp()` helper with a lazy import; the first cut was
  accidentally indented into the class body and broke the test run - fixed by
  moving it to module scope after the class).
- `Bridge.java`: `Snapshot` gains `modStamp` (defaults "" so older launchers
  simply skip the check). On each refresh the mod fingerprints its own jar via
  its code-source location and compares; a mismatch delivers a one-shot chat
  notice: "Cubeon was updated - restart Minecraft to get the latest Friends
  features." Unfingerprintable setups (dev dirs) stay silent.
- Verified live: stamps hash the two real cache jars and differ; mods
  re-hashed. `test_friends_service` 180, `test_friends` 37,
  `test_mod_bridge` 110, `test_ui_smoke` 40, mod compile clean; both jars
  rebuilt + redeployed.

## Follow-up 9: jars shippable from assets/, disk-space guards

- **`assets/jars/` is now the distributable home for the mod jars.**
  `tools/build_mod_jars.py` copies every verified build there in addition to
  the runtime cache, and `cubeonfriends.find_jar()` checks cache →
  assets/jars → mod/build/libs (a packaged launcher has only assets/jars;
  dev build/libs stays as a fallback). Both current jars copied into
  `assets/jars/`; verified find_jar resolves through the new path when
  build/libs is absent.
- **Disk-space guards** (from agents/docs/production-readiness-gaps.md):
  `cubeon/paths.ensure_disk_space()` refuses with a human sentence when the
  destination drive can't fit the download (10% margin + 64 MB). Wired into
  `server.install_server` (512 MB guard before a Paper install/download) and
  `modpacks._stream_download` (checks the response's content-length before
  writing a single byte). Verified the guard fires with a friendly message.
- `test_friends_service` 180 · `test_mod_matrix` 68 · `test_mod_bridge` 110 ·
  `test_ui_smoke` 40.

## Follow-up 11: agents/docs/module-map.md — the anti-re-reading map

The user's recurring pain: every agent session starts by re-reading the whole
codebase. Built the fix this repo's note system was missing - a living map:

- `agents/docs/module-map.md`: one-paragraph architecture summary, repo
  layout table, per-module ownership table, the "facts that bite" list (two
  jar namespaces, human-sentence degradation, on-disk roots, assets/jars
  shippability, relay lag, UI text policy), the test commands with expected
  pass counts, deeper-doc pointers, and open production items.
- `AGENTS.md` now points to the map FIRST and instructs agents to fold
  durable facts into the map instead of burying them in diary notes.

Maintenance rule: the map is the living truth; diary notes are history.

## Follow-up 10: Connect plugin jar moved out of the repo root

- `connect-spigot.jar` (62 MB, Minekube Connect) moved from the repo root to
  `assets/jars/`, next to the Friends mod jars - the root is now clean and
  every distributable jar lives in one folder.
- `minekube.find_local_plugin()` searches `assets/jars` first, then the app
  dir, cwd and servers dir (legacy drop spots still work). Verified live:
  `find_local_plugin()` resolves to `assets/jars/connect-spigot.jar` and the
  zip/plugin.yml validation still passes.
- `test_invites` 127 · `test_ui_smoke` 40.

## Follow-up 12: production pass 1-5

Items from the production-readiness list, done in one pass:

1. **CI test job** - `.github/workflows/build.yml` gained a `test` job running
   every `tools/test_*.py` (hermetic via CUBEON_GAME_DIR, Java 21 for the mod
   compile test) BEFORE the build jobs.
2. **Auto-update check** - `cubeon/updater.py` (APP_VERSION, feed check,
   is_newer); main.py runs it in the background at startup and shows a
   non-blocking "Cubeon X is available / Get it" snackbar. NOTE: APP_VERSION
   must be bumped with every release, and a real feed URL owner/repo must be
   set (currently the placeholder default fails silently by design).
3. **Logging** - `cubeon/logging_setup.py`: rotating `~/.cubeon_launcher/cubeon.log`,
   excepthooks so NO uncaught failure anywhere is silent, `diagnostics_text()`
   ready for a future "copy diagnostics" button. Wired first in main().
4. **Live two-player test** - NOT done (needs two humans with the GUI). Still open.
5. **Retry/resume/concurrency** - `cubeon/net.py`, wired into all three
   download sites (packs, mods, Paper jar). 19 new tests in `tools/test_net.py`.

Verified: test_net 19, test_modpacks 51, test_mod_store 21, test_friends_service
180, test_friends 37, test_ui_smoke 40, test_invites 127; all touched files
compile; workflow YAML parses. Gotcha: sharing one CUBEON_GAME_DIR across
suites pollutes the mod store - use a fresh tmp dir per run.

## Follow-up 13: production pass 2 (items 6-14)

Done: relay rate limits (#6, needs `wrangler deploy`), opt-in crash reporting
client (#7, needs a receiving endpoint), orphaned-game watchdog (#9), macOS CI
build job (#11, inline PyInstaller with mandatory assets bundling), first-run
onboarding dialog (#10). Skipped with reasons: #8 (paid cert), #12 (tray API
risk / toast hooking), #13 (high effort).

KEY DISCOVERY: `packaging/` does not exist in this repo even though
.github/workflows/build.yml's Windows/Linux jobs call those scripts - those
two jobs cannot succeed until the scripts are restored or the jobs are
converted to inline PyInstaller (the macOS job shows the pattern; assets
MUST be in --add-data).

Verified: test_production 13/13; full sweep green (net 19, modpacks 51,
mod_store 21, friends_service 180, friends 37, ui_smoke 40, invites 127,
launch_indicator 11); node worker checks pass; all touched Python compiles;
workflow YAML parses.




