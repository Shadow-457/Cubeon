# Flexible + animated capes (2026-09-07)

## What I did

Follow-on to the Profile Cape tab (`ed7858d`). Two user-approved features,
committed as `aadc6f2`:

1. **Flexible cape uploads.** The picker now accepts any image
   (png/jpg/jpeg/webp/gif/bmp). `cubeon/capes.py` auto-fits non-cape shapes
   onto the 10x16 back panel of a real 64x32 sheet (HD 2:1 layouts pass
   through untouched), so "not 64x32" is no longer a rejection.

2. **Animated capes, self-only.** A multi-frame GIF/APNG stores capped
   frames (`<name>.frames.json`, 16 max, ≤512px, 2-10fps) next to the cape.
   The launcher serves them to our Fabric mod over `GET /cape/frames`
   (loopback, token-authenticated, 204 when none), and the mod's new
   `AnimatedCape` thread animates the LOCAL player's own cape in-game by
   re-registering `minecraft:capes/<USERNAME>` with fresh frame textures.
   Only the wearer sees motion; friends see static frame 0 via CSL
   LocalSkin. Zero Worker/KV involvement, zero bytes for other clients.

## Verification

- `python tools/test_capes.py` — 29/29 (fit/JPEG/HD passthrough, frame cap,
  dedupe, sync + rename cleanup, /cape/frames 200-vs-204 contract)
- `tools/test_friends_service.py` 180/180, `test_mod_bridge.py` 110/110,
  `test_mod_compile.py` clean, `test_ui_smoke.py` 46/46,
  `test_mod_matrix.py` 68/68
- `build_mod_jars.py` — both jars rebuilt into cache + `assets/jars/`

## Gotchas hit (test-side)

- JPEG is lossy: pixel-equality assertions on fitted panels fail; compare
  with tolerance (~12/channel).
- PIL GIF dedupe: consecutive identical frames collapse before the cap —
  use distinct frames when testing MAX_FRAMES.
- `test_friends_service`'s route-coverage regex now allows one path
  sub-segment (`/cape/frames`) on both the mod-call and served sides.

## Reflection names (all verified against real jars earlier)

`Identifier` ctor(1.20.1)/`method_60655`(1.21)/`withDefaultNamespace`(26);
`class_1060` register/getTexture; `class_1043` setPixels/upload + dual ctor;
`class_1011.method_49277` read(byte[]); `class_310` getUser → `class_320`
getName; `execute(Runnable)` on the event loop. One jar spans all brackets.

## Baton question for the next agent

In-game verification is still todo-by-user: we have no automated harness
that can launch a real client and watch the cape. If you get any report
like "cape stuck on frame 0 in-game", check two things first: (a) the
frames file exists (`~/.cubeon_launcher/capes/<name>.frames.json`) — the
mod silently disables animation without it; (b) `AnimatedCape`'s texture id
`minecraft:capes/<USERNAME>` still matches what SkinManager registers in
the user's MC version (see the KEY CONTRACT note in the module map's capes
row and `mod/.../AnimatedCape.java`'s header).
