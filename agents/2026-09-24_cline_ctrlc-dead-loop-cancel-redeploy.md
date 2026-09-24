# Ctrl+C dead-loop crash + cancelled request coming back, artifacts rebuilt (2026-09-24)

- **Agent:** Cline
- **Date:** 2026-09-24
- **Task:** (1) `RuntimeError: Event loop is closed` / `cubeon.fatal CRITICAL`
  after "cubeon: quit from tray" + ^C; (2) a cancelled outgoing friend
  request reappears when the launcher is reopened; (3) afterwards rebuild the
  .deb, .exe and AppImage.

## 1. Ctrl+C after the session ends (main.py)

flet installs `exit_gracefully` for SIGINT+SIGTERM while the app runs and
never removes it; it pokes the app's asyncio loop, which is CLOSED once
`ft.run` has returned. The ^C therefore raised from INSIDE the signal
handler at `_ct.join(timeout=3.0)` and escaped `_session_loop()` as
`cubeon.fatal CRITICAL`. Fixes: `_reclaim_session_signals()` runs immediately
after every `_run_flet_once()` return (first press = set the tray quit event,
second press = `os._exit(0)`); the parked wait polls at 0.5s (it only SETS
the event now, and Tray Open still wakes instantly); the in-`ft.run` race is
caught by its exact message. Guard: tools/test_ui_smoke §4d (10 checks,
including a real SIGINT/SIGTERM fired at the test process).

## 2. Cancelled request came back (Worker was never deployed)

`worker/cubeon-friends.js` already deleted BOTH directions in `onDecline`
(2026-09-23), but the deployed Worker still ran the one-directional DELETE,
so a requester's Cancel deleted nothing server-side and the request came back
on the next roster/relaunch. Deployed it
(`npx wrangler deploy -c wrangler-friends.toml`, version
6514cc53-6a5c-4167-acac-9a2b63e4e58f) and proved it live with a two-identity
probe (add -> cancel -> both rosters clean -> reconnect -> still clean). Also
repaired `worker/test-friends-rooms.mjs`, which had been failing on stale
12-digit UIDs (worker is 8-digit), and added an executed requester-cancel
block, so the Hub harness is green (47/0) and actually runs those semantics.
Client-side hardening: `FriendsClient.decline_request` drops the name from
the cached roster and persists `friends_cache.json` (guard: tools/test_friends
"durable cancel" block, 7 checks). Stale `_canceled` comments in
`ui/chat_tab.py` updated.

## 3. Artifacts rebuilt (dist/)

- `Cubeon-x86_64.AppImage` (319 MB) - booted it, UI painted, no tracebacks.
- `cubeon_1.0.0_amd64.deb` (429 MB) - built from the same fresh AppDir.
- `Cubeon-Windows-x64.zip` + `Cubeon-Windows-x64-Setup.exe` (114 MB) - wine
  onedir build (`wine ~/winpython/py311/python.exe packaging/build_windows.py`
  works unchanged) + NSIS; the exe booted under wine, painted the UI, zero
  CRITICAL/Traceback. `Cubeon-Windows-x64-single.exe` (Sep 20) is legacy and
  is NOT what /windowsdownload serves - left untouched.
- `~/.local/opt/Cubeon/Cubeon.AppImage` refreshed, so the desktop-entry
  launcher now runs the fixed build.
- Order matters: `dist/Cubeon` is shared by the AppImage and Windows builds;
  run `build_appimage.sh` (+ `build_deb.py`) before the Windows onedir.

## Verification

- tools/test_ui_smoke 170/0 (was 160), tools/test_friends 104/0 (was 97),
  worker/test-friends-rooms.mjs 47/0 (was broken), mega_smoke --static 15/0,
  test_chat_optimistic 16/0, test_faces 12/0, test_friends_service 368/4 - the
  4 failures are the known pre-existing HEAD ones (confirmed identical in a
  pristine worktree).

## Note for the next agent

- A request that was cancelled BEFORE the 2026-09-24 deploy still has a real
  server row: the user must cancel it once more (or have the other side
  decline) - the server is authoritative and the launcher honestly shows it.
- Durable facts were added to agents/docs/module-map.md ("Post-session signals
  + friends-hub harness (2026-09-24) - INVARIANTS").
