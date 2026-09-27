# Tag Cubeon players in the tab list: [Cubeon] in green (2026-09-27)

- **Agent:** Cline
- **Date:** 2026-09-27
- **Task:** "now i want like when we do tab i want cubeon users to show
  [Cubeon]playername like this and cubeon green color" — confirmed with the
  user as **tab list only**, not the nametag.

## What it does
`TabListTag.decorate()` prepends a green `[Cubeon]` to a tab-list row when the
player is one the launcher can vouch for. `PlayerTabOverlayMixin` injects at
RETURN of `getNameForDisplay(PlayerInfo)`. So a friend reads `[Cubeon]Shadow`.

The name itself keeps the server's own team/scoreboard colouring — only the tag
is green. Colouring the username would fight the server's teams.

## The interesting part: finding a cross-era seam
The obvious target, the tab list renderer, is the worst possible one — and the
removed nametag badge's own docstring said so: *"the single most-reshaped
piece of client code between the two eras."* Confirmed by `javap` on the real
jars:

| | 1.20.1 | 26.1.2 |
|---|---|---|
| render | `render(GuiGraphics, …)` | `extractRenderState(GuiGraphicsExtractor, …)` |
| name builder | `getNameForDisplay(PlayerInfo)` | `getNameForDisplay(PlayerInfo)` |

**The renderer changed completely; the name builder did not.** So one injection
covers both brackets — same trick the old badge used with
`Player.getDisplayName()`. Also verified `Style.withColor(TextColor)` and
`TextColor.fromRgb(int)` are identical in both, so the tag is the *exact*
Cubeon green `#83C13D` in both, not `ChatFormatting.GREEN` (a different
colour, and all the old badge could manage on 1.20-1.21).

None of this is guesswork — every signature was read out of
`~/.cubeon_minecraft/versions/26.1.2/26.1.2.jar` and the loom-mapped 1.20.1 jar.

## Reused rather than rebuilt
`BadgeNames` (kept from the badge removal the same day) is the matching rule:
you + friends' Minecraft usernames + the `/players` roster, matched by
username, never by relay handle. Its 146 self-test checks still pass unchanged.
Known limit, same as before: a stranger running Cubeon is not tagged, because
the client can't ask "is this arbitrary name a Cubeon account".

## Cost
`getNameForDisplay` runs per row per frame while the tab list is open, so the
name set is rebuilt only when `Bridge.revision()` / `playersRevision()` move
(case-insensitive `TreeSet`, so no `toLowerCase` copy per lookup). Fail-soft
twice: `require = 0` and a `Throwable` catch, because a throw here is
crash-every-frame.

## The real build caught a bug the stub could not (the authlib split)
The first REAL jar build failed:
```
PlayerTabOverlayMixin.java:47: error: cannot find symbol
  info.getProfile().getName()   symbol: method getName()  location: class GameProfile
```
The compile stub modelled `GameProfile` with `getName()`, so the stub test
passed. Reality: **authlib 7 made `GameProfile` a record** and renamed the
accessor to `name()`.

`javap` across every authlib the launcher has downloaded:

| authlib | shape | accessor |
|---|---|---|
| 6.0.54 / 6.0.57 | plain class | `getName()` |
| 7.0.61 / 7.0.63 | **record** | `name()` |
| 10.0.77 | record | `name()` |

And the 26 bracket is not the problem — 26.1.2 ships 7.0.63, 26.3 ships
10.0.77, both records. **The real problem is inside the 1.20-1.21 bracket**:
it spans 1.20.1 (authlib 6) → 1.21.11 (authlib 7.0.61), so the accessor is
renamed *mid-range*. That defeats `brackets.json`'s own rule — "a method that
exists in the oldest exists in the newer ones too" — which is precisely the
guarantee a per-bracket overlay relies on. There is no compile-time spelling
that serves the whole bracket.

So `TabListTag.nameOf()` resolves it **reflectively once at class-init** and
caches the `Method`, preferring the record accessor. One cached invoke per row
per frame, on a path that already builds a Component and does a tree lookup.
Documented as the one sanctioned exception to the "only touch stable API" rule.

This is the strongest argument for building the real jars: the stub test was
green, the spec-compliant implementation was broken, and only a real compile
against a real authlib found it.

## Both jars built and verified
- `assets/jars/cubeon-client-1.0.0+mc26.jar` (javac path, offline)
- `assets/jars/cubeon-client-1.0.0+mc1.20-1.21.jar` (gradle+loom, 40s)
- Both contain `TabListTag.class` + `PlayerTabOverlayMixin.class`, contain
  **zero** traces of `Nametag`/`PlayerNameMixin`, and ship a mixin config
  listing `PlayerTabOverlayMixin`. Also copied to
  `~/.cubeon_launcher/cache/`, so they're live on next launch.
- Also fixed by the real build: `TabListTag.nameOf` had to be `public` (the
  mixin is in `com.cubeon.client.mixin`), and the stub `GameProfile` is now
  deliberately modelled at the authlib-6 shape so the reflective lookup is
  actually exercised rather than silently finding nothing.

## New guard: `_check_mixin_wiring()`
Three moving parts must agree (mixin config ↔ `MOD_SOURCES` ↔
`build_mod_jars.REQUIRED_ENTRIES`). An unregistered mixin silently does
nothing in-game; a stale `REQUIRED_ENTRIES` entry fails a real build over a
class that doesn't exist — that's exactly how the removed badge surfaced.
Added to `tools/test_mod_compile.py` (it already owns `MOD_SOURCES` and the
stub). It also asserts the nametag mixin stays gone, so the tab-list-only
decision can't silently regress.

**I proved the guard actually fails**: temporarily unregistered the mixin and
got `FAIL PlayerTabOverlayMixin (in MOD_SOURCES) is registered in the mixin
config`, then restored it.

Two stub compile errors were caught and fixed along the way (missing
`ChatFormatting` import; `withColor(int)` erases against `withColor(TextColor)`
in a bare stub — dropped, since `TextColor.fromRgb` is the real path).

## Verification
- `tools/test_mod_compile.py` — wiring guard all-green, **all sources compile
  clean** including `TabListTag.java` and `PlayerTabOverlayMixin.java`.
- `tools/test_mod_bridge.py` — 146/0 (BadgeNames coverage intact).
- `tools/test_mega_smoke.py --static` — 15/0.

## For the next agent
- **Still never seen in-game.** No display/session here. The jars are built and
  the injection seam is verified against the real jars, but the *rendered* row
  is not. Open a server with a Cubeon friend and hold TAB.
- **If the tag never appears**, the first thing to suspect is
  `TabListTag.PROFILE_NAME` being null (both spellings missing from the
  authlib on the classpath) — it fails silent, by design, and every row comes
  back untagged. A `System.err` line there would confirm it in one launch.
- **The badge removal note's jars caveat is now resolved too** — both jars
  were rebuilt in this session, so neither the badge removal nor the tab tag is
  pending a build.
- Durable facts went into `agents/docs/module-map.md` ("Tab-list [Cubeon]
  tag"), not into this note.