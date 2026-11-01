# Changelog

## Unreleased — Seasonal Play artwork

- Added the approved pixel-art trees, tilted sapling and ground artwork for all
  four seasons. Responsive images use bundled transparent assets and retain
  access to Play, version, username and instance actions.
- Added **Play scenery** to hide the overlay independently of the seasonal
  colors and buddy. Removed the old Weather effects option and separate band.
  Particles are capped at twelve (nine autumn leaves), updating about four times
  per second. Reduced motion keeps artwork static; hidden Play panes stop particle
  work. Minimized and unfocused windows pause animation; an empty shared ticker
  blocks without polling.
- The seasonal buddy wanders launcher edges, climbs borders and rests above Play.
  Tab changes return it to the floor before the new pane appears, fixing floating
  pets over a vanished button. Resizing also retires unavailable button perches.
  Resting, reduced-motion and paused buddies use bundled static poses.
- Fixed a native Flet layout failure that rendered the overlay as a gray panel:
  the size listener now belongs to the inner Stack, outside the positioned host.

## Unreleased — Mods, Resource Packs and Shaders audit

- Added per-instance enable/disable switches for resource packs and shaders,
  including unpacked folders. Disabled entries stay recoverable and are excluded
  from launch staging. Shared bytes and sibling-instance metadata remain intact.
- Installed scans and row actions run in background workers; browse and installed
  lists render on demand, with bounded expansion and reused cached artwork.
  Fixed a duplicate browse request, stale-instance actions, hidden initial
  skeletons, worker-start recovery and misleading post-install failure feedback.
- Downloads use unique preparation files, validate archives and redirect hosts,
  clean failed partials and avoid overwriting shared name collisions. Cached mod
  bytes are checked against requested hashes, including cache-alias lookups.
  Path checks reject traversal and escaped profile/store directories; failed
  folder adoption retains the original and shared-store purges retain live references.
- Pack repairs stream assets and detach shared folder links before changes.
  Mod descriptors and nested-JAR scans have memory budgets. File discovery skips
  malformed/empty releases; shader setup respects the selected loader and offers
  Oculus on Forge rather than promising to convert the instance to Fabric.

## 2026-11-01 — Modpacks performance, graphical Linux setup and website recovery

- Modpacks prepares icons outside the UI lock, coalesces duplicate artwork
  requests and limits artwork workers to four. Rows reuse cached artwork and
  reject stale image callbacks. Browse and installed lists render on demand;
  each provider returns at most ten rows per page, and installed packs build
  in batches of 25. The initial skeleton stays enabled and uses stronger
  contrast, making it visible in native Flet. Refreshes preserve existing rows.
- Server and installed-modpack metadata refreshes run on coalesced background
  workers; stale selections cannot overwrite newer state. Server edits remain
  protected while loading. Public-address lookup reads only the final 256 KiB
  of its log. Server controls prewarm after first paint without network fetches.
- Added an offline graphical `Cubeon-Linux-x86_64-Setup.AppImage` with folder
  selection, progress, cancellation/error feedback and completion actions.
  Setup always uses green, independent of seasonal themes or color arguments.
  It shares the AppImage runtime and installs its own payload; application-menu
  launches select launcher mode. Fixed hidden-window reveal and confirmed exit.
  Build/release asset checks and `/linuxinstaller` download routing include it.
- Windows setup uses specific welcome/finish feedback and removes the redundant
  normal upgrade confirmation and unreliable append-mode executable probe.
  Intentional downgrade confirmation and staged rollback remain available.
- Updates perform target/busy probes, hashing, preparation and cleanup outside
  the UI lock, check disk space before writes, recheck active work before
  replacement and preserve payload ownership during cancellation. Preparation
  failures restore a retry action. Release notes stay bounded and scrollable.
- Dependency Doctor treats numeric `1.1` and `1.1.0` as equal, handles semantic
  prereleases/build metadata and permits operator whitespace. Valid Ingenium
  API no longer fails OldCannons' `>=1.1.0` constraint or triggers a download.
- Restored shared website JavaScript after a missing closure disabled download
  panes and language-choice persistence. Translation now applies body and
  attribute edits against the same original offsets, preventing broken tags
  and links. Regenerated Arabic pages, corrected locale artwork `srcset` paths,
  fixed targeted catalogue checks and made sitemap regeneration idempotent.

### Additional launcher fixes recorded from the preceding source checkpoints

- Added consistent loading/empty/retry states, retained-pane fades and
  background prewarming; saved window placement precedes splash reveal.
  Fixed Chat's UI/socket lock inversion that could leave status disconnected
  and prevent notice delivery. Existing skins, artwork and palette remain.
- Custom controls support keyboard focus and Enter/Space activation. Dialogs
  guard global shortcuts; Settings fades handle rapid reopen safely and its
  navigation scrolls independently. Long names truncate with tooltips. Optional
  launch/error sounds stay off by default and add no network or idle polling.
