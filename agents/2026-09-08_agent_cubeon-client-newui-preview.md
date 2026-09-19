# 2026-09-08 — Mod renamed "Cubeon Client", brand player tag, version banners, --new-ui preview

## What was asked (clarified after round 1)
1. Rename the **IN-GAME MOD** (the Friends mod inside Minecraft) to
   "Cubeon Client" — NOT the launcher. Launcher stays "Cubeon".
2. Brand block: cube icon + "Cubeon" + the player's avatar and IN-GAME
   username next to it, like Feather Client shows.
3. New UI template with pictures fetched from official version pages, cached.
4. `python main.py --new-ui` runs the redesign preview WITHOUT touching the real UI.

## What was done
### Round 2 corrections (launcher name REVERTED)
- main.py: `page.title` back to "Cubeon"; wordmark "Cubeon" (19pt, as before).
- Brand block is now: `[cube.svg] Cubeon [ (avatar chip) in-game-name ]` —
  the player tag is a pill (SURFACE_HI, hairline border, radius 999) with a
  small CircleAvatar (radius 9) + monospace username. Click → Profile tab.
  Lives via walrus names `sidebar_brand_avatar` / `sidebar_brand_username`,
  both refreshed in `refresh_avatars()`.
- test_ui_smoke title assertion back to "Cubeon".
- ui_new/preview.py branding fixed to "Cubeon" too.

### Mod rename (the real ask)
- `mod/src/main/resources/fabric.mod.json`: name "Cubeon Friends" →
  "Cubeon Client" (jar id `cubeon-friends` and package names unchanged —
  renaming those would break bracket routing, worker parity and the mod
  matrix for zero visible gain).
- `CubeonFriendsScreen.java`: screen title literal "Cubeon Friends" →
  "Cubeon Client"; corner-icon tooltip likewise.
- Mod jars rebuilt via tools/build_mod_jars.py (cache + assets/jars both).
- In-game "Cubeon Friends" chat notices (CubeonFriendsClient) were NOT
  renamed — they're sentences about friends, not the mod's nameplate.

- `cubeon/version_art.py` (NEW): version → cached banner image.
  - Source: minecraft.wiki. Two-step lookup:
    1. `https://minecraft.wiki/images/<id>_banner.jpg` (works for 1.15.2+,
       snapshots too — verified live).
    2. MediaWiki API `prop=pageimages` lead image (old versions: 1.8.9, 1.9,
       1.12.2, 1.14, 1.13, 1.10, 1.11, 1.18 all resolve this way).
  - Cache: `~/.cubeon_launcher/cache/version_art/<id>.{jpg,png}`, forever
    (banners never change post-release). Memory dict + disk probe; misses are
    memory-only cached so a page gaining art later retries next launch.
  - `fetch_async(version, cb)` for UI threads — daemon thread, callback does
    its own marshalling. Uses `cubeon.net.get_with_retry` (retry/backoff).
- `ui_new/preview.py` + `ui_new/__init__.py` (NEW): standalone redesign mock.
  - Top-bar nav (not sidebar rail), cinematic 180px hero with the version
    banner + dark scrim, version card grid, pill loader chips, PLAY CTA,
    Mods tab with mock cards. All tabs are stubs except Play/Mods.
  - Reuses real palettes via `cubeon.color_templates` (TEMPLATE_MODULES +
    _derive) so `--new-ui` respects the carbon default palette.
  - Flet 0.86 gotchas hit & fixed: `ft.padding.symmetric` →
    `ft.padding.Padding.symmetric`, `ft.padding.all` → `ft.padding.Padding`,
    `ft.divider` → `ft.Divider`, `Text(spacing=)` → `TextStyle(letter_spacing=)`.
  - Verified headlessly: builds 105 controls, zero None children (gray-box
    trap), all 6 nav clicks build their tabs; live `--new-ui` painted a real
    window (ui_painted_ok marker) and exited cleanly.

## Verification
- `tools/test_ui_smoke.py`: 48 passed, 0 failed.
- `tools/test_net.py`: 19 passed, 0 failed.
- Live banner fetch matrix: 1.8.9→1.21.11 + 25w14craftmine all resolve.
- `timeout python3 main.py --new-ui`: window painted, clean exit 0.

## Invariants learned (added to module map)
- version_art banner URL shape + API fallback + cache location.
- ui_new/ is preview-only; real UI untouched.

## Q&A baton for the next agent
The user wants to evaluate `python main.py --new-ui`, then, if approved, port
the layout into the real main.py UI. When porting: the top-bar nav replaces
the sidebar rail, but KEEP the sidebar's Signed-in-as block, status dot,
controller pill and inspector toggle somewhere (they have no home in the
preview yet — that's a deliberate stub).
