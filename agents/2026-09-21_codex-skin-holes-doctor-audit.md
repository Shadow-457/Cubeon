# 2026-09-21 — skin holes and doctor audit

Fixed actual uploaded-sheet holes: transparent pixels in required Minecraft
base regions were reaching CSL and rendering black in-game. `skins.py` now
repairs only required base geometry from the built-in fallback before storing
or publishing a skin; outer-layer transparency and slim/Alex reserved arm
columns remain untouched. Added regression coverage for the repair.

Audited the all-content mod fixer/doctor with `tools/test_content_doctor.py`;
its full suite passes, including mods, resource packs, shaders, modpacks,
plugins, auto-repair, cache invalidation, and path safety.
