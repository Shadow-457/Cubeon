# Fabric (and every loader) install died with "FileNotFoundError: [WinError 2]" (2026-09-24)

- **Agent:** Cline
- **Date:** 2026-09-24
- **Task:** "a user's fabric mod loader doesnt work giving this error: Error:
  FileNotFoundError: [WinError 2] The system cannot find the file specified"

## Root cause (verified in the installed library, not guessed)
`cubeon/mod_loaders.install_mod_loader()` called
`loader.install(mc_version, MINECRAFT_DIR, callback=callback)` - **no `java`**.
minecraft-launcher-lib 8.0 (`mod_loader/__init__.py:202`) does
`if java is None: java = "java"`, then every loader installs by DOWNLOADING an
installer jar and EXECUTING it (`_fabric.py:42`:
`subprocess.run([java, "-jar", installer, ...])`). Cubeon ships no JRE, so on a
normal Windows box `java` isn't on PATH and the exec raises
`FileNotFoundError [WinError 2]`, which main.py printed raw under the download
button. Quilt/Forge/NeoForge have the identical shape.

## Fix
- New `mod_loaders.loader_java(mc_version, loader_id)`: resolves Java with the
  SAME logic that starts the game (Settings `java_path` -> system `java` ->
  every JVM found by mll, LOWEST sufficient major) and **verifies it exists**
  before the installer sees it. `find_java_for_version()` deliberately falls
  back to the bare name "java" so a too-old Java surfaces Minecraft's own error
  at launch time; for an install that fallback is the bug, so it is rejected
  here and replaced with "Java 17+ wasn't found... install one or set the path
  in Settings". Raises BEFORE any download starts.
- `install_mod_loader()` now passes `java=` plus the newest stable
  `loader_version=` (signature-checked, so an mll API change degrades instead
  of crashing) and uses the version id mll RETURNS, with the before/after diff
  as the fallback. It also refuses an `incomplete` profile for ANY new id, not
  just the ones containing the MC version.
- A FileNotFoundError that still escapes (Java moved between resolve and exec)
  now gets a readable line in both error surfaces: main.py's download progress
  label and the modpack install failure text.

## Verification
- tools/test_launch_fixes.py 66/0 - new section 8b, 8 checks with a fake mll 8
  loader: java is passed through, loader version pinned, no-Java fails BEFORE
  the install with a readable message, and the bare "java" fallback is refused.
- test_modpacks.py 70/0, test_ui_smoke.py 170/0, test_client_json.py 40/0,
  mega --static 15/0.
- Live on this machine: `loader_java("1.20.1","fabric")` ->
  `/usr/lib/jvm/java-17-openjdk/bin/java`; the real mll signature is
  `(minecraft_version, minecraft_directory, loader_version, callback, java)`
  and `get_latest_loader_version("1.20.1")` -> 0.19.5.

## Notes for the next agent
- **INTEGRITY: a loader install EXECUTES a jar with Java.** Any change to that
  path must pass a VERIFIED java; the bare-name fallback IS the WinError 2 bug.
- Cubeon deliberately ships no JRE - "pick the lowest sufficient Java" is the
  contract, and the launcher is the only thing that knows where Java lives.
- Artifacts in dist/ + ~/.local/opt/Cubeon/Cubeon.AppImage predate this AND the
  CurseForge browse-row work - rebuild before shipping.

## Artifacts rebuilt after this fix (2026-09-24, 10:42-10:46)
All three shipped artifacts now contain this fix AND the CurseForge row fix:
- `Cubeon-x86_64.AppImage` (319 MB, 10:42) - boot-tested: `ui_painted_ok`
  written, tray up, friends WS connected, zero CRITICAL/Traceback for the run.
- `cubeon_1.0.0_amd64.deb` (429 MB, 10:45) - same fresh AppDir.
- `Cubeon-Windows-x64.zip` (127 MB, 10:44) + `Cubeon-Windows-x64-Setup.exe`
  (114 MB, 10:46) - wine onedir + NSIS; the exe boot-tested under wine
  (painted, WS connected).
- `~/.local/opt/Cubeon/Cubeon.AppImage` refreshed (10:52), so the desktop-entry
  launcher runs the fixed build.
- No-source invariant re-checked: no `*.java`, no `templates/*.py` anywhere;
  `_internal/mod/` is `brackets.json` only; the Windows bundle carries
  `flet-windows.zip`. Build order still matters (`dist/Cubeon` is shared by the
  AppImage and Windows builds - AppImage + deb first, then Windows).
