# 2026-09-12 - 12-digit chat UID: verified end-to-end, fixed int zero-pad

## Ask
"chat auto gives the user a uid, 12 numbers, first user 000000000001, add
friends by uid, name/secret don't matter."

## Finding
Already implemented in the working tree (client + worker + UI):
- `cubeon/friends.py`: `_UID_RE` = exactly 12 digits, `UID_WIDTH = 12`,
  `canonical_uid()` / `format_uid()` / `current_uid()`.
- `worker/cubeon-friends.js`: server assigns a sequential uid on first claim
  (`nextUid()` starts at 1, `uidStr` zero-pads), `GET /uid/<uid>` resolves it,
  add-by-uid frames resolve via `nameByUid`.
- `cubeon/friends_service.py`: `FriendsService.uid()` reads the identity file.
- `ui/chat_tab.py`: shows "You are ... ID <12 digits>", roster rows show each
  friend's ID, add-friend field validates with `canonical_uid` and sends by uid.

## What changed
One bug: `canonical_uid(1)` returned None (int was stringified but never
padded before the 12-digit regex). Fixed to `str(uid).zfill(UID_WIDTH)` for
ints only - string inputs like "42" stay rejected so a typo can't silently
match a different user's ID.

## Verification
- `tools/test_friends.py` 48/48 (was 47/1 - the "accepts an int and zero-pads"
  check now passes).
- `tools/test_friends_service.py` 213/213, `tools/test_ui_smoke.py` 112/112
  (includes the chat-tab-shows-12-digit-ID invariant).

## Note for next agent
UIDs are server-assigned on first successful claim; until the friends worker
is deployed (see worker/README.md), the tab stays on "Getting your ID...".
