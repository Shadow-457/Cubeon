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
- [CONFIRMED 2026-09-05] The exe opens a window. User verified under Wine,
  and opencode reproduced: run 33980038131 launches clean (only a harmless
  `app() is deprecated` DeprecationWarning from flet 0.86 — main.py:3388
  still calls ft.app(); switch to ft.run() someday, zero urgency).
- The flet_desktop fix was necessary but NOT sufficient — a second crash
  followed: cubeon/controller.py imported fcntl (Linux-only) at module
  load. Fixed in 4f8edc1 by making the import optional (watcher inert on
  Windows), plus watchdog.terminate() no longer assumes SIGKILL exists.
  **Lesson: check every platform-specific import before shipping a
  cross-platform exe — Wine is a cheap pre-flight for this.**
- macOS build has the same fixes but remains untested on real hardware.
