# 2026-09-13 — Chat tab: fix + professional pass

## Ask
The Chat tab was "too broken and raw" and should look/behave like a working
professional chat. Scope agreed with the user: land the concrete fixes, then
continue into a fuller redesign.

## Finding
Headless functional passes were already clean (`app_driver explore` 822
actions, 352/352 handlers, 0 errors), and the friends worker IS deployed
(`/claim` 405, `/name/...` 200, `/ws` 426; the local identity
`Player_33416699` resolves `online:true`). So the complaint was UX, not a
crash. The one hard functional bug found: the composer is `multiline=True`
with Flet's default `shift_enter=False`, so **Enter inserts a newline and
never fires `on_submit`** — sending only worked via the tiny button.

## What I did
Backend (`cubeon/friends_service.py`):
- `roster_payload` now decorates each friend with `last_text`, `last_ts`,
  `last_dir`, and `unread` (inbound msgs newer than that peer's read marker),
  computed from the existing `_chat` ring under `_chat_lock`.
- New `mark_read(friend)` advances a new `_chat_read` marker monotonically
  (idempotent; `_changed()` only when it moves). Extra payload keys are
  backward-compatible with the mod bridge.

UI (`ui/chat_tab.py`):
- Composer `shift_enter=True`: Enter sends, Shift+Enter newline.
- Roster rows are chat-style: online avatar ring, name, last-line preview
  ("You: ..." for outbound) or presence, right-aligned clock + accent unread
  badge; the raw ID moved to the row tooltip (still in the conversation
  header).
- Transcript: `Today`/`Yesterday`/date separators, grouped same-side spacing,
  a `.get`-guarded `mark_read` on select and every poll while open.
- Identity block: no more "You are X" / "Your ID" stack; a bordered badge
  chip for the ID and the avatar now uses the name initial (was a UID digit).
- Inline send-error line above the composer; a warning banner in the pane
  while the socket is down; connection-aware empty-state subtitle.

## Verification
- `tools/test_friends_service.py` 268/0 (new `test_chat_read_rail`, 9 checks).
- `tools/test_ui_smoke.py` 116/0 (4 new chat checks: Enter-to-send, rail
  preview/unread, day separators, mark_read).
- `tools/app_driver.py explore`: 821 actions, 351/351 handlers, 0 errors.
- `tools/app_driver.py fuzz`: 31,923 actions, 4851/4851, 0 errors/warnings.
- `tools/test_mega_smoke.py --suites` **27/0**.
- Extra probe (`/tmp/opencode/chat_probe2.py`): select renders 5 messages
  across Yesterday+Today separators, mark_read fires, send clears composer.

## Cleanup pass (later the same day)
Re-read `ui/chat_tab.py` end to end for leftovers from the 2026-09-12
name->ID rework and found two: an unused `add_btn` IconButton (dead since the
add flow became Enter-only) and `add_field` carrying `expand=True` while
sitting in a vertical scrolling `Column` (there `expand` is a vertical-fill
hint, not full-width). Removed both; an AST dead-local scan is now clean.
Re-verified: ui_smoke 116/0, friends_service 268/0, explore 823 actions
354/354 / 0 errors.

## Note for the next agent
- Not visually verified: there is no image-reading/headless renderer here, so
  the polish was reasoned from the control tree + the repo's design rules. If
  the user still calls it raw, ask for a screenshot or run
  `app_driver shots` and have them look.
- Deliberately NOT done (no backend signal): typing indicators, read receipts,
  message search. `mark_read` is the hook if receipts are wanted later.
- `ui_new/.preview.py.kate-swp` is a stray untracked editor swap file, left
  alone.
