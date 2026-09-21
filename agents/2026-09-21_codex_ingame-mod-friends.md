# 2026-09-21 — in-game Friends cleanup

Removed the in-game Account tab and its account-only prose/action handling.
The Friends add field now accepts 8-digit Cubeon IDs as well as names, so the
launcher bridge can resolve IDs; invalid or nonexistent IDs are surfaced by
the existing launcher error/system-notice path. Sync is now disabled for an
offline friend with an explicit tooltip, and the offline hint no longer says
Sync still works.

Verification: `python3 tools/test_mod_compile.py` passed all mod sources;
`python3 tools/test_mod_bridge.py` passed 146 checks; `python3 tools/test_ui_smoke.py`
passed 148 checks. The full Gradle build was unavailable in this environment
(native-platform / wildcard-IP initialization failure).
