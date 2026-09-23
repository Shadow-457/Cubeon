# Face avatars everywhere in chat (2026-09-22, Cline)

- **Agent:** Cline
- **Date:** 2026-09-22
- **Task:** "pfp doesn't show in chat, neither on friends' ID title nor on
  yourself" — make profile/skin faces actually render on the Chat tab.

## What I did
Root cause was two-fold:
1. The launcher never consumed the skins Worker's `GET
   /faces/<name>.png` endpoint (worker serveFace: name → pointer → uuid →
   head crop). Chat avatars were pure color-initial chips.
2. The SELF avatar fallback was `crafatar.com/avatars/<name>` which only
   resolves Mojang accounts — Cubeon's users are offline/cracked, so it
   404'd and your own card rendered as an empty circle.

Changes:
- **`cubeon/faces.py` (new):** `get_face_b64(name)` → base64 of the cached
  face PNG, else None. Mirrors `icons.py` (disk cache under
  `cache/faces/`, one background download thread, never blocks/raises)
  plus a NEGATIVE cache (`_missed`, 10-min retry) because 404 is a common
  answer for non-Cubeon names and the roster repaints every 1.5s. Name
  validation doubles as path-safety. In-flight dedupe via `_inflight` set.
- **`ui/chat_tab.py`:** `_paint_avatar` (roster rows, request rows,
  conversation header) now paints the face over the chip; `_set_you_avatar`
  keeps uploaded-pfp-first, falls back to your face then the chip. Face
  availability is a token inside `_identity_sig` and `_header_sig` so a
  face that lands on disk flips the sig and the next poll repaints it.
- **`cubeon/skins.py`:** `get_skin_face_url` now returns
  `<CUBEON_API_BASE>/faces/<name>.png` (was crafatar). This feeds the
  sidebar `CircleAvatar` and Account dialog in main.py.
- **`launcher_core.py`:** re-exports `get_face_b64` for callers.
- **`tools/test_faces.py` (new, registered in test_mega_smoke SUITES):** 11
  checks — URL validation/shape, miss→None→one scheduled download, cached
  bytes served, 404 negative-cache (no request storm), in-flight dedupe.

## How I verified
- `python3 tools/test_faces.py` → 11 passed, 0 failed.
- `python3 tools/test_ui_smoke.py` → 148 passed, 0 failed (builds the real
  chat tab headless, so `_paint_avatar`/sigs run against stubs).
- `python3 tools/test_friends.py` → 95 passed; `test_skins_net.py` all green.
- `test_friends_service.py` 364/4 — verified PRE-EXISTING via a git worktree
  at pristine HEAD (identical 364/4, same 4 labels).
- `tools/test_mega_smoke.py --suites` full run: base sections green; of the
  2 sub-suite exits, BOTH verified pre-existing on a pristine-HEAD git
  worktree (test_friends_service 364/4 and test_wedge_watchdog 8/1 —
  identical labels/counts at HEAD, unrelated to this change; wedge watchdog
  also hangs at session end at HEAD, needing pkill).

## Notes for the next agent
- `cubeon/faces.py` never touches the network on the caller's thread; a
  miss returns None immediately and schedules one download. Anything
  listing Cubeon players can reuse `get_face_b64` + a repaint-sig token.
- Test isolation: faces cache comes from `Path.home()`; set
  `os.environ["HOME"]` BEFORE `cubeon` imports (the test_skins_net.py
  pattern). Setting a CUBEON_HOME env var does NOTHING — paths.py ignores
  it (test_friends.py patches module attrs instead).

## Question for the next agent
Friends' uploaded profile pictures (profile.py) still never leave their
machine — only skin faces do. Should the identity API (heartbeat payload)
carry a `pfp` hash so the launcher can show a friend's chosen pfp, or is
skin-face-as-avatar the intended ceiling for chat?