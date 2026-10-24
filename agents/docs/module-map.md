# Cubeon module map

Read this first, then only the references needed for the task. Public guides
live in [docs/](../../docs/README.md). Detailed earlier findings are preserved
in [the implementation reference](../history/implementation-notes-2026-10-24.md);
dated or superseded entries there are not a substitute for current code.

## Repository entry points

| Path | Responsibility |
| --- | --- |
| `main.py` | Startup, window/session lifecycle, navigation, Play orchestration |
| `launcher_core.py` | Compatibility facade over the launcher modules |
| `cubeon/` | Game/service logic and shared UI helpers |
| `ui/` | Flet tab builders and dialogs |
| `mod/` | Fabric companion client and version-specific overlays |
| `worker/` | Skins, invites, friends, downloads, and waitlist services |
| `packaging/` | Platform build scripts and installers |
| `tools/` | Standalone tests, development harnesses, and release tooling |

## Module ownership

| Area | Modules |
| --- | --- |
| Paths and configuration | `cubeon/paths.py`, `config.py`, `atomicio.py` |
| Game installation and launch | `versions.py`, `mod_loaders.py`, `launch.py`, `jre.py` |
| Instances | `instances.py`, `versions.py`, `content.py` |
| Mods and packs | `mods.py`, `modpacks.py`, `global_mod_cache.py`, `content.py` |
| Content compatibility | `packformat.py`, `doctor.py`, `content.py` |
| Download infrastructure | `net.py`, `global_mod_cache.py`, `local_cache.py` |
| Friends ownership | `friends_service.py`, `friends.py`, `e2ee.py` |
| Mod bridge | `local_api.py`, `cubeonfriends.py`, `mod/brackets.json` |
| World sharing | `p2p.py`, `invites.py`, `server.py`, `minekube.py`, `gate.py` |
| Cosmetics | `skins.py`, `capes.py`, `gallery.py`, `profile.py`, `appearance.py`, `appearance_scene.py` |
| Chat faces and artwork | `faces.py`, `icons.py`, `version_art.py` |
| Activity and screenshots | `milestones.py`, `activity.py`, `library_stats.py`, `screenshot_gallery.py` |
| UI infrastructure | `thread_safe_ui.py`, `dialogs.py`, `motion.py`, `theme.py`, `scrolling.py` |
| Window and crash handling | `winwindow.py`, `winchrome.py`, `incident.py`, `logging_setup.py` |
| Input and presentation | `shortcuts.py`, `seasonal.py`, `color_templates.py`, `status_text.py` |
| Release and optional features | `updater.py`, `features.py`, `osnotify.py`, `voice.py` |

Except for explicit paths, names in this table are relative to `cubeon/`.
Check source ownership before assuming a helper is UI-free: the package also
contains Flet support modules.

## UI ownership

| Surface | File |
| --- | --- |
| Play version picker, cards, banner, instances | `ui/versions.py` |
| Mods, resource packs, shaders | `ui/mods_tab.py` |
| Modpacks | `ui/modpacks_tab.py` |
| Chat | `ui/chat_tab.py` |
| Cosmetics and account previews | `ui/skin_tab.py`, `ui/appearance_preview.py` |
| Servers | `ui/server_tab.py` |
| Activity statistics | `ui/stats_tab.py` |
| Settings | `ui/settings_tab.py` |
| Screenshot gallery | `ui/screenshot_gallery.py` |

Tabs are lazy-built and retained. Shared state and callbacks are wired in
`main.py`; keep builders consistent with the shared `THEME` contract.

## Contracts to preserve

### Flet and UI updates

- Dependencies pin Flet and `flet-desktop` to `>=0.86,<0.87`. A machine-wide
  installation of another version is not the release environment.
- Mutate shared control trees under `thread_safe_ui.TREE_LOCK`; request
  scoped repaints through `thread_safe_ui.refresh()`. Background threads
  must not invoke a whole-page update directly.
- Use `cubeon.dialogs` for dialog-stack compatibility. Removed APIs include
  `ft.border.all`, `ft.padding.only`, and `ft.margin.only`.
- Local absolute paths are not valid `ft.Image.src` values. Use cached
  base64, bundled asset paths, or a real URL; do not restore blank local images.
- Reuse installed/browse rows and image controls during metadata updates.
  Chat presence/unread updates must not remount PFPs. Use gapless playback
  and change sources only when actual artwork changes.
- Default hover/click effects are fill/rim fades, not scale or corner morphs.
  Mods and Modpacks do not replay cascade/shimmer animations on refresh.

### Play and content

- Installed-instance selection restores its actual loader before refreshing
  dependent surfaces. Quick Jump and instance actions use `_pick_version()`.
- The banner uses an opacity-only 180 ms transition with a stable host.
  Identical sources are no-ops; late artwork must not replace a newer selection.
- Reserve the loader-status slot and keep hero labels single-line. Changing
  Jump back in must not change hero height because a notice appears.
- Vanilla accepts resource packs, not mods or shader packs. Other loaders
  are valid when compatible; shaders also require Iris/Oculus-style support.
- Shared storage must not leak one instance's active content into another.
  Installs/cancellation must respect instance ownership and atomic writes.
- FPS boost is the Play-menu toggle. Turning it off restores the previous
  settings; do not replace Sodium's defaults with unsupported tuning claims.

### Chat, cosmetics, and account data

