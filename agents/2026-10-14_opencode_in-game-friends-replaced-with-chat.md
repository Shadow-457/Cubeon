# 2026-10-14 — In-game mod: friends/connection features removed, chat screen added

## Ask
"remove the whole friends stuff from the Cubeon client, like completely remove
it, the connection and stuff, but add a chat area with friends where we can
chat and show same chat as the launcher."

## What changed
- **`CubeonClientScreen.java` rewritten (1609 → 1038 lines)** as a chat-only
  screen: friends picker (presence rows, double-click opens) → transcript
  (prose, newest at bottom, incoming WHITE/outgoing AQUA) + composer
  (EditBox/Send). Everything else is gone: FRIENDS/REQUESTS tabs, add-by-ID,
  accept/decline, Play/Invite/Join/Ask-to-join, the session banner and its
  Cancel/Retry, the worldgate + join-password prompts, Sync (compare/fix/
  download), Whitelist, Remove. Same cross-era widget rules as before (no
  render/keyPressed overrides, widgets mutated not recreated, workers never
  touch screen state).
- **`Bridge.java` pruned (1454 → ~1290 lines)**: `Session`, `parseSession`,
  `SyncReport`, the `/sync` + `/status` poll streams and 15 management actions
  deleted. `Snapshot` lost requestsIn/Out + session. `sendChat` (`POST /dm`) is
  the only action left. Chat poll stream (`/chat`) unchanged — that is what
  makes in-game chat and the launcher's Chat tab the SAME conversation (both
  ride one `FriendsService`; E2EE untouched).
- Corner icon + mixins kept (relabelled "Cubeon Chat", `canInvite` param
  dropped), toasts, `[Cubeon]` tab tag, WorldPlayers, stale-jar tripwire kept.
- `fabric.mod.json` description updated; `mod/tools/SelfTest.java` dropped the
  session section (121 checks green).

## Baton from the previous agent (2026-10-14 fix-all-bugs note) — DONE
`YggdrasilSessionServiceMixin` is now registered in both `MOD_SOURCES`
(tools/test_mod_compile.py) and `REQUIRED_ENTRIES` (tools/build_mod_jars.py),
and the compile stub's `@Inject`/`@Mixin` grew a `remap()` attribute —
`test_mod_compile.py` is fully green for the first time since the cracked-proxy
mixin landed.

## The 26.x jar is BUILT again (was blocked since 2026-10-05)
- Temurin JDK 25 in `~/jdks` had been a truncated unpack (86 MB, no libjli);
  re-downloaded from Adoptium, sha256-verified.
- The 26.1.2 client jar was missing from `~/.cubeon_minecraft/versions/`;
  fetched from piston-meta (sha1-verified) so the javac path can compile.
- `LIB_PREFIXES` in tools/build_mod_jars.py gained `jspecify` and `fastutil`
  (Mojang's 26 classes carry jspecify annotations and fastutil maps; javac
  refuses to read them without those jars on the classpath).
- Both `cubeon-client-1.0.0+mc1.20-1.21.jar` and `cubeon-client-1.0.0+mc26.jar`
  rebuilt and verified, deployed to `~/.cubeon_launcher/cache/` and
  `assets/jars/`.

## Push + read parity (same session, user request)
- Committed 041436b and pushed to origin/main with the user's identity
  (Shadow-457 <hamza1tan123456@gmail.com>). NOTE: this environment injects
  `user.name=zwork`, so the commit needed explicit
  `git commit --amend --author=...` + GIT_COMMITTER_* env; a bare commit comes
  out authored as zwork <zwork@local>.
- `FriendsService.chat_payload` now calls `mark_read(peer)` on both of its
  return paths (first page + incremental poll): the in-game screen polls
  /chat while a conversation is open, and without this, reading in Minecraft
  left the launcher's unread badge lit. Guard added to test_chat_http
  (373 checks now). Stray personal PDF
  "Security - My Account Panel - Namecheap.com.pdf" deliberately left out of
  the commit.

## Verification
- `tools/test_mod_compile.py` clean (stub + all sources).
- `tools/test_mod_bridge.py` 121/121; `test_mod_matrix.py` 68/68;
  `test_friends_service.py` 372/372; `test_friends.py` 104/104;
  `test_chat_optimistic.py` 16/16; `tools/test_mega_smoke.py --suites`
  green except `test_wedge_watchdog.py` (4/9) — **pre-existing, fails
  identically on a stashed clean tree**; it spawns real GUI clients and this
  box has no display session.
- NOT verified in-game: no GUI session here. One real launch should confirm
  the picker/transcript layout and that Send lands on both ends.

## Environment note for the next agent
The workspace file-write guard false-positives on `Bridge.java` (it contains
the local-API token loader — the JSON key "token" — and used to contain the
worldgate "password" field). The user approved shell-based edits for that file;
I used anchored Python replacements that assert every match.
