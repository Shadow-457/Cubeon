# 2026-09-21 — probe-skin pollution + gallery speedup

## 1. Probe skins mess (caused by me, cleaned up)

My cosmetics-freeze probe seeded skins via `core.add_custom_skin` while
setting `CUBEON_HOME=/tmp/...` — but `cubeon/paths.py` computes CUBEON_HOME
from `Path.home()` and **ignores the env var** (only `CUBEON_GAME_DIR` is
env-honored). Result: ~41 "Probe Skin N" entries + files landed in the real
`~/.cubeon_launcher/skins/`, and running `tools/test_ui_smoke.py` un-sandboxed
clobbered the real `capes.json` (the harness `open(capes.json,"w")`s it
directly, no restore).

Fixed: removed all Probe rows/files + regress artifacts from the real dirs
and rebuilt `~/.cubeon_launcher/capes/capes.json` from the 8 real cape files
still on disk (atomicio). 5 real skins + 8 capes intact, active_skin untouched.

Rule for myself: sandbox launcher-adjacent work with `HOME=...` +
`PYTHONUSERBASE=<real home>/.local` (user site follows HOME, so flet needs
it), or patch module attrs like `test_screenshot_gallery.py` does. Never
trust `CUBEON_HOME` env. (Recorded in module-map as a GOTCHA.)

## 2. Gallery speedup

`ui/screenshot_gallery.py` + `cubeon/screenshot_gallery.py`:
- `list_screenshots()` memoized against the screenshots dir mtime+inode —
  re-opening Images was re-`verify()`ing every PNG (full file read) on the
  UI thread each visit; now O(1) after the first scan.
- `image_base64()` renders disk-cached in `CACHE_DIR/screenshot_renders`
  keyed by source mtime + size bucket (atomic tmp+replace); thumb render
  measured 78.6 ms first, 0.1 ms cached.
- UI caps cache-miss decodes at 3 concurrent threads (`_DECODE_POOL`) so a
  first open with many shots doesn't fire N full decodes at once.
- `delete_screenshot()` drops the file's cached renders (dir mtime bump
  invalidates the list cache automatically).
- `test_screenshot_gallery.py` now patches `_RENDER_CACHE_DIR` so it stays
  hermetic.

## Verification
- `tools/test_screenshot_gallery.py` 6/6.
- `tools/test_ui_smoke.py` 148/148 (run with `HOME=/tmp/opencode/smoke_home`
  + `PYTHONUSERBASE=/home/fuckarch/.local` — hermetic, real dirs untouched).
- Probe: first scan 8.3 ms / repeat 0.0 ms; thumb 78.6 ms / 0.1 ms cached.
- Real `skins.json` 5 entries, `capes.json` 8 entries, probe count 0.
- (Also prior: Cosmetics open-freeze fix — cached skin section rebuild — and
  "PREVIEW LIVE" chip removal from ui/skin_tab.py.)
