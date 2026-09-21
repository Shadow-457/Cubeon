# Chat tab: optimistic sends, working auto-scroll, emoji picker

- **Agent:** Cline
- **Date:** 2026-09-20
- **Task:** "refine the chat area; msg sending is slow (~1s); auto-scroll is
  bad; need emojis."

## What I did (all in ui/chat_tab.py, no service changes)

1. **Optimistic sends.** `_do_send` now clears the composer and appends a dim
   "Sending…" bubble the instant Enter is pressed, then runs
   `service.send_chat` on the usual background thread. The relay's echo-filed
   line replaces the pending bubble (FIFO match by text) in
   `_append_messages`, so no duplicate and no 1s dead air. A refusal
   (`send_chat` error) or 12s without an echo (`_sweep_pending` on the poll
   tick) repaints the bubble red "Couldn't send". Pending state dies on
   conversation switch (transcript rebuilds from the server).
2. **Auto-scroll fix.** `ft.ListView(auto_scroll=False)` was the root of the
   "shit" scrolling; replaced with `_stick["at_end"]` tracked from
   `on_scroll` (`extent_after < 48`). New messages animate to the bottom
   (`page.run_task(transcript.scroll_to, -1)`) ONLY when the user is already
   at the bottom — reading history is never yanked down. Opening a
   conversation force-jumps to the end.
3. **Emoji picker.** Smile button beside the composer toggles a 32-emoji
   panel (literal glyphs, no plugin), game-flavored (⛏️🧱💎🎮⚔️…). Click
   appends to the composer; panel hides on send/select/clear.
4. Shared `_make_bubble`/`_bubble_row` builders so pending/failed/normal
   bubbles render identically; module docstring documents the new rules.

## How I verified

- `python3 -m py_compile ui/chat_tab.py` OK.
- `tools/test_ui_smoke.py` 148/148 (all chat-tab source pins still true:
  shift_enter, on_submit=_do_send, your_id_text, day separators…).
- `tools/test_friends.py` 95/95. `tools/test_friends_service.py` 364/4-fails
  — verified those 4 fail identically on unmodified HEAD (pre-existing
  metadata/label suite drift, unrelated to the UI).
- Live UI check is the user's next step: reopen the launcher's Chat tab.

## Q for the next agent

`_sweep_pending`'s 12s timeout assumes the echo lands within ~2 poll ticks.
If the relay ever gets slower, the failed bubble may coexist with a late-
arriving real line — bump the timeout rather than removing the sweep.