# Remove the [#] nametag badge from the in-game mod (2026-09-27)

- **Agent:** Cline
- **Date:** 2026-09-27
- **Task:** "in the in game mod i wanna remove the cube coming with the users
  name like this #shadoww_"

## What it actually was
Not a literal `#` — a **bracketed square**, `[▪]Shadow`: three components
(`[` grey, `▪` U+25A0 in Cubeon green, `]` grey). The user wrote it as
`#shadoww_`; that is this badge.

Applied by `mixin/PlayerNameMixin.java`, an `@Inject` on
`Player.getDisplayName()` at RETURN, calling `Nametag.decorate()`, which
returned `badge() + displayed`. Because it hooked the *display name*, it
painted everywhere the client draws the name from that method — the nametag
above the head (the tab list builds its own component and was untouched).

## Removed
- `mod/src/main/java/com/cubeon/client/Nametag.java` — deleted (it was only
  reachable from the mixin).
- `mod/src/main/java/com/cubeon/client/mixin/PlayerNameMixin.java` — deleted.
- `cubeon-client.mixins.json` — `PlayerNameMixin` unregistered.
- `CornerIcon.badge()` + the `MARK`/`MARK_GREEN`/`BRACKET` constants + the
  now-unused `ChatFormatting` import — removed from BOTH overlays
  (`java-overlay-1.20-1.21` and `java-overlay-26`).
- `tools/test_mod_compile.py` — dropped both sources from `MOD_SOURCES`;
  rewrote the stale `net/minecraft/.../Player` stub comment.
- `tools/build_mod_jars.py` — swapped `PlayerNameMixin.class` for
  `TitleScreenMixin.class` in `REQUIRED_ENTRIES` (a jar missing a required
  entry is treated as a broken build).

## Deliberately KEPT: BadgeNames.java
It no longer has a caller in the mod, but I kept it and its SelfTest
coverage. Its docstring records a real, hard-won bug: the relay's routing
*handle* is not the Minecraft *username*, and when the launcher moved to
auto-minted handles the badge silently stopped appearing on friends. That
matching rule is worth keeping for any future non-name-marking use, and it is
tested on a bare JDK. Called out in the module map so nobody "cleans it up"
as dead code.

## Verification
- `tools/test_mod_compile.py` — **all sources compile clean** against the
  version-stable API subset (javac 21, release 17). This is the check that
  actually proves the Java edits are valid.
- `tools/test_mod_bridge.py` — **146/0** (the `BadgeNames` tests still run and
  pass; deleting them would have reduced coverage for no reason).
- `tools/test_mega_smoke.py --static` — 15/0. `mod/brackets.json` +
  `cubeon-client.mixins.json` both parse.
- Grepped the whole repo for `PlayerNameMixin` / `Nametag` / `badge()` — only
  hits left are my own doc comment and the gitignored stale
  `mod/build/resources/` Gradle output (regenerated on next build).
  `main.py`'s `update_pack_badge` is unrelated (modpack badge in the launcher
  UI, not the in-game name).

## For the next agent
- **The badge is gone but the jars are not rebuilt.** `assets/jars/*.jar` and
  anything under `~/.cubeon_launcher/cache/` still contain the old classes.
  Rebuild with `python3 tools/build_mod_jars.py` (or the 26 bracket alone)
  before the change is visible in-game, or the launcher will keep installing
  the pre-badge jars.
- I did not run an in-game visual test (no display / no game launch here), so
  the *rendered* result is unverified — only the compiled source is. The
  change is a pure removal with no new draw path, so the risk is low, but a
  real launch is the proof.
- Durable facts went into `agents/docs/module-map.md` ("Nametag badge
  REMOVED"), not into this note.