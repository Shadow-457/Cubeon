[Documentation](../README.md) / Development

# Testing

Most checks are standalone scripts in `tools/`. Run them with the Python
environment from [Development setup](setup.md), from the repository root.
They report failures and return a nonzero exit status; pytest is not required.

## Smoke gate

```bash
python tools/test_mega_smoke.py
```

The default gate compiles Python source, checks imports and contracts,
examines control flow, and exercises the UI with headless fixtures.
It does **not** run every regression script.

| Command | Scope |
| --- | --- |
| `python tools/test_mega_smoke.py --static` | Source, imports, and contract checks without the runtime pass |
| `python tools/test_mega_smoke.py --suites` | Gate plus its registered regression suites |
| `python tools/test_mega_smoke.py --json` | Default gate with a JSON report |

The registered suite list is `SUITES` in `tools/test_mega_smoke.py`.
Additional test scripts exist outside that list.

Reproduce source-launch failures in a fresh launcher process after edits.
Python keeps imported modules in memory; a later import can otherwise combine
new callers with an older function signature. The source runtime guard may
select `.venv` or `.venv-build`; also run the affected suites with the
interpreter printed at startup when it differs from the release Python.

## Focused checks

Start with the area your change affects. These are examples, not a complete
catalog; the scripts in `tools/` are the current inventory.

| Area | Scripts |
| --- | --- |
| UI construction | `test_ui_smoke.py`, `test_version_ui.py`, `test_toast.py`, `test_render_compat.py` |
| Instance storage/migration | `test_instance_storage.py`, `test_instance_game_dirs.py`, `test_modpack_integrity.py` |
| Navigation and input | `test_tab_navigation.py`, `test_keyboard_shortcuts.py` |
| Motion and scrolling | `test_motion.py`, `test_scrolling.py` |
| Artwork and avatars | `test_mod_ui_stability.py`, `test_chat_avatar_stability.py`, `test_faces.py` |
| Cosmetics | `test_appearance_preview.py`, `test_cosmetic_preview.py`, `test_cosmetic_packages.py`, `test_capes.py`, `test_skins_net.py`, `test_cosmetics_store.py`; installed-game probe: `test_cosmetic_store_native.py` |
| Mods and packs | `test_modpacks.py`, `test_mod_store.py`, `test_loader_content_rules.py`, `test_perf_mod_removal.py` |
| Automatic modpack preservation | `test_modpack_integrity.py`, `test_perf_loader_support.py`, `test_game_feature_switches.py`, `test_modpack_client_mods_errors.py` |
| Mod compatibility and launch override | `test_content_checks.py`, `test_mod_prelaunch_dependencies.py`, `test_mod_resolver.py`, `test_launch_claim.py`, `test_play_backend_audit.py` |
| Combined mod catalogue | `test_mod_catalogue.py`, `test_mod_search.py`, `test_mod_detail.py`, `test_content_install_feedback.py`, `test_mods_management_ui.py` |
| Horizon content mods for Rust | `test_rust_mods.py`; `test_rust_engine_native.py --content-mod /path/to/adapted.hmod` with a matching installed binary/resources |
| Content isolation | `test_content_instance.py`, `test_instances.py` |
| Friends and chat | `test_friends.py`, `test_friends_service.py`, `test_chat_optimistic.py` |
| Local bridge and mod | `test_mod_bridge.py`, `test_mod_compile.py`, `test_mod_matrix.py` |
| Fabric 26.3 LOD | `test_lod.py` for core algorithms/settings, transparent boundaries and bounded cache residency; `test_lod_native.py` for CPU/GPU terrain, planted-ground coverage, composition, near occlusion, fog, live status, freeze and disable |
| Full Bright and keystrokes | `test_full_bright.py` (`--targets` checks cached APIs, `--jars` checks shipped fixes), `test_hud_debug_visibility.py`; `capture_full_bright.py` uses isolated cached games on Xvfb |
| Launch and downloads | `test_version_integrity.py`, `test_launch_fixes.py`, `test_net.py` |
| Release tooling | `test_release_version.py`, `test_release_pipeline.py` |

Keep declared client mixins in `tools/build_mod_jars.py`'s `REQUIRED_ENTRIES`.
`test_mod_compile.py` checks this contract, and `test_mod_matrix.py` audits the
shipped archives. Rebuild through the mod builder after changing game sources
so packaged JARs carry the new hooks.

The compatibility suites exercise the real guarded launch block: default
checks block before staging, while **Run anyway** consumes one in-memory
approval for the exact instance, mod snapshot and issue list. Changed files,
new runtime issues, expired approvals and another instance must fail that
match. Forge/NeoForge bracket ranges use `cubeon/maven_versions.py`, following
Apache Maven 3.8.8 `ComparableVersion`; Fabric operator predicates retain
their semantic prerelease rules. Include a real descriptor fixture for fixed
build suffixes such as LionfishAPI `2.4-Fix`, Create `0.5.1.j` and Flywheel
`0.6.11-13`, plus exact/upper-bound failures. Forge bare versions are Maven
recommendations; required dependencies must still be present. Metadata fixtures
cover signed manifests larger than 1 MiB while limiting the main section to
64 KiB, unfolded main-section versions, ignored per-entry attributes and
Ars Énergistique 1.2.0's unscoped `[[dependencies]]` array (ignored by Forge's
NightConfig lookup). Preserve scoped primary/secondary requirements. Pin tests
must prove an older release is selected and incompatible pins fail instead of
falling back to latest.

