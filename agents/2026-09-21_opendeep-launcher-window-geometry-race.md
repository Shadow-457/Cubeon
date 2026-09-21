# 2026-09-21 — opencode — Launcher window opening top-left / centered despite saved geometry

## Problem
The launcher opened centered (or top-left) on every launch, ignoring the
position saved in `~/.cubeon_launcher/window_geometry.json` (e.g.
`{left:405, top:225}`).

## Root cause
This was NOT a save bug — the geometry file was correct and `_apply_real_geometry`
was being called in `_reveal_window` *before* `visible = True`. The issue is the
Flet 0.86 / GTK window-manager first-map race: setting `window.left`/`top` on a
window before it is mapped gets clobbered by the WM's default centering behavior,
so the position write succeeds but is immediately thrown away by the GTK
toplevel realization. The code was right and the window still opened centered.

## Fix
`main.py` → `_reveal_window()` now writes geometry **twice**:
1. `_apply_real_geometry()` before reveal — sets size/minimized state (unchanged).
2. After `page.window.visible = True`, re-sets `page.window.left = _gl` and
   `page.window.top = _gt` so it lands on the already-realized GTK toplevel and
   survives the WM's first-map centering.

Second write is guarded by `if not _needs_center:` (no saved position → keep
intentional centering) and wrapped in try/except (headless/test runtimes have no
real window manager). The orphaned "First successful paint" comment got
reattached.

## Verified
- `python3 -c "import ast; ast.parse(open('main.py').read())"` → syntax OK
- `python3 tools/test_ui_smoke.py --static` → 149 passed (added a new assertion
  pinning that `visible = True` precedes the post-map `left`/`top` write inside
  `_reveal_window`, so this regresses visibly instead of silently coming back).
- `window_geometry.json` still reads `(405, 225)` and the save path
  (`_on_window_event` / `_save_geometry_now`) was untouched — confirmed the bug
  was purely on the apply side.

## Note for next agent
This is a runtime/WM behavior, not a Python logic bug, so the bare-JDK self-test
can't catch it — `test_ui_smoke.py`'s source-inspection assertion is the guard.
The real proof is launching the app and watching the window open at the saved
position; I could not run the GUI here (headless), so verify visually on a real
desktop before declaring the regression closed.
