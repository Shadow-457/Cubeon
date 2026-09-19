# Animated cape system removed (2026-09-07)

## What I did

User asked for a clean removal of the animated cape system. It was shipped
earlier today (see agents/2026-09-07_agent_flexible-animated-capes.md and the
static-fix note) and touched both launcher and mod. Everything is gone:

- **Mod**: deleted `mod/src/main/java/com/cubeon/friends/AnimatedCape.java`
  (the whole reflection animator); removed `AnimatedCape.refresh(this)` from
  `Bridge.refresh()` and the `CapeFrames` record + `fetchCapeFrames()` from
  `Bridge.java`.
- **Launcher**: removed the frame storage from `cubeon/capes.py`
  (`_read_frames`, `.frames.json` writing, `animated_cape_frames()`,
  MAX_FRAMES/MAX_FPS/MAX_ANIM_WIDTH, the `animated` flag in capes.json —
  `add_custom_cape` now just fits the single image); removed the
  `/cape/frames` route + `capeframes` provider slot from
  `cubeon/local_api.py`; removed `cape_frames_payload` and its wiring tuple
  entry from `cubeon/friends_service.py`; removed the `animated_cape_frames`
  re-export from `launcher_core.py`; removed the animated badge/caption/
  status message from `ui/skin_tab.py`.
- **Tests**: rewrote `tools/test_capes.py` down to the still-cape coverage
  (flexible input + CSL sync/cleanup, 14 checks); dropped AnimatedCape.java
  from `test_mod_bridge.py` and `test_mod_compile.py`; fixed the endpoint
  contract comment in `test_friends_service.py` (it cited /cape/frames as the
  reason paths allow one sub-segment).
- Rebuilt both jars via `tools/build_mod_jars.py` (fresh hashes in cache +
  `assets/jars/`; deployed installs will be flagged stale by mod_stamp, which
  is the designed path — a restart of Minecraft picks the new jar up).

Custom capes remain fully functional as STATIC images: upload → auto-fit onto
the cape layout → CSL LocalSkin sync. Nothing about the removal touches the
Worker or KV.

## Verification

- `python3 tools/test_capes.py` 14/14
- `python3 tools/test_mod_bridge.py` 110/110
- `python3 tools/test_mod_compile.py` clean (both brackets)
- `python3 tools/test_mod_matrix.py` 68/68
- `python3 tools/test_friends_service.py` 180/180 (incl. the mod↔launcher
  endpoint contract, now without /cape/frames on either side)
- `python3 tools/test_ui_smoke.py` 48/48 (incl. the 5b cape-row/no-None check)
- `python3 tools/test_friends.py` 37/37
- `grep` sweep: zero remaining references outside `agents/` history notes
  (the only "animated" hits in code are the unrelated `animated_switch`
  theme widget).

## Baton

- Old `.frames.json` files from animated capes may still exist on the user's
  disk under `~/.cubeon_launcher/capes/` — harmless orphans now (nothing
  reads them). If you ever want them gone, a one-line sweep there is safe.
- If a still-running game session has the old jar, its AnimatedCape class
  simply never gets frames served (the endpoint is gone; the mod's fetch
  would 404 and degrade to static) — the stale-jar warning will nudge the
  restart anyway.
