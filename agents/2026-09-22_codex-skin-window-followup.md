# 2026-09-22 — skin model and window-position follow-up

Active skin model publishing now re-reads the PNG and repairs stale slim
metadata from older builds, preventing a 3px-arm skin from being advertised as
classic. Window reveal now falls back to the window manager's center operation
when xrandr cannot provide screen geometry, avoiding the Wayland top-left
default. Verified with `tools/test_skin_preview.py` and Python compilation.
