# 2026-09-21 — chat tab convenience pass (drafts, jump, copy, filter, timestamps)

All five requested enhancements are in `ui/chat_tab.py`. Pure UI — no protocol
changes, no service/relay work.

## What changed
- **Drafts**: `_drafts` (canon friend -> composer text), saved on every
  keystroke (`on_change`), restored in `_select`, saved when switching away /
  on `_clear_conversation`, cleared on send. Survives tab closes within the
  session (the tab stays mounted once built).
- **Jump-to-bottom**: `_jump_row` pill above the composer, visible only while
  the view is scrolled up (`_on_transcript_scroll` sets `_stick["at_end"]` and
  toggles it), click = `_stick_bottom(force=True)`; hidden on open/clear.
- **Copy message**: every bubble is click-to-copy via the Clipboard service
  (`_copy_message`, "Message copied." status), tooltip = full date + hint.
- **Friend filter**: `find_field` above the Friends rail, client-side filter
  over `_last_roster` friends by label or ID; "No friend matches that." empty
  state; re-applies on every roster rebuild.
- **Timestamps**: `_full_date` (hover), grouped clock — only the first bubble
  of a same-side run (or day) shows the time (`with_time` in
  `_append_messages_inner`), and roster stamps use `_short_stamp` (clock
  today, "Mar 3" otherwise).

## Verification
- `tools/test_ui_smoke.py` 148/148 (hermetic HOME).
- `tools/test_friends.py` 95/95, `tools/test_mega_smoke.py` 16/16.
- `tools/test_friends_service.py`: 364 passed, **4 failed — all pre-existing**
  (`test_display_identity` in `friends_service.py`: peer_label/peer_metadata/
  status_payload identity checks; `friends_service.py` and its test file are
  untouched by this working tree — the failures predate this session).
- Also (earlier today): cosmetics open-freeze cache fix, "PREVIEW LIVE" chip
  removal, screenshot-gallery list+thumb caching, probe-skin cleanup of the
  real launcher dirs.
