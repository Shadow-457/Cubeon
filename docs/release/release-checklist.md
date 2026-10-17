# Release Checklist

## Pre-Release

### Code Quality
- [ ] All tests pass: `python tools/test_mega_smoke.py`
- [ ] Static checks pass: `python tools/test_mega_smoke.py --static`
- [ ] Worker tests pass: `cd worker && node test-worker.mjs`
- [ ] Mod compile passes: `python tools/test_mod_compile.py`
- [ ] No bare `except:` clauses
- [ ] No mutable default arguments
- [ ] Type hints on all new public APIs

### Version & Changelog
- [ ] Nothing to do for the version — CI stamps it per push
      (`tools/release_version.py stamp`). Only edit `APP_VERSION` (then
      `python3 tools/release_version.py stamp <version>`) when you want to start
      a new minor series; the tag, the app and the website text must all agree.
- [ ] Update `CHANGELOG.md` (or create if missing)
- [ ] Verify `mod/brackets.json` matches supported Minecraft versions

### Worker Deployment (if protocol changed)
- [ ] Deploy `cubeon-skins.js` to Cloudflare Workers (dashboard)
- [ ] Deploy `cubeon-invites.js` to Cloudflare Workers (dashboard)
- [ ] Deploy `cubeon-friends.js` via `wrangler` (Durable Object)
- [ ] Verify `/health` endpoints return OK
- [ ] Update `DEFAULT_API_ROOT` in `cubeon/friends.py` if URL changed
- [ ] Run protocol parity tests: `python tools/test_friends.py`, `python tools/test_invites.py`

### Mod Jars
- [ ] Build mod jars: `python tools/build_mod_jars.py`
- [ ] Verify jars in `assets/jars/` match brackets
- [ ] Test mod loads in-game: launch a profile with the mod

### Assets
- [ ] Cape PNG up to date in `assets/capes/`
- [ ] Icons present in `assets/icons/`
- [ ] Seasonal pets in `assets/pets/`
- [ ] Title image in `assets/titleimg.jpg`

## Build & Test

### Linux
- [ ] `./packaging/build_appimage.sh` succeeds
- [ ] AppImage runs: `./dist/Cubeon-x86_64.AppImage`
- [ ] UI opens, tabs switch, no errors in `cubeon.log`
- [ ] Friends connect (if worker deployed)
- [ ] Mod install works

### Windows
- [ ] `python packaging/build_windows.py` succeeds
- [ ] EXE runs (on Windows or Wine)
- [ ] UI opens, tabs switch, no errors
- [ ] Friends connect
- [ ] Mod install works

### macOS
- [ ] `./packaging/build_macos.sh` succeeds
- [ ] App bundle runs
- [ ] UI opens, tabs switch, no errors

## Post-Build Verification

### Launcher Functionality
- [ ] Launch vanilla Minecraft
- [ ] Launch Fabric/Quilt/Forge/NeoForge profile
- [ ] Install mod from Modrinth
- [ ] Install modpack
- [ ] Install resource pack/shader
- [ ] Friends: add friend, chat, invite to world
- [ ] Server tab: install Paper, start server
- [ ] Settings: RAM slider, window geometry, legacy toggle
- [ ] Seasonal: theme changes, pet toggle

### Multi-Instance
- [ ] `python tools/launch_sandbox.py "TestUser"` creates working second launcher
- [ ] Both instances can run simultaneously
- [ ] Friends work independently per instance

### Edge Cases
- [ ] No network: launcher starts, cached content works
- [ ] Corrupt config: launcher recovers with defaults
- [ ] Missing Java: helpful error message
- [ ] Disk space low: `ensure_disk_space()` warns

## Release

### GitHub Release — `git push` is the whole job
- [ ] Push to `main`: CI picks the version, tags it, builds Linux + Windows +
      macOS and publishes the release (draft → verify all 6 assets → un-draft).
- [ ] Watch the Actions run; `publish` is the job that makes it public.
- [ ] Only if you must release a number CI would not pick:
      `git tag vX.Y.Z && git push origin vX.Y.Z` (released verbatim).
- [ ] Notes come from `--generate-notes`; the in-app updater shows the first
      ~400 characters of them, so keep the commit subjects user-readable.

### Worker Deployment (if not done earlier)
- [ ] Deploy any worker changes
- [ ] Update `CUBEON_FRIENDS_API` etc. env vars if needed

### Post-Release
- [ ] Verify the release carries all six assets (the `publish` job asserts this)
- [ ] Verify update check works: `cubeon/updater.py` finds new version
- [ ] Monitor `cubeon.log` for crash reports (if crash endpoint deployed)
- [ ] Update `docs/SIMPLE_OWNER_GUIDE.md` if user-facing changes

## Rollback Plan

If critical issue found post-release:
1. **Re-run the failed job** rather than deleting anything — a re-run of the
   same push reuses its tag and version (it does not mint a new one) and
   re-drafts the release while assets are replaced.
2. **Bury it**: the in-app updater only offers releases NEWER than the running
   one, so pushing a fixed `APP_VERSION` (or just the next commit) is usually
   enough. Only make an old release "latest" again if downloads must move back —
   `gh release edit vX.Y.Z --latest` (CI never moves `latest` backwards).
3. **Delete a bad tag** only if it never shipped:
   `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`.
4. **Re-deploy** workers if they were updated.
5. **Communicate** to users via Discord/GitHub

## Version Numbering

- **Major**: Breaking protocol changes, worker API changes
- **Minor**: New features, new Minecraft version support
- **Patch**: Bug fixes, cosmetic changes

Example: `1.2.3` → `1.3.0` (new loader support) → `2.0.0` (protocol v2)