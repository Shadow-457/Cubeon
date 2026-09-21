# 2026-09-21 — window restored at top-left

Root cause: `window_geometry.json` had `left: 0, top: 0`, captured while the
native/Flet splash window still reported placeholder coordinates. Startup
treated that pair as valid forever. `main.py` now treats `(0, 0)` as a bad
pre-reveal capture, centers once, and ignores geometry save events until the
finished window's real geometry has been applied.

Verification: `python3 -m py_compile main.py` and `tools/test_ui_smoke.py`
(148 passed).
