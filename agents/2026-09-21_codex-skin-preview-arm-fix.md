# 2026-09-21 — uploaded skin preview arm geometry

Fixed the slim/Alex preview renderer in `cubeon/skins.py`: the left-arm base
layer was shifted one pixel right and the left outer sleeve was read from the
wrong x origin, clipping/misaligning arm edges. Both now use the documented
Minecraft origins (x=36 and x=52), with the unused slim column remaining on
the right. Added `tools/test_skin_preview.py` with marked edge pixels to guard
the geometry.

Verification: skin preview regression passed, `tools/test_skins_net.py`
passed, and `tools/test_ui_smoke.py` passed 148 checks.
