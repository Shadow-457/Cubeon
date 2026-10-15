# 2026-10-15 — FPS boost moves to the Play menu; OFF restores vanilla graphics

## Ask
"the cubeon optimization actually nerfs the game shadow and textures and
looking right? and the fps boost button is in the settings but it doesnt do
much if the install is already installed. Remove that option and instead add
a toggle in play menu which actually doesn't nerf the texture and things once
off but actually make 3x fps when on … do not nerf the fps."

## The honest answer (recorded in the module map)
The boost's FPS comes FROM those settings - graphicsPreset fast, ao:false,
entityShadows:false, particles:2, biomeBlendRadius 0. They are not a bug;
they are the levers. So "3x FPS with zero visual change when off" is delivered
as: ON = exactly the previous fast values (NOT weakened), OFF = the same keys
written BACK to Minecraft's defaults at launch. The old OFF did nothing to an
installed instance because it only skipped FUTURE application - the fast
values stayed baked in options.txt. That is the "doesn't do much" the user
felt, and it is fixed.

## Changes
- `cubeon/game_options.py`: new `restore_vanilla_look()` + 
  `VANILLA_LOOK_OPTIONS` (same keys, vanilla defaults incl. smoothLighting).
  `apply_max_fps()` untouched.
- `cubeon/launch.py`: boost on → apply_max_fps; off → restore_vanilla_look.
- `cubeon/config.py`: `max_fps_enabled` → `fps_boost_enabled`, migrated in
  load_config (the user's ON/OFF choice carries over).
- `main.py`: Settings checkbox deleted; `fps_boost_switch` (ft.Switch) built
  BEFORE `play_tab` and placed in the Play card under "Mod loader" with a
  one-line explainer. First draft defined it after play_tab →
  UnboundLocalError; test_ui_smoke caught it and a guard now pins the order.
- `ui/settings_tab.py`: the "Max FPS mode" row removed.
- `tools/test_perf_mods.py` §11 (75 checks): restore values, idempotence,
  boost-restore round trip, fresh-file no-invented-keys, visual choices
  untouched.
- `tools/test_ui_smoke.py` (187): new "FPS boost lives in the PLAY menu" block.

## Verification
- test_perf_mods 75/75, test_ui_smoke 187/187, test_launch_fixes 106/106,
  test_friends 104/104, test_friends_service 373/373,
  test_versions_profile_key 13/13, mega_smoke --static 15/16 (the "mutable
  default args" FAIL is pre-existing, verified identical on a stashed tree),
  mega_smoke --suites 37/39 (same two pre-existing FAILs: mutable-defaults
  lint + wedge_watchdog, which spawns real GUIs).
- NOT verified in-game (no GUI session): the Play-card layout and one real
  boosted→unboosted launch cycle should be eyeballed once.