- Chat and the companion mod consume one process-scoped FriendsService.
  Keep adaptive polling, draft preservation, read markers, and optimistic
  send/echo reconciliation intact.
- Self-avatar fallback is uploaded PFP, cached skin face, then initials.
  Detect real file/source changes without re-reading unchanged bytes per poll.
- Cosmetic libraries are local folders. `remotes.py` is still used by the
  offline-session explanation's premium-name lookup; it is not dead code.
- Cosmetics uses the shared native-client 3D preview, not a new C/Rust
  dependency. Cape ordering and scene state have focused regression tests.
- Screenshots have their own Settings section, not the main Settings pane.
  Servers has no Browse view. Stats uses a compact recent-playtime histogram.
- Public UUIDs and display names are not private capability tokens. The
  loopback mod bridge is authenticated; never publish identity or token files.

### Windows, Java, and packaging

- Preserve all three Windows reveal paths: forced visible transition,
  `to_front()` call, and the native `winwindow.py` backstop. Flet's default-value
  suppression can make a plain `visible=True` assignment ineffective.
- Hide consoles on every Windows child-process spawn. Custom window chrome
  remains opt-in; fullscreen/maximize changes require explicit state handling.
- Verify Java by running it, and run the complete first-launch doctor.
  Do not blame Java for a graphics failure without Java-specific evidence.
- The game must not inherit launcher-only software-graphics overrides.
  Crash text must not promise a fix that has not been verified.
- `mod/brackets.json` is the version-routing authority. Per-version source
  overlays are intentional; do not collapse them as accidental duplication.
- Current mod assembly needs JDK 25+ for Gradle, while bytecode targets Java 17.
- Bundle the Flet desktop client, color templates, required mod jars, and
  `assets/jars/connect-spigot.jar`. The large tunnel JAR is a runtime dependency.

## Documentation and repository hygiene

- Public documentation has one home under `docs/`; no duplicate agent mirrors.
  The player guide is `docs/user-guide.md`, platform checks are under
  `docs/release/`, and dated reports are under `docs/reports/`.
- The README uses `web/assets/cubeon-play.png`, the website's launcher image.
  Flat-square Shields badges show release, edition, and platforms; the version
  badge reads releases dynamically rather than hardcoding a stale version.
- Source licensing is Apache 2.0. Keep company/private checkout paths out of
  public instructions and do not add fabricated support or performance claims.
- Logs, compiled classes, captures, virtual environments, and build caches
  stay untracked. Historical local task notes are preserved under
  `archive/agent-history/`; Git retains their previously committed versions.
  Runtime JARs are not generated clutter.
- UI captures default to `archive/ui-captures/`, not the agent-reference tree.
  Old diagnostic snapshots are kept locally in `archive/agent-history/generated/`.
- Do not delete build caches while a build or worker is active. Local cleanup
  does not shrink existing Git history; do not rewrite history without approval.
- The repository lives at `~/Ylet_Productions/products/cubeon`; old
  `Products/Cubeon` or `Downloads/Cubeon` paths are obsolete. Do not create a
  parent-company Git repository or assume the old `.venv-build` is usable.

## Verification

Tests are standalone scripts, normally isolated with `_sandbox_home` and
safe fixtures. Run the affected script first, then the smoke gate.

```bash
python tools/test_mega_smoke.py
python tools/test_mega_smoke.py --static
python tools/test_mega_smoke.py --suites
node worker/test-worker.mjs
```

The default smoke gate does not run all registered suites; `--suites` does.
See [testing](../../docs/development/testing.md) for prerequisites and exclusions.

| Change | Focused checks in `tools/` |
| --- | --- |
| UI/tree contracts | `test_ui_smoke.py`, `test_motion.py`, `test_scrolling.py` |
| Play/selection/banner | `test_version_ui.py`, `test_version_art_cache.py` |
| Mods and artwork | `test_mod_ui_stability.py`, `test_loader_content_rules.py` |
| Chat | `test_chat_avatar_stability.py`, `test_chat_optimistic.py`, `test_faces.py` |
| Cosmetics | `test_appearance_preview.py`, `test_capes.py` |
| Windows/startup | `test_winwindow.py`, `test_winchrome.py`, `test_startup.py` |
| Mod sources and jars | `test_mod_compile.py`, `test_mod_matrix.py`, `test_mod_bridge.py` |
| Releases | `test_release_version.py`, `test_release_pipeline.py` |
| Repository cleanliness | `test_repository_hygiene.py` |

Known baseline: the scoped-repaint assertion in `test_tab_navigation.py`
also failed before the recent polish. Do not disguise existing failures as
passing or fix unrelated behavior while changing documentation.

## Releases and hosted services

- A push to `main` starts the release workflow. Publishing, committing,
  deploying, and rewriting history require the user's explicit request.
- `tools/release_version.py` owns stamping/channel policy. Zero-patch versions
  are stable; nonzero-patch versions are beta. Preserve concurrent release
  metadata and do not force-push over another change.
- Publishing verifies the required assets. Test jobs are separate; a published
  release does not establish that every test or desktop smoke check passed.
- Worker configuration is not proof of current deployment health. Preserve
  client/Worker protocol parity, authentication, write budgets, and rate limits.
- See [builds](../../docs/release/build.md), [security](../../SECURITY.md), and
  [Worker deployment](../../worker/README.md) for the current public references.
