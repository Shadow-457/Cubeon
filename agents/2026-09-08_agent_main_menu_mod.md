# 2026-09-08 — main-menu mod UI + GPU-crash fix + top-bar launcher layout

## What was built (part 3: top-bar layout, mod dependencies, legacy gate)
- Sidebar → top icon bar (Play/Mods/Modpacks/Cosmetics/Servers centered,
  Account/Settings right) per the user's mockup; Server sub-tabs (Console/
  Plugins/Settings) are chips shown only while a server tab is active;
  identity card (avatar/username/picture) moved into an Account dialog
  behind the person icon; old Profile tab became the Cosmetics tab
  (skins/capes/hat).
- Mods: clicking Download now also installs REQUIRED Modrinth dependencies
  (`mods.install_mod_with_dependencies`; skip-if-installed via meta
  project_ids; per-dep failure never blocks the main mod). Verified live:
  iris → sodium resolved; junk slug → [] without raising.
- Play tab: "Update game version" button (newest stable release, auto-install
  via existing prefetch) and a "Legacy" opt-in button that gates <1.20
  versions behind a dialog noting the Cubeon Client stops working there.
- test_ui_smoke updated for the icon nav (labels checked via lowercased
  all_text, which includes tooltips). Full battery green: ui_smoke 52,
  production 13, mod_store 21, modpacks 51, friends_service 187, mod_bridge
  119, mod_matrix 68, mod_compile clean, capes 14, skins_net.

## What was built (part 2: crash recovery)
The user pasted a coredump: flet client SIGSEGV in libgallium **mid-session**
(window had been up 21 minutes). The pre-paint retry loop didn't cover that,
and in-process retry is impossible (ft.run once-per-process). Changes in
main.py:
- `_kill_flet_client()` now returns whether a LIVE flet child was found
  (zombies excluded - a zombie is a crashed/exited client).
- `_session_loop`: window painted + client gone → arm `use_software_gl`, bump
  `CUBEON_GPU_RESTARTS` (env survives execv; reset on clean close), re-exec
  the launcher (tray-reopen trick), max 2, then park like a user close.
- Parked `_reopen.wait` now catches the spurious "Event loop is closed"
  RuntimeError from flet's exit_gracefully (was a spurious CRITICAL fatal).
- Verified: /proc scan against real forked children (live vs zombie with
  PR_SET_NAME); all test suites still pass (ui_smoke 48, production 13,
  friends_service 187, mod_bridge 119).

## What was built (part 1: the mod main menu)

## What was built
- **Shared** `mod/src/main/java/com/cubeon/client/CubeonMenuScreen.java`: the new
  menu (Profile / Skins / Capes / Cosmetics / Statistics / Chat + bottom Online
  button + character-box area with its own Profile button). Strictly
  widget-only (same contract as CubeonClientScreen). Chat ported: friend-picker
  rows, transcript labels with Older/Newer paging buttons, EditBox + Send.
  Opens from a "Cubeon" button added under the corner icon in BOTH
  TitleScreenMixin and PauseScreenMixin.
- **Era overlays** (both `java-overlay-*` dirs): `CharacterView` (true 3D
  entity-in-inventory render of the local player into the box; draws nothing on
  the title screen where mc.player is null) and `mixin/CubeonMenuRenderMixin`
  (injects at TAIL of CubeonMenuScreen.render / extractRenderState). Registered
  in cubeon-client.mixins.json.
- **Shared** `WorldPlayers.java`: players actually in the world via
  `Minecraft.getConnection().getOnlinePlayers()`. GameProfile's NAME accessor
  is NOT era-stable (1.20.1 authlib: `getName()`; 26 authlib 9 record:
  `name()`) → resolved reflectively, try `name` then `getName`.
- **Bridge**: new poll stream `refreshPlayers()` → GET /players;
  `CubeonPlayer` record + `parsePlayers()` (unit-tested in SelfTest.java,
  "Bridge: /players parsing"). `Nametag.names()` now also covers these names.
- **Launcher**: GET `/players` in local_api.py (empty list when no provider /
  500→empty list on raise — mod treats null/empty as "nothing known") backed by
  `FriendsService.players_payload()` (you first, with skin/cape from CSL
  LocalSkin mirrors via `_local_skin_name`/`_local_cape_name`; friends carry
  version/status only — their pixels live on THEIR launcher).

## How verified
- test_mod_compile / test_mod_bridge (119) / test_mod_matrix / test_friends_service
  (187) all pass. BOTH real jars build+verify: 26 via javac against the shipped
  26.1.2 jar; 1.20-1.21 via gradle+loom against 1.20.1 (network available).
- Live smoke of /players: no provider → `{"players": []}` 200; provider → rows
  carried; raising provider → 500 with empty players list.

## Gotchas for the next agent
- 1.20.1's `renderEntityInInventoryFollowsMouse` is
  `(GuiGraphics, centerX, feetY, scale30, centerX-xMouse, feetY-50-yMouse, entity)`
  — NOT the 9-arg 1.20.2+ shape. The 26 one is
  `InventoryScreen.extractEntityInInventoryFollowsMouse(extractor, i,i,i,i,i,
  f,f,f, entity)`.
- tools/test_friends_service.py had a stale MOD_SRC path (com/cubeon/friends);
  fixed to com/cubeon/client.
- The stub inventory additions (GuiGraphics, InventoryScreen, LivingEntity,
  ClientPacketListener, PlayerInfo, GameProfile, Minecraft.getConnection) are
  for the overlay/WorldPlayers only — shared screens still can't touch
  graphics; GuiGraphics is deliberately member-less.

## Part 4: compact Account|Game-version row + searchable version picker
- Config band is one row: ACCOUNT (username) | GAME VERSION (button).
- Dropdown replaced by a dialog: search field + filtered list + Show
  snapshots + "Browse all versions →". The ft.Dropdown survives as the
  unmounted source of truth; `version_dropdown_button` mirrors its value via
  `_sync_version_button()` called from on_version_selected.
- Fixed the `_reveal_window` NameError the fuzz suite caught (`_CUBEON_HOME`
  not in main()'s scope - the ui_painted_ok marker was never written).
- Green: ui_smoke 52, production 13, fuzz 12 (incl. coroutine scan).
