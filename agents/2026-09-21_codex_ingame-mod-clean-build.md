# 2026-09-21 — clean in-game mod removal and JAR rebuild

Removed the remaining Account-tab references from the shared screen/bridge
comments and self-test wording, fixed the stale offline hint so it agrees with
the disabled Sync button, and rebuilt both bracket JARs. Verified outputs are
in `assets/jars/` for Minecraft 1.20–1.21 and 26.x.

Verification: `tools/build_mod_jars.py` completed both builds and copied both
assets; `tools/test_mod_compile.py` passed; `tools/test_mod_bridge.py` passed
146 checks; `tools/test_mod_matrix.py` passed 68 checks.