- Play runs Java preflight on its worker and preserves loader/icon choices.
  Installation, launch and running claims block duplicates and premature
  state transitions; early exits and rapid relaunches reconcile correctly.
  Version/profile validation rejects unsafe paths, external symlinks and cyclic
  references before writes. Deletion checks active claims and dependencies,
  runs outside the UI lock and preserves user-owned shared data. JVM probes
  cache briefly; in-memory log buffers are bounded while disk logs stay complete.

### Verification and limits

- Focused Modpacks, navigation, dependency, updater, graphical-installer,
  translation, release-pipeline, UI and smoke checks passed with Flet 0.86.5.
  Arabic catalogue validation passed all 1,211 strings; English/Arabic browser
  checks covered desktop/mobile, overflow, script execution and no-JS access.
- The rebuilt graphical installer completed an actual isolated offline
  installation, exact payload-hash and desktop-wrapper checks, and Done exit.
  Native launcher captures confirmed the visible Modpacks skeleton. Windows
  installer transaction checks passed under Wine; native Windows/macOS
  rendering and the user's exact intermittent network condition remain unverified.
- Ukrainian/Russian catalogues remain empty English fallbacks. Worker routing
  needs its own deployment. The normal workflow assigns this push's release
  version/channel; source verification is separate from completed public builds.

## 2026-11-01 — More Culling safety and Windows setup recovery

- Removed More Culling from automatic performance installs. The default suite
  retains Sodium, Lithium, ImmediatelyFast, EntityCulling and FerriteCore.
- Before Play, disable legacy Modrinth-managed More Culling once in ordinary
  profiles, preserving JAR bytes and metadata. This runs even with the client
  or performance suite disabled. Explicit new installs/re-enables, manual
  untracked jars, modpack profiles and required More Culling dependencies are
  preserved. Old automatic and browser installs share metadata, so either may
  be disabled once. Pending migrations recheck identity; errors block launch.
- Windows setup leaves its staged runtime directory before swapping files,
  retries temporary access/sharing errors for under five seconds per move,
  handles empty runtime directories and reports the failed phase/path/native
  error instead of attributing every failure to disk space or open windows.
- Rollback moves new runtime files aside and preserves previous program files
  if restoration is blocked. `Cubeon-Setup.log` retains initial and rollback
  details; corrected NSIS append positioning to avoid overwriting earlier errors.
- Added Windows installer transaction fixtures to the Windows build before
  publishing. Wine checks use real file locks and cover temporary/persistent
  locks, incomplete payloads, placement/rollback failures, backup bytes, custom
  paths, empty runtime directories, upgrades and data-safe uninstall.
- Native Windows fixtures launch setup directly with raw NSIS arguments;
  corrected a `cmd /c` quoting issue that stalled the first Windows CI run.
- Verification: performance retirement/removal 14 tests; performance/options
  100 checks; prelaunch dependencies 17 tests; lookup budget 12 checks; mod store
  27 checks; launch fixes 133 checks; updater 28 tests; release pipeline 61
  checks; installer suite including Wine 3 tests; launcher smoke 23 checks.
- No affected user's exact upstream More Culling conflict or Windows failure
  has been reproduced. Native Windows runner results are separate from Wine
  verification. This source push follows the ordinary beta channel policy;
  v1.3.38 stable remains unchanged until a later explicit promotion.

## 2026-11-01 — v1.3.38 stable promotion

- Promoted the existing v1.3.38 release to stable, preserving its tag and binaries.
- Updated homepage and download-page version labels to 1.3.38 and recorded the
  promotion in release tooling. Subsequent patch releases still default to beta.
- Enabled the download page's macOS app-bundle link; the published asset replaces
  the outdated “not available yet” placeholder.
- This metadata/website update uses `[skip ci]` and does not create a new release.

## 2026-11-01 — Motion blur, notifications, request efficiency and rendering recovery

This entry records the source and bundled-client changes included in this push.
The build workflow assigns the release version and channel. Worker changes need
their own deployment; committing them does not establish deployment health.

### Client rendering and settings

- Added optional camera motion blur to all 24 supported clients, with native
  rendering adapters, saved settings and render-thread resource cleanup.
  The effect samples the current scene with an 8 ms exposure; it does not
  accumulate previous frames or blur HUD/menu text.
- Added saved blur intensity to the K settings menu: 25–200% in 25% steps,
  default 100%. Updated all eight native menu adapters, compact layouts,
  translations and configuration validation. Changing intensity resets the
  renderer; exposure and its limit scale together.
- Fixed Fabric's `IllegalClassLoadError` for `CameraBlurRenderer` by moving
  mixin hooks into `hud.blur.mixin`, outside ordinary renderer classes.
  Native shader/pipeline setters now use parsed identifiers so Minecraft
  does not substitute its own namespace for Cubeon's shader resources.
- Integrated zoom FOV changes with blur motion calculations. Added packaged
  class/resource checks, mapped-hook checks, mouse-polling math, shader and
  lifecycle regressions. Rebuilt all 24 client JARs.
- Restored the five Small wing rigs upward by two model units. Giant wings
  and the existing textures retain their geometry and animation data.

### Launcher fixes and previews

- Fixed invisible launcher notifications by giving the card's stretched Row
  intrinsic height and mounting new hosts through the overlay parent. Added
  per-window deduplication, lifecycle cleanup and release of persistent
  notification waiters when a card is closed or evicted.
