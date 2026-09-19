# Friends corner button: real two-person icon on 26.x (blank until pre-26 splits)

The small Friends corner button (title + pause menu) now shows an actual icon
on Minecraft 26.x instead of a blank square: a bundled two-person silhouette
glyph in Cubeon grass green (#83C13D), with the pending-invite count appended
when there is something actionable. On 1.20-1.21 it is byte-for-byte unchanged
(blank, or the count) on purpose - see the version-range finding below.

## What changed
- `mod/src/main/resources/assets/cubeon-friends/font/cubeon_friends.json` +
  `.../textures/font/cubeon_friends.png`: a bitmap font mapping U+E000 to the
  glyph. Texture is 8x8 WHITE-with-alpha (Minecraft tints by text colour; white
  is the era-independent choice). Regenerate with `tools/make_corner_icon.py`.
- `CornerIcon` split by era, same FQN `com.cubeon.friends.CornerIcon`, one body
  per bracket, entry point `static Component label(int pending)`:
  - `mod/src/main/java-overlay-26/.../CornerIcon.java` - glyph always; appends
    the count (no space: 2 digits still fit the 20px button). Uses 26-only API:
    `Identifier.fromNamespaceAndPath`, `Style.EMPTY.withFont(new
    FontDescription.Resource(id)).withColor(TextColor.fromRgb(0x83C13D))`,
    `Component.literal(...).withStyle(style)`, `.append(...)`.
  - `mod/src/main/java-overlay-1.20-1.21/.../CornerIcon.java` - previous
    behaviour, touching only `Component.literal/empty`.
- `CubeonFriendsScreen.iconLabel()` now computes the pending count (shared) and
  delegates drawing to `CornerIcon.label(pending)`.
- Build paths taught the overlay dir: `mod/build.gradle` adds
  `src/main/java-overlay-${bracket.key}` to the main source set;
  `tools/build_mod_jars.py` `sources(bracket_key)` walks the same dir.
- `tools/test_mod_compile.py` compiles the 1.20-1.21 overlay (era-stable) with
  the shared tree; the 26 overlay is deliberately NOT stub-compiled (26-only
  FontDescription chain would pollute the version-stable stub) - it is checked
  by the real 26 build against the actual 26.1.2 jar instead.

## Why the pre-26 bracket has no icon yet (the range finding)
The 1.20-1.21 bracket spans several font/component API generations: through
~1.21.5 `Style.font` is `ResourceLocation`; by 1.21.11 (still <26) it is the
new `FontDescription` (same type 26.x uses), and the JSON-component parser
changed at 1.21.6. One pre-26 jar cannot reference the font type on both ends,
so drawing the glyph there requires splitting that bracket - deferred (user
picked 26.x now). 1.21.9's mapped jar is NOT cached locally (unlike .4/.5/.6/
.8/.11), so the exact 1.21.5->1.21.11 transition point was not pinned.

## Verification
- `tools/test_mod_compile.py` clean; `test_mod_matrix.py` 68 passed;
  `test_mod_bridge.py` 100 passed.
- `tools/build_mod_jars.py` built + verified BOTH jars (26 via javac against
  real 26.1.2, 1.20-1.21 via Loom). Jars copied to `~/.cubeon_launcher/cache/`.
- javap on the 26 jar's CornerIcon confirms it really references
  FontDescription$Resource/Identifier/TextColor/Style (compiled against real
  26.1.2). Both jars contain the font json + png; 1.20 jar's CornerIcon is the
  small plain-text body.
- Font json + 8x8 PNG inside the live mc26 jar parse cleanly (U+E000, ascent 7).
- NOT done: in-game visual check (no GUI session here). User should confirm the
  glyph renders grass green and sits centered on 26.1.2; if it looks cramped or
  too small, the grid in `tools/make_corner_icon.py` is the one knob.
