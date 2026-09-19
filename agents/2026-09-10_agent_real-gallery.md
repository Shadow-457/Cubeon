# 2026-09-10 — Real-player cosmetics gallery (replaces self-drawn art)

## What I did
The user asked for real skins/capes/hats from free 24/7 APIs instead of the
gallery's generated placeholder art. I verified the sources live from the
shell first, then reworked the pipeline and shipped it.

### Verified working live (2026-09-10), all keyless/free/24/7
- **Mojang** `api.mojang.com/users/profiles/minecraft/<name>` -> UUID ->
  `sessionserver.mojang.com/session/minecraft/profile/<uuid>` -> base64
  textures blob -> real 64x64 skin PNG + cape PNG (when the account owns one).
  Mojang serves bare-`http://` texture URLs, so we upgrade to https.
- **mc-heads.net/face/<name>** -> real player flat head.
- **There is NO real hat API.** Vanilla Minecraft has no hat slot. "Real hats"
  = a real player's head worn as the hat layer. Said so plainly.

### Code
- `cubeon/remotes.py` (NEW): Mojang + mc-heads client, cached under
  `CUBEON_HOME/remotes/<id>/` (24h TTL, stale-cache offline fallback), all HTTP
  through a module-level `TEST_HANDLER` hook so tests need no network.
- `cubeon/gallery.py` (REWORK): procedural art out; the catalog is now REAL
  players (canonical username = id). Lists are network-free (cache only).
  Kept public API; added `load_player`, `install_gallery_hat`, `list_gallery_hats`.
- `cubeon/cosmetics.py`: `add_image_hat(...)` so a real head PNG is a wearable
  32x16 hat-layer (set_hat/compose/preview all work unchanged).
- `ui/skin_tab.py`: "Load a real player" box in Skin + Cape Browse (fetch +
  install the real gear), "Wear a real player's head" in Cosmetics.
- `tools/test_gallery.py`: rewritten for the fake-Mojang pipeline.

## Verification
- `tools/test_gallery.py` 30/30 (fake Mojang via remotes.TEST_HANDLER).
- `tools/test_ui_smoke.py` 74/74, `tools/test_capes.py` 14/14, skins-net green.
- py_compile on every edited file. test_fuzz launched (was flaky-slow before).
- Found + fixed: `os.path.isfile(None)` crash in `_snapshot_from_profile` for
  cape-less players; `attach_hover` needs (`..., None, SURFACE_HI)`).

## Gotchas for the next agent
- Keep the gallery `list_*` functions network-free (UI calls them at build).
  Anything that can't be resolved offline must stay OUT of the build path.
- `remotes.TEST_HANDLER` is the ONLY network seam tests use - keep using it.
- The old `agents/2026-09-09_agent_cosmetics-gallery.md` describes the
  procedural gallery; it's history now. module-map Follow-up 21 is the truth.

## Final cleanup (same session)
- Removed the last chunked-edit placeholder markers from `ui/skin_tab.py`
  (`__CAPE_GALLERY_UI__`, `__ASSEMBLY__`); grep across cubeon/ ui/ tools/ is
  marker-free.
- Moved remotes.py's constants (CACHE_TTL / TEST_HANDLER / _UA / endpoint
  urls) from the bottom of the file up to the top with their comments — they
  were stranded at EOF by the chunked inserts.
- Re-verified after cleanup: test_gallery 30/30, smoke 74/74, capes 14/14,
  skins-net green, py_compile on all edited files, and a LIVE end-to-end run
  (throwaway HOME, real network): fetched CheeseChips's real skin + real
  mc-heads head and wore the real head as a hat.