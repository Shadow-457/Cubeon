# Rust client port: scope and saved progress

Updated 2026-11-04. The user asked to fix repeated launcher update prompts and
local mod uploading first, then resume this work. This is a work-state record,
not a completion report.

The user also requested simpler Mods navigation and four Settings sections
(Account, Game, Performance, Appearance), with Doctor called Fix problems and
explicit profile-picture upload/remove labels. These launcher changes are now
implemented: persistent update dismissal/current-version guards, reviewed batch
local imports with backups, one content area with visible Mods/Modpacks/Resource
Packs/Shaders selectors, compact tiles and search/Installed actions,
screen-dependent result counts, local/cached pack artwork with Cubeon-logo fallback,
earlier title publication and pooled artwork downloads, four Settings sections and
explicit profile-picture labels. Focused suites and
real Flet captures verify them. Java cosmetic wings now replace equipped elytra
visually, with flying strokes and vanilla fallback for hidden peer cosmetics.
This Java implementation does not complete the native Rust cosmetic port.

## Accepted scope

- Replace all player-facing Horizon names, logos, window icons, UI translations,
  crash/log labels and help links with Cubeon branding. Retain required MIT and
  third-party copyright/license notices.
- Make CustomSkinLoader-compatible skin/cape lookup work in the Rust engine using
  Cubeon's existing local mirrors, ordered texture-source behavior and public
  CustomSkinAPI service. Java CSL JARs cannot directly execute in the native engine.
- Port the **full Cubeon client feature set**; the user explicitly selected this
  over a skins/capes/cosmetics-only first stage. Reuse config/service contracts and
  implement native gameplay/render/input behavior with real feature verification.
- Add animated cosmetic wings as a visual replacement for equipped elytra in the
  Cubeon client. A viewer who hides other players' cosmetics must see their normal
  vanilla elytra. Do not change item requirements or gliding physics.
- Preserve the existing Instances/New instance Rust · Beta → 26.3-only flow,
  offline stable local identity, selected-Rust Servers unavailability, and the
  explicitly unmeasured 1000 FPS target.
- Finish Cubeon's own GitHub runtime hosting after the revised build is verified.

## GitHub setup already performed

An isolated checkout lives at `/tmp/cubeon-rust-release`, based on current
`origin/main` (`32d9d24`, the v1.3.46 stamp). Rust source/integration files were
committed and pushed on `rust-beta-26.3`:
`7549a1c9c370da782e81614d29677fa94b400196`.

The initial Linux/Windows native build is
https://github.com/Shadow-457/Cubeon/actions/runs/41823252681 .
It uses `.github/workflows/rust-beta.yml`, triggered by relevant changes to the
Rust source branch, with artifact/hash merging and preparer/CLI checks. It does
not publish. The Linux, Windows and manifest jobs completed successfully.
This run predates the new branding/full-client work.

The pinned download destination is `Shadow-457/Cubeon`, release tag
[`rust-26.3-beta.1`](https://github.com/Shadow-457/Cubeon/releases/tag/rust-26.3-beta.1),
published on 2026-11-06 from successful run `42064514681` at `f68ff468`.
The Windows/Linux archives and manifest passed provenance, size and hash checks;
their public download URLs work. The normal updater filters to numeric `vX.Y.Z`
tags, so the Rust prerelease is outside its launcher channels; latest stable
remains `v1.3.46`. This publishes the revised beta, with Windows gameplay and
feature/performance work still subject to the limits described below.

The main working checkout retains unrelated website/benchmark changes. The
isolated source branch contains only Rust integration/source changes and a
Rust-only module-map update. Do not reset or overwrite the user's main checkout.

## New changes saved locally, not yet built or pushed

Under `native/cubeon-rust/crates/`, player-facing strings/logs/crash labels and
locale values/English phrase keys were rebranded. `Page::Horizon` and its references
are now `Page::Cubeon`. The public launch API's product key is `cubeon`.
`horizon-theme/icons/horizon-64.png` was replaced by
`horizon-theme/icons/cubeon-64.png`, copied from `assets/icon_64.png`; its embedded
reference was updated. Offline skin/cape variables in `skins.rs` now use
`CUBEON_RUST_OFFLINE_*`.

These edits are in the main checkout only, and require compilation, localization
and actual native UI verification. Remaining internal namespace/file names and
original notices are provenance/compatibility details, not verified UI branding.
Native CSL/full-client/elytra behavior has not yet been implemented.

## Entry points and constraints found

- Existing Java Cubeon client: `mod/src/main/java/com/cubeon/client/` plus version
  overlays selected by `mod/brackets.json`; Minecraft 26.3 uses `hud-26.3`,
  `cosmetics-26`, Mojang API adapters and queued `SubmitNodeCollector` geometry.
- `hud/HudFeatures.java` defines 13 overlays. `ui/HudMenu.java` has searchable
  categories, positions/scales, health, cosmetic animation/depth/peer visibility,
  sprint and motion blur; emotes/friends are separate controls. Preserve all
  features, hold-to-zoom/freelook and the existing per-feature input/visibility rules.
- `CubeonHudConfig.java` owns `cubeon-client-hud.json`; cosmetic selection is
  launcher-owned `config/cubeon-cosmetics.json` and read-only in the client.
- `CosmeticPlayers.java` applies local/peer identity, visibility/range and per-player
  animation trackers. Other cosmetics default off and must never hide vanilla
  capes/elytra/parrots. Only cancel a vanilla elytra layer when a visible, ready
  replacement is actually drawn.
- Java `CosmeticElytra.java` orders the cosmetic layer immediately before vanilla
  wings and consumes a single-pass identity marker only after ready wing geometry
  is emitted/queued. Port the visibility/fallback contract and flight animation to
  Rust; Java mixins cannot execute in the native engine.
- `Bridge.java`/`cubeon/local_api.py` provide token-protected loopback friend/chat/
  emote contracts. Never use Cubeon's private token as a Minecraft account token.
- `cubeon/csl.py`, `cubeon/skins.py`, and
  `docs/decisions/customskinloader-verified-facts.md` define texture source priority,
  slim metadata, pointer identity and CustomSkinAPI bare texture IDs/trailing slash.
- Native renderer `skins.rs` already supports skin/cape decoding, cache/download
  slots and offline images. `game/cosmetics.rs` already has player-bone geometry
  integration, but its Horizon provider is disabled. Cubeon's catalogue has more
  slots/larger textures than that provider; inspect atlas limits before adapting it.
- Native integration points: `horizon-client/src/game.rs` HUD/input/player state,
  `game/extras.rs`, `extras_hud.rs`, `game/cosmetics.rs`, `game/skin_models.rs`,
  renderer `extras.rs`, `hud.rs`, `options_ui.rs`, and mob model/pose/render code.
- Existing baseline build/resources/tests are recorded in
  `agents/2026-11-04_codex_rust_beta_implementation.md`. Root `build/rust-engine/`
  has the previously verified local Linux bundle. Rebuild/repackage after native
  changes; do not treat that old ZIP as containing the new branding/features.

## Resume sequence

Complete the update-popup and local-mod import fixes and their checks first.
Then compile/verify the saved branding edits, implement and verify native CSL,
port each Cubeon feature against its Java behavior, add/test wing-elytra rendering
and viewer fallback across supported Java/native paths, refresh runtime packages,
push the revised source and publish verified platform downloads/manifests.
