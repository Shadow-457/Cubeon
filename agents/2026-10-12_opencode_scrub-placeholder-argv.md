# "Invalid session" on some servers: argv scrub + plain-English diagnostic (opencode/mimo)

**Date:** 2026-10-12
**Model:** opencode/mimo-v2.6-flash-free
**Task:** "Invalid session" on some servers → fix the launch path.

## What was actually broken (and what wasn't)

**Was broken (fixed):** `minecraft_launcher_lib` 8.0's `replace_arguments()`
does NOT substitute `${clientid}` / `${auth_xuid}` — they are vanilla
placeholders tied to Microsoft-account plumbing, and Cubeon is offline-only.
On a real 1.21+ install the launch argv therefore shipped with the **literal**
strings `--clientId "${clientid}" --xuid "${auth_xuid}"` passed to the game.
Reproduced end-to-end against the machine's real
`~/.cubeon_minecraft/versions/1.21.11/1.21.11.json`.

**Was NOT broken (inherent):** the actual `Invalid session (Try restarting your
game and the launcher)` kick comes from the **client's own** session check, not
the launcher. Verified by decompiling `hie.class` (the client handshake
listener, implements `ako`) in `1.21.11.jar`:

- `hie.b(String)` calls `com.mojang.authlib.minecraft.MinecraftSessionService.joinServer(uuid, username, serverHash)`.
- An `InvalidCredentialsException` from that call maps to
  `disconnect.loginFailedInfo.invalidSession`.
- `joinServer` only runs on the **encrypted (online-mode)** login path
  (`hie.a(String, akz, Cipher, Cipher)` takes ciphers). Offline-mode servers
  never hit it.
- `hit.d()` (server-type check) returns true **only for `LAN`**, so a LAN join
  downgrades the failure to a warning and proceeds. Every other server type
  disconnects.

**Bottom line:** Cubeon hands the game `accessToken="0"` (see
`cubeon/launch.py`, the `"token": "0"` line). That token can never pass an
online-mode server's session verification, and no launcher-side argument change
can make it do so. "Invalid session" on an online-mode server is therefore
*expected* for an offline/cracked client — it is not a Cubeon bug. The fix for
a player who wants to join those servers is a legitimate account (out of scope
for this launcher).

## The fix

`build_launch_command()` (`cubeon/launch.py`) now does a final scrub pass over
the argv: any `--flag` immediately followed by a bare `${...}` placeholder is
dropped (both the flag and its value), and any stray bare `${...}` placeholder
is dropped on its own. Healthy substituted args (`--username`, `--accessToken`
`0`, `--uuid`, etc.) are untouched.

## Verification

- Added section "N. unresolved ${...} placeholders scrubbed from the launch
  argv" to `tools/test_launch_fixes.py`: mocks `get_minecraft_command` to
  return a realistic argv with `${clientid}`/`${auth_xuid}` leaked through, and
  asserts no `${` survives, `--clientId`/`--xuid` are gone, and healthy args
  remain. **101 passed, 0 failed** (was 98/0).
- `tools/test_client_json.py` 40/0 and `tools/test_mega_smoke.py --static`
  16/0 still green.
- End-to-end against the real `1.21.11` version JSON on this machine: built the
  command, confirmed `leaked placeholders: []` and no `--clientId`/`--xuid`.

## Concrete case: lemonmc.fun vs mazer.club (same day, real game log)

The player's own log (`~/.cubeon_launcher/game-072a4c9f….log`) settles it:

- **`mazer.club` WORKS.** Connect → "You are being verified" → "You have passed
  verification — reconnect to play" kick → reconnect → stays up (world map +
  chat). It's offline-mode + an antibot two-phase gate. Cubeon joins it fine;
  the only friction is the server asking for a reconnect after verification.
- **`lemonmc.fun` FAILS.** It returns the *vanilla* key
  `disconnect.loginFailedInfo.invalidSession`, ~2 s after connect (that delay
  is the client's `joinServer` HTTP round-trip to Mojang — an offline server
  never triggers it). The "You are logging in too fast" and
  `recvAddress(..) error(-104) Connection reset by peer` lines are that same
  server's rate-limiter/proxy dropping retries after the failed logins — same
  root cause, not a second bug. **`lemonmc.fun` is online-mode (directly or via
  a session-verifying proxy); no launcher change can join it.**

## Plain-English diagnostic (main.py)

Because "invalidSession" is a raw translation key that reads like a Cubeon bug,
`main.py` now passes a `log_cb=_game_log_cb` into `launch_game()`. It tails the
live game log, tracks the last `Connecting to X` server name, and on the FIRST
`loginFailedInfo.invalidSession` line fires one snackbar:
"<server> requires a premium Minecraft account. Cubeon is offline-only…". A
`shown` flag prevents repeat toasts across reconnect spam. Verified against the
real log lines: tracks `lemonmc.fun`, fires exactly once. UI smoke 176/0.

## Note for whoever's next

If a player still reports "Invalid session", it is the online-mode case above.
Check the game log for the target server: if the disconnect is the vanilla
`loginFailedInfo.invalidSession` key, the server is online-mode — inherent, not
a launch-path bug. Only if an `online-mode=false` server kicks with something
OTHER than this key would there be a real new bug to chase, and nothing in the
current code or the 1.21.11 client decompile points
at such a path.
