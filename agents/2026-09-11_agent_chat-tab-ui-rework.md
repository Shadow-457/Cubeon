# 2026-09-11 — Chat tab UI rework

## Ask
"the chat area ui is shit" — rebuild the launcher Chat tab's presentation.

## What I did
Rewrote the presentation half of `ui/chat_tab.py`; the entire service /
threading / identity model is unchanged (still `FriendsService` on its own
daemon poll thread through `thread_safe_ui`).

Layout before → after:
- Left rail (300→290): removed the stacked "Your name"/"Add friend" section
  labels, the always-on "No pending requests." line, and the green presence
  text in favor of a clean header. Now: "Chat" + connection dot/text, an
  identity avatar + "You are …", rename field, add-friend field with a
  person-add prefix icon, Requests section that only appears when non-empty,
  then Friends.
- Right pane: padded conversation header with the friend's avatar + presence,
  a centered empty state (icon + two lines) instead of a hint glued under the
  transcript, and a rounded composer with a square accent send button.
- Messages: bubbles now hug their text (width from the longest line, cap =
  half the window) instead of every bubble being a fixed 380px slab; "mine" is
  a faint `ACCENT_TINT` wash (was a solid green slab with dark text); theirs is
  `SURFACE_HI`. Message + name text uses the body font, not mono. Timestamps
  stay small/faint.
- Avatars: stable per-name color from `theme.AVATAR_COLORS` at 16% fill, so
  the roster has identity without adding color noise, and green stays semantic.
- Remove-friend icon is `TEXT_DIM` at rest, `DANGER` on hover.

## Verify
- `python3 -m py_compile ui/chat_tab.py`.
- Headless harness (`/tmp/opencode/chat_harness2.py`) builds the live tab with
  a stub `FriendsService`, triggers the roster render, selects a friend, and
  appends messages — no exceptions.
- `tools/test_ui_smoke.py` 97/97 (the four chat invariants still hold:
  exists+wired, `service is None` notice, daemon poll, rename via
  `rename_unique`/`name_base`).
- `tools/test_friends_service.py` 213/213.

## Note for next agent
- `ui/chat_tab.py` still takes the full fixed `**THEME` kwarg set; new tokens
  are imported directly from `cubeon.theme` (do NOT add keys to `THEME`).
- Message dedup relies on the SERVICE honoring `chat_payload(name, since)` —
  `_append_messages` itself does not filter by seq (it only tracks `last_seq`).
  A test stub that ignores `since` will double-render; that's expected.
