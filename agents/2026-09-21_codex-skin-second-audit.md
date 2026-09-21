# 2026-09-21 — skin and in-game second audit

Fixed two additional production issues: custom skin uploads and CSL mirror
writes now use temporary files plus atomic replacement, preventing preview or
the game from reading a partially-written PNG; and the in-game Sync view now
closes immediately when the selected friend goes offline, instead of leaving
a stale compare/download surface active. Rebuilt both JAR brackets into
`assets/jars/`.

Verification: skin preview, skin-net, and cape tests passed; mod sources
compiled; UI smoke passed 148 checks; both mod JAR builds completed and were
verified/copied.
