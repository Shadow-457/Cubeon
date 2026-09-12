# 2026-09-11 - Removed the in-game Cubeon menu (kept Friends)

## Ask
"in the cubeon client mod remove the cubeon menu where it shows profile
stats etc remove it completely and cleanly but do not remove the friends"

## What the menu was
The mod had TWO screens:
- `CubeonClientScreen` - the **Friends** screen (Friends/Requests/Chat/Account).
  Kept.
- `CubeonMenuScreen` - a separate hub button that opened Profile / Skins /
  Capes / Cosmetics / Statistics / Chat / Online, with a 3D player preview.
  Removed.

Two mixins added both buttons on the title screen and pause menu; the menu
button sat right under the Friends icon. The preview was drawn by per-era
overlay `CharacterView.java` + `mixin/CubeonMenuRenderMixin` (the shared screen
was widget-only).

## Changes
Deleted:
- `mod/src/main/java/com/cubeon/client/CubeonMenuScreen.java`
- `mod/src/main/java-overlay-1.20-1.21/com/cubeon/client/CharacterView.java`
- `mod/src/main/java-overlay-1.20-1.21/com/cubeon/client/mixin/CubeonMenuRenderMixin.java`
- `mod/src/main/java-overlay-26/com/cubeon/client/CharacterView.java`
- `mod/src/main/java-overlay-26/com/cubeon/client/mixin/CubeonMenuRenderMixin.java`
- the two now-empty overlay `mixin/` directories

Kept: `CubeonClientScreen`, `CornerIcon` (both overlays), `Bridge`, `Json`,
`Nametag`, `WorldPlayers`, `CubeonClient`, and both mixins' **Friends** button.

Edited:
- `mixin/PauseScreenMixin.java` / `mixin/TitleScreenMixin.java`: dropped the
  `CubeonMenuScreen` import and the menu-button block, leaving only the Friends
  icon (`CubeonClientScreen.menuButton`).
- `resources/cubeon-client.mixins.json`: dropped `CubeonMenuRenderMixin`
  (now PauseScreenMixin / PlayerNameMixin / TitleScreenMixin).
- `tools/test_mod_compile.py`: removed the menu + overlay sources from
  `MOD_SOURCES`, deleted the now-menu-only `GuiGraphics` + `InventoryScreen`
  stubs (LivingEntity stays - LocalPlayer extends it).
- `tools/build_mod_jars.py`: removed the three menu classes from
  `REQUIRED_ENTRIES`.
- Comment-only staleness: `cubeon/local_api.py`, `cubeon/friends_service.py`,
  `cubeon/config.py` no longer say the in-game menu reads /players.
- Docs: `agents/docs/module-map.md` (menu section rewritten as a "gone, do not
  reintroduce" durable fact; fixed the stale `CubeonFriendsScreen` /
  `com/cubeon/friends` table row) and `guide-ui-modules.md` (class rename).

## Jars rebuilt (this is what makes the removal live in-game)
The launcher installs from `assets/jars/`, so leaving the old jars would have
shipped the menu anyway. Rebuilt both brackets with `tools/build_mod_jars.py`:
- `cubeon-client-1.0.0+mc26.jar` (javac path)
- `cubeon-client-1.0.0+mc1.20-1.21.jar` (gradle+loom)

Verified by reading the jars: no `*MenuScreen`/`CharacterView`/
`*MenuRenderMixin` entries, `CubeonClientScreen.class` present, and the embedded
`cubeon-client.mixins.json` lists only the three kept mixins.

## Verification
- `test_mod_compile` - all sources compile against the version-stable subset
  (31 stub types, down from the menu's 33).
- `test_mod_bridge` 119/119, `test_mod_matrix` 68/68, `test_friends_service`
  187/187, `test_ui_smoke` 93/93.
- Both shipped jars inspected as above.

## Note for next agent
`Bridge.java` still has transport methods the removed menu used (profile/skins/
stats/etc). They are harmless and the launcher's `/players` endpoint still
feeds the Friends roster, so they were left in place. If you want to prune them,
do it deliberately - `test_friends_service.py::test_contract` reads
`CubeonClientScreen.java` (not Bridge) to decide which endpoints must exist.