Pack preservation fixtures install author-selected JARs on Fabric, Quilt,
Forge and NeoForge, then repeat automatic preparation and the actual launch
FPS block. Assert unchanged JAR bytes/state and no extra downloads or automatic
dependency repair, even with legacy provider receipts. Cover missing, relocated,
corrupt and hidden pack markers; an instance's pack ownership is sufficient.
Explicit Mods installs still work. Skin opt-in restores Cubeon's setting backups
while respecting manually disabled copies and the independent Client switch.

For example:

```bash
python tools/test_chat_avatar_stability.py
python tools/test_chat_optimistic.py
```

Worker route and storage tests use Node.js and stubbed services:

```bash
node worker/test-worker.mjs
node worker/test-skins-cache.mjs
```

Java compile checks need a JDK with `javac`. Stub compilation is not a
replacement for building the mod jars or testing them in Minecraft.

## Isolation

Tests that write launcher state should call `_sandbox_home.isolate()` before
importing modules that resolve paths. Use the existing fixtures to stub
network requests and child processes. `CUBEON_GAME_DIR` isolates game files,
not every file under the launcher's home directory.

Not every tool is headless or offline. Visual tests and
`test_wedge_watchdog.py` can start real desktop clients. Jar assembly and
deployment tools may need network access. Check a script's prerequisites
before running it in automation.

## Adding a regression test

- Add `tools/test_<feature>.py`, following the adjacent standalone scripts.
- Add its explicit `.gitignore` exception: `/tools/*` otherwise keeps new
  local scripts out of Git and the CI checkout.
- Make failures produce a nonzero exit status.
- Use temporary directories and deterministic service fixtures.
- Add the script to `SUITES` if it belongs in the extended smoke gate.

For a UI stability fix, assert control identity or emitted updates as well
as displayed values. Equal text does not prove that an image stayed mounted.

## CI and manual checks

The Python test loop, exclusions, and platform jobs are defined in
[`.github/workflows/build.yml`](../../.github/workflows/build.yml).
CI is not identical to the default smoke gate.

The Ubuntu job runs `tools/test_*.py` with a fresh `CUBEON_GAME_DIR` for each
script. Its explicit exclusions require separate local fixtures:

| Excluded checks | Prerequisites |
| --- | --- |
| `test_visual_*.py`, `test_wedge_watchdog.py` | A graphical desktop and the native Flet client; these inspect actual windows and recovery behavior. |
| `test_cosmetic_elytra_native.py`, `test_live_cape_native.py`, `test_client_263_native.py`, `test_gif_capes_native.py`, `test_lod_native.py` | Installed compatible Minecraft/Fabric, built companion JARs, a matching JDK, cached game dependencies and a graphical display/OpenGL driver. Use isolated game fixtures. |
| `test_rust_engine_native.py` | Built native Rust executables, matching prepared local resources and a working graphics backend. Resource preparation needs Java 25. |
| `test_rust_profile_native.py` | Compiled Rust libraries for the selected `--profile` (`fast` or `release`) and `rustc` matching their build toolchain. |
| `test_camera_blur_gpu.py` | Linux EGL/OpenGL with a working driver and PyOpenGL; it executes production shaders and reads back pixels. |
| `test_webdoctor_browser.py`, `test_website_browser.py` | Playwright and Chromium installed locally, or `CUBEON_TEST_CHROMIUM` pointing to a compatible browser. |

These exclusions do not disable the companion compile/archive, shader lifecycle,
website SEO, or Rust backend unit checks. Run a native or browser
script explicitly once its prerequisites are available, and report its result
separately from the headless CI gate. `--suites` has its own registered inventory;
the workflow exclusion list does not automatically apply to that command.

Report exact commands, failures, and skips. A passing headless run does not
establish desktop frame rate, window visibility, or platform packaging.
Use [Windows smoke testing](../release/windows-smoke-test.md) and the
[release checklist](../release/release-checklist.md) for those checks.

The interim LOD engine is restricted to the `lod-26.3` source/resource overlays.
Its native probe copies a complete save and uses separate settings/cache paths;
it does not edit the installed world or replace installed renderer mods. Select
the profile, runtime, Java home, save name, Sodium and candidate client with its
CLI options. This pixel test is not an FPS benchmark. Iris shader integration
and performance certification remain unfinished.
Use `--no-sodium` to verify normal world startup with LOD inactive when that
optional renderer is absent.

Minecraft 26.3's RenderPearl `RenderPass.draw` takes `(vertexCount,
instanceCount, firstVertex, firstInstance)`. Use `AtlasIds.BLOCKS` for block-atlas
lookup, and include `GpuTexture.USAGE_COPY_DST` on textures cleared by command
encoders. Compiling with an older draw-call convention can succeed while
submitting zero vertices; native colour/depth readback guards this failure.

LOD's nearby full-detail radius is a horizontal terrain cutoff, separate from
the camera-space near clipping plane. Preserve the camera projection's X/Y
mapping and use a close near plane for the far projection. The native planted
ground fixture checks visible points outside the horizontal cutoff but inside
the former clipping plane, and requires complete CPU/GPU depth parity.

Transparent plants and fluids cannot hide an adjacent opaque horizontal face.
When LOD has terrain ready, its fog hook extends only the render-distance fog;
weather, environmental, sky and cloud fog retain their vanilla values. LOD uses
the same environmental fog in its shader, and disabling it restores the normal
render-distance fog. Cache residency evicts the farthest summaries first and
defers their disk reload until the camera moves, preventing stationary churn.
