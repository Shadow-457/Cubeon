# Install cancel button (2026-09-22, opencode)

Reported: "when installing an instance of Minecraft there's no option to cancel
it". Added one.

## What changed
- `main.py`: new `progress_cancel_btn` in the Play progress row, shown while an
  install is cancellable; `on_cancel_install()` sets a per-version cancel
  `Event`; `do_install_and_launch` checks it in its progress/status callbacks
  (raising `_InstallCancelled`, which is what actually stops mll, since
  `setStatus` fires before each download) and at step boundaries. The prefetch
  honors the same event so a Play click blocked on `_install_lock` can be
  cancelled. Launch phase disarms cancellation. A fresh cancelled install's
  version folder is deleted so it can't show as "(incomplete)".
- `state["installing_version"]` is the new single source of truth for which
  version the cancel button targets.

## Verification
- `python3 tools/test_mega_smoke.py` → 16 passed, 0 failed.
- Wrote /tmp/opencode/probe_cancel.py (headless app_driver): stub
  `install_version` blocks, select uninstalled 1.21.11 via the version picker
  (Browse all versions → row), Play, then fire the tooltip "Stop this install"
  button. Result PASS: prefetch aborted with `_InstallCancelled`, only ONE
  install call total, label "Install cancelled", cancel hidden, play button
  back to "DOWNLOAD & PLAY". No committed harness (the picker + prefetch
  sequence made this awkward to fold into the existing fuzz scenarios).

## Follow-up
The user's message was cut off ("...and also"). Need to ask what the second
part was.
