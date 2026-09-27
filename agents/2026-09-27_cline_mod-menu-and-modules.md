# Mod menu + module framework (2026-09-27)

- **Agent:** Cline
- **Date:** 2026-09-27
- **Task:** "add pvp mod menu via the mod like we click a button it comes up and
  stuff" + a reference screenshot — then "in 1 go" when offered a phased plan.
  Explicitly **not** asking for cheating features.

## What shipped
- `ModuleMenuScreen` — category tabs (All/HUD/PvP/Render/Utility), a search box,
  a card per module with a name, blurb, On/Off toggle and a `...` settings
  button that opens -/+ controls for that module's values.
- Opened by a **"Mods"** button that `PauseScreenMixin` adds next to the
  Friends icon. No keybind: that needs `fabric-key-binding-api`, and this mod
  ships no Fabric API modules (loader only). Offered as a one-liner if the dep
  is acceptable.
- `modules/` framework: `Module`, `ModuleConfig`, `ModuleCategory`, `HudText`,
  `HudState`, `GameOptions`, `OptionsAccessor`, `Modules`.
- 13 real modules. Render: Fullbright, FOV Changer, No View Bobbing, Smooth
  Camera. PvP: Auto Sprint, Reach, Attack Cooldown, Ping, Armor. HUD: FPS,
  Coordinates, Keystrokes, Session Time. Nothing that cheats.
- Config at `<game>/config/cubeon-modules.json`, atomic writes.

## The key finding: one jar still works
I javap'd the real 1.20.1 and 26.1.2 jars before writing anything. The menu,
the framework and the option-driven modules all use API that is
**byte-identical in both eras**: `Options.gamma()/fov()/bobView()`,
`OptionInstance.get/set`, `keyUp`, `LocalPlayer.tick`, `getArmorValue()`,
`getAttackStrengthScale(float)`, `hitResult`, `getFps()`, and the whole Screen
widget surface (Button/EditBox/StringWidget/addRenderableWidget/font/
clearWidgets/isPauseScreen).

**Two things are NOT shared**, and that is the whole design:
- 26.x turned `Options`' public *fields* into *accessors*. Writing
  `options.gammaSetting` compiles on 1.20-1.21 and fails 26. Everything uses
  the accessor form.
- The in-game HUD draw was genuinely reshaped: 1.20-1.21 has
  `Gui.render(GuiGraphics, float)`, 26.x has
  `Gui.extractRenderState(GuiGraphicsExtractor, DeltaTracker)`. So only
  `HudMixin` is per-bracket - same FQN in both `java-overlay-*` dirs, the
  `CornerIcon` arrangement. It does nothing but call `HudState.lines()` and
  draw strings; all the content logic is shared and testable.

## The bug the real 26 build caught
Auto-sprint originally read `mc.player.input.forwardImpulse`. The **stub test
passed** - I had modelled that field from 1.20.1 without checking 26. The real
26 build failed:

```
Modules.java:241: error: cannot find symbol
  mc.player.input.forwardImpulse   symbol: variable forwardImpulse
  location: variable input of type ClientInput
```

26.x turned it into `ClientInput.hasForwardImpulse()`. Fixed to read
`options.keyUp.isDown()`, which exists in both - and which is what auto-sprint
actually means. The stub for `Player.input` is now a comment explaining why it
must not come back. **This is the argument for building real jars: the stub
test was green and the feature was still broken on one bracket.**

## Tests
- `test_mod_bridge` **164/0** (was 146) — new SelfTest sections
  `moduleFramework` and `hudTextLines`, 18 new checks covering toggle-applies-
  immediately, clamping, category matching, config round-trip, malformed-JSON
  degradation, unknown-id rejection, a throwing module reporting itself off, and
  the exact HUD line formatting.
- `test_mod_compile` — all 20 sources compile clean; wiring guard extended to
  understand per-bracket overlay mixins and assert a per-bracket one exists in
  BOTH overlays (it immediately caught that HudMixin was per-bracket and that
  the new mixins needed `REQUIRED_ENTRIES` entries).
- `test_ui_smoke` 166/0, `mega --static` 15/0.
- **Both jars rebuilt** and verified to contain the menu, the framework and
  both mixins.

## For the next agent
- **Never opened in-game.** No display. The menu layout, the widget code and
  the HUD drawing are all unexercised. A real launch is the only proof, and
  the 26.x `extractRenderState` text call is the single most likely thing to
  be wrong (it is the least verifiable surface in the mod).
- The card layout is a fixed 2-column grid with a hard-coded card width, so on
  a very narrow window or a large GUI scale the columns may not fit. Worth
  scaling off `this.width` if it looks wrong.
- `Modules.get()` is a singleton; `ModuleConfig.loadFrom` is only called once at
  startup, so changing the game directory mid-session will not re-read it.
- Durable facts went into `agents/docs/module-map.md` ("Mod menu + module
  framework"), not into this note.