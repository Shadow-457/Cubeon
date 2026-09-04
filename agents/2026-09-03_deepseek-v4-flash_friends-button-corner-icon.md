# Friends menu button -> small top-left corner icon with count badge

Changed the Cubeon Friends mod so the entry point on the title screen AND the
pause menu is a quiet 20x20 square docked top-left instead of a full-width
"Friends (N online)" button in the menu's button column.

## What changed
- `mod/.../CubeonFriendsScreen.java`: `menuButton()` now builds a 20x20 button
  (`ICON_W/H`, `ICON_INSET = 4`); `badgeText()` replaced by `iconLabel()` which
  is blank normally and shows invites + incoming requests as a count when > 0
  (online friends no longer shown on the button - not actionable). Tooltip
  simplified to "Cubeon Friends - invites and friend requests".
- `mod/.../mixin/PauseScreenMixin.java`: dropped the measure-the-lowest-widget
  placement; now adds the icon at top-left (4,4). Kept the `minecraft.player ==
  null` guard (pause screen backs the saving-world overlay) and fail-soft.
- `mod/.../mixin/TitleScreenMixin.java`: same corner-icon placement; removed the
  layout-measuring code entirely.

No new assets and no new Minecraft API touched - still only Button/widgets, so
one source tree still compiles for both namespace eras (test_mod_compile passes).

## Verification
- `tools/test_mod_compile.py` - all sources compile clean vs the API stub.
- `tools/test_mod_matrix.py` - 68 passed; `tools/test_mod_bridge.py` - 100 passed.
- Built bracket 26 (`mappings: none`, javac path) -> jar copied to
  `~/.cubeon_launcher/cache/cubeon-friends-1.0.0+mc26.jar` (matches
  mod/build/libs). javap confirms ICON_* + iconLabel() present, badgeText gone.
- User only has Minecraft 26.1.2 installed, so that jar is the live one.

## Both brackets now built (Gradle installed)
- Installed Gradle 9.7.1 to `~/.local/share/gradle-9.7.1` (pacman needs sudo and
  wasn't available; no passwordless sudo), symlinked at `~/.local/bin/gradle`
  (that dir is already on PATH in ~/.bashrc). The prior `~/.gradle` cache made
  the loom build go fully offline.
- `gradle build -PmcVersion=1.20-1.21` (fabric-loom 1.14.10) -> BUILD SUCCESSFUL;
  `tools/build_mod_jars.py 1.20-1.21` verified + copied to
  `~/.cubeon_launcher/cache/cubeon-friends-1.0.0+mc1.20-1.21.jar`. javap on the
  remapped jar confirms ICON_* + iconLabel() present (obfuscated names:
  class_4185 menuButton, class_2561 iconLabel) - so pre-26 Minecraft gets the
  corner icon too now.
