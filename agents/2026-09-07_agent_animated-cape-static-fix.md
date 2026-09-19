# Animated cape stuck on static frame (2026-09-07)

## What I did

User report: animated capes show static in-game (feature shipped this morning,
never verified live — the baton question from the flexible-animated-capes
note asked exactly for this check).

THREE stacked bugs, all silent (the mod's failure posture degrades to
"static", no log anywhere):

1. **Wrong texture id (the contract was wrong).** Vanilla registers capes
   under `minecraft:capes/<MinecraftProfileTexture.getHash()>`, and CSL 15's
   LocalSkin source uses the `(LOCAL_LEGACY)` fake-URL scheme where
   `getHash()` is a cache-busting `sha1Hex(fileLength + path + lastModifiedMs)`
   over the config path VERBATIM (`LocalSkin/./capes/<USERNAME>.png` — the
   `/./` matters!). The old code animated `minecraft:capes/<USERNAME>`, which
   only holds for the modern `(LOCAL)` scheme. Verified by reproducing the
   exact hash from `CustomSkinLoader/CustomSkinLoader.log`'s CapeUrl line —
   matched twice, at two different file states (and once more against a
   16:56 log line while the user was in-game).
2. **NativeImage width/height reflection missed on 1.21.x.**
   `method_105/method_104` don't exist on intermediary class_1011 (they're
   `method_4307/method_4323` there; `getWidth/getHeight` only on 26.x). So
   `render()` threw before its first `execute()` — even the wrong-slot
   registration never happened. Replaced with pure-byte PNG IHDR parsing
   (era-proof, no reflection).
3. **Minecraft.runDirectory is `field_1697`** in intermediary (the guessed
   `field_1687` is a ClientLevel field on 1.21.11). Needed to locate
   `CustomSkinLoader/` to compute the hash.

Fix in `mod/.../AnimatedCape.java`: `Plan` now carries a list of candidate
texture id paths — the name-based id plus the legacy hash of every known
LocalSkin cape path (computed from the live file stats under the game dir's
`CustomSkinLoader/`) — and `Glue.render()` takes over + uploads to every
candidate (wrong guesses are inert textures nothing samples). Every reflected
name re-verified with `javap` against the real
`.fabric/remappedJars/minecraft-1.21.11-0.19.5/client-intermediary.jar`.

Launcher side verified healthy: `GET /cape/frames` returned 200 with the
frames (auth is the `X-Cubeon-Token` header, NOT Bearer — bit me once).

## Verification

- `test_mod_compile.py` clean; `test_mod_bridge.py` 110/110;
  `test_mod_matrix.py` 68/68; `test_capes.py` 29/29; `test_ui_smoke.py`
  48/48 (its §5b cape-row regression still holds after today's earlier fix).
- `build_mod_jars.py` rebuilt both jars into cache + assets/jars (fresh
  hash; the launcher's mod_stamp will flag any stale deployment).
- Formula reproduction against the live CSL log is the real proof: the mod's
  candidate list contains exactly the id CSL registered at 16:52/16:56.

## Baton

In-game verification is STILL todo-by-user — the currently running game
session (started 16:28) has the OLD jar; a restart is needed for the fix to
load. If it's still static after restart: check the CSL log's CapeUrl hash
against `capes.json` state, and confirm `/cape/frames` (X-Cubeon-Token) 200s.
