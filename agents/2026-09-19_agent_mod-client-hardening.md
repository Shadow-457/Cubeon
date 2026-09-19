# Mod client hardening

Refactored the in-game mod bridge and screen lifecycle. `Bridge` now validates
the local API token/port, reloads credentials after 401 or file changes, rejects
oversized or misclassified responses, preserves a live session through brief
`/status` failures, URL-encodes chat/sync queries, and validates event/chat
cursors. Screen notice and Sync callbacks are owner-checked during close/reopen,
and the poller can be restarted after interruption. Updated stale self-test IDs
to the 8-digit contract and rebuilt both Minecraft jars. Verified with
`tools/test_mod_bridge.py` (137), `tools/test_mod_compile.py`,
`tools/test_mod_matrix.py`, `tools/test_mega_smoke.py` (16), and
`tools/build_mod_jars.py`.
