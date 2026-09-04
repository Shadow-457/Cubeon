# Friends CHAT tab implemented in the in-game screen (E2EE DM UI)

The Friends screen now has a working CHAT tab wired to the encrypted DM
service/bridge work that landed earlier (sender-can't-decrypt design, `/dm` +
`/chat`, Bridge chat layer). All in `CubeonFriendsScreen.java`, no new API.

## What changed (all in `mod/src/main/java/com/cubeon/friends/CubeonFriendsScreen.java`)
- Picker: rows list your friends (name + presence), one click selects, footer
  primary reads **Chat** and opens the conversation via `Bridge.setChatFriend`;
  re-clicking an already-selected row opens it too (the FRIENDS-tab double-tap
  idiom, so no single-click-open). Empty state points at the Friends tab.
- Transcript: while a conversation is open the friend rows, pager and info
  prose hide and a read-only prose transcript fills the list region, newest
  anchored at the bottom (24-label pool, wrap per line, author prefix
  `Name: text`; incoming WHITE, outgoing AQUA, offline/online picker grey vs
  white). Rendered from `Bridge.chat()` on `chatRevision()` change.
- Action bar: the four-slot bar yields to one centred **Close** that returns to
  the picker (`setChatFriend("")`).
- Composer: when open, footer becomes the existing EditBox + **Send**
  (`submitSend` -> `bridge.sendChat`, local empty/length checks, clears on
  success, worker thread like the other submits). Picker has no text box.
- Leaving the CHAT tab or closing the screen closes the conversation so the
  bridge's chat poll stream goes quiet (`selectTab`, `removed()`).
- Incoming-DM notices already flow through `screenToastSink` -> status line; no
  badge, no auto-open (unchanged). New CHAT empty-states in `emptyHead/Body`;
  header/tab-label plumbing extended to the 4th tab.

## Verification
- `tools/test_mod_compile.py` clean (stub API subset respected);
  `test_friends_service.py` 179 passed, `test_friends.py` 37, `test_mod_matrix.py`
  68, `test_mod_bridge.py` 110.
- `tools/build_mod_jars.py` rebuilt BOTH jars (gradle+loom for 1.20-1.21, javac
  for 26) and copied them to `~/.cubeon_launcher/cache/`.
- NOT done: in-game visual check (no GUI session here). Worth a look on real
  MC: transcript line colours, Close placement, and whether a long wrap line
  reads well. Relay baton: the earlier "corner icon glyph needs an in-game
  check" note is still open too - both are one GUI session to confirm.
