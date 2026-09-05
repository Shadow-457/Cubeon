# 2026-09-05 — Frozen builds died instantly (missing flet_desktop)

## What happened
User downloaded the CI Windows exe and it closed instantly. Diagnosis from
source (no Windows machine needed):

1. `flet.app()` imports `flet_desktop` (separate wheel from `flet`).
2. The build used `--collect-all flet` only → frozen exe has no `flet_desktop`.
3. flet's `ensure_flet_desktop_package_installed()` (flet/utils/pip.py) then
   tries to **pip-install at runtime** → impossible inside PyInstaller →
   SystemExit before any window.

Second latent bug in the same path: even WITH flet_desktop collected, the
PyPI wheel ships `flet_desktop/app/` EMPTY, and `ensure_client_cached()`
downloads `flet-windows.zip` from GitHub Releases on first run — fails
offline, and surprises the first user.

## Fix (commit 07a65cd) — all five packaging scripts
- `--collect-all flet_desktop` everywhere.
- Client archive downloaded at BUILD time into the interpreter's
  `flet_desktop/app/<artifact>` (exactly where `ensure_client_cached()`
  looks first: `get_package_bin_dir()/artifact`), so runtime needs no network.
  Artifact name comes from `flet_desktop.get_artifact_filename()` (platform
  aware); Windows build pins FLET_VERSION=0.86.5 from requirements.
- `--windowed` added to Windows builds (no console flash).

## Verified
- CI run 33978721003: all 4 jobs green; log shows "+ bundled flet client
  (38 MB)".
- Downloaded the ZIP artifact and confirmed
  `Cubeon/_internal/flet_desktop/app/flet-windows.zip` (40 MB) is inside.

## Baton for next agent
The exe from run 33978721003 should be the first one that actually opens a
window — user needs to re-download and confirm on real Windows. If it still
dies: run via cmd.exe to see the traceback, and check
`resolve_assets_dir()` + the AppRun layout for Linux. macOS untested on
real hardware entirely.
