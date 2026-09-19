# 2026-09-12 - Removed chat from the in-game mod

## Ask
"remove chat from in game mod" - chat lives in the launcher's Chat tab now;
the in-game Cubeon Client screen should not duplicate it.

## What changed
All in `mod/src/main/java/com/cubeon/client/CubeonClientScreen.java`:
- Tab enum is FRIENDS, REQUESTS, ACCOUNT (CHAT removed); header/docs updated.
- Removed: the CHAT picker rows, transcript renderer (applyChat/chatTranscript),
  composer plumbing (CHAT_INPUT_MAX, submitSend), the centred chat Close button
  (chatClose), openChat/openChatFromProfile/closeChat/isChatOpen, the
  chatRevision tick-detection, and setChatFriend calls in selectTab/removed().
- The transcript's label pool is now the sync pool: chatLines -> syncLines,
  CHAT_POOL -> SYNC_POOL, CHAT_LINE_STEP -> SYNC_LINE_STEP,
  transcriptRows -> syncRows (only applySync uses it).
- Friend profile action bar is now Play / Sync / Whitelist / Remove - the
  actions array shrank from 5 to 4 slots; REQUESTS and both sub-views hide
  fewer slots. Hint/status wording dropped "chat".
- Bridge is INTENTIONALLY untouched: its chat poll stream only starts when
  setChatFriend is called, which nothing does anymore, and test_mod_bridge pins
  the Bridge. The local_api /chat endpoint is now unused by the mod but left
  in place (launcher chat does not use it either - FriendsService only).

## Verification
- tools/test_mod_compile.py: all mod sources compile clean against the
  version-stable API subset.
- tools/test_mod_bridge.py 119/119, test_mod_matrix 68/68, test_friends 48/48,
  test_friends_service 213/213, test_ui_smoke 112/112.
- tools/build_mod_jars.py rebuilt BOTH brackets (1.20-1.21 via gradle+loom,
  26 via javac) and redeployed to ~/.cubeon_launcher/cache/ AND assets/jars/.