- FriendsService now delivers new notices directly to the active launcher
  window, outside its ring lock. This adds no network polling or history replay.
- Scroll following now owns asynchronous completion, skips hidden/detached
  lists and handles the exact expected listener timeout and teardown errors.
  Unrelated scrolling failures still surface.
- Crash explanations require explicit missing-entrypoint evidence before
  blaming incomplete Fabric/Minecraft files. Ordinary Knot/Minecraft stack
  frames no longer misclassify a mod mixin failure as a broken installation.
- Restyled Play with the bundled Minecraftia font and stepped SVG frame.
  Preserved launch/Cancel/Quit state and click handling; corrected Flet 0.86
  icon updates to use `.icon` so mode glyphs change correctly.
- Giant-wing launcher previews use the matching silhouette texture and four
  quads instead of 3,566 feather faces. Full geometry remains available;
  Small wings, shoulder pets and game rendering are unaffected by this preview.

### Skin and cosmetics request efficiency

- Added canonical public Worker Cache API keys, single-flight reads, ETag/HEAD
  handling and 60-second mutable/negative caches. Hash-addressed textures stay
  immutable; username face URLs use a mutable cache policy.
- Skin publishing reuses connections, coalesces work, preserves partial success,
  stops a failed batch and persists exponential backoff with jitter. It respects
  Retry-After and pauses exhausted daily write budgets until the UTC refill.
  A confirmed new identity can skip publishing an empty cosmetics selection.
- Avatar downloads are limited to four concurrent requests. Missing avatars
  and service outages have persisted cooldowns; positive faces refresh after
  six hours while retaining visible pixels.
- Peer cosmetics use five-minute positive and fifteen-minute negative caches,
  reuse cached context, share failure backoff and use a bounded request bucket,
  executor queue and cache. The two-hour fixture measured 24 refreshes versus
  120 before, an 80% reduction for that scenario.
- Managed CustomSkinLoader changes only an untouched 30-second cache default
  to 300 seconds. Custom expiry values, provider order, local skin behavior and
  the management opt-out remain respected.
- Smoke fixtures now stub skin/avatar traffic instead of contacting the live
  Worker. Cache hits still count as incoming Worker requests; the measurements
  do not guarantee a fleet-wide quota reduction.

### Missing HUD, flicker and returning performance mods

- Added explicit **Settings → Doctor → Rendering** Apply compatibility / Restore
  settings controls for the selected instance. The workaround bypasses known
  EntityCulling culling options and ImmediatelyFast enhanced batching, with
  atomic backups and restoration that preserves later user edits. Normal
  launches do not enable it automatically; FPS may decrease.
- Fixed More Culling returning after removal. Removing a performance mod now
  atomically records a profile-specific opt-out before unlinking. Play skips
  its lookup/download; disabled jars remain recognized. Explicit Mods-browser
  installs work and other instances/shared store copies remain intact.
- Failed opt-out writes retain the mod; unreadable preferences prevent automatic
  suite additions. Added regressions for repeated Play/sync, renamed manual
  jars, disabled-then-removed mods, sibling isolation and explicit reinstalls.
- The affected stable user's general entity flicker has not been reproduced on
  their machine. The stable v1.3.34 F3 HUD gate was verified separately; current
  source already contained that visibility fix before this push. OneConfig's
  separate intermittent crash investigation is paused and no fix is claimed.

### Website search visibility

- Added visible product/loader answers and FAQPage data matching all fifteen
  homepage answers. FAQ answers remain readable without JavaScript.
- Added explicit OpenAI/Claude search and user-retrieval crawler allowances,
  preserving API exclusions, plus a linked optional `/llms.txt` reference.
- Updated crawler-role and regeneration documentation. Crawl permissions and
  structured data do not guarantee inclusion or citations in ChatGPT/Claude;
  real crawler firewall access and index status require provider-side evidence.

### Verification and limits

- All 24 Gradle client builds completed and bundled/cache JAR hashes matched.
  Mod matrix: 568 checks passed. Packaged blur math covers 30–2000 FPS and
  125/1000 Hz mouse input; all eight adapter lifecycle checks passed.
- Real Fabric 1.21.11 reached a disposable world with Iris/Sodium under
  Xvfb/llvmpipe; an isolated observer confirmed blur drawing and OFF cleanup.
  Physical GPU/VulkanMod behavior and Giant-wing multiplayer visuals remain
  outside that verification.
- Native Flet 0.86.5 captures verified Play mode icons, launcher previews and
  stacked/multiline/action notifications. UI smoke: 266 checks passed; launcher
  smoke: 23 passed. More Culling removal: six tests passed; existing performance,
  prelaunch dependency, lookup-budget, mod-store and rendering recovery suites
  passed.
- Worker fixture: 80 profile requests used three KV reads. Ownership/cosmetics
  checks and skin publishing, CSL, avatar and peer-request regressions passed.
- Website SEO: ten tests passed. Browser review covered 1440/768/390/320px and
  FAQ rendering with/without JavaScript; FAQ regeneration was idempotent.
  Python syntax and Git whitespace checks passed.
