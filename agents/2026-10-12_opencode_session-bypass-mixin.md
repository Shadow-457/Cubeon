# Client-side session-check bypass: the Yggdrasil mixin for cracked proxies (opencode/mimo)

**Date:** 2026-10-12
**Model:** opencode/mimo-v2.6-flash-free
**Task:** "lemonmc.fun is a cracked-allowed server — make it joinable."
**Follow-up to:** `2026-10-12_opencode_scrub-placeholder-argv.md` (same day).

## How this revises the previous note

The earlier note concluded "`lemonmc.fun` is online-mode (directly or via a
session-verifying proxy); no launcher change can join it" and told the next
agent to stop there. That conclusion was half-right:

- **Right:** the *launcher* still cannot make token `"0"` pass a real session
  check. Nothing in the launch path changed.
- **Incomplete:** `lemonmc.fun` is not a plain online-mode server. It is a
  **Velocity proxy** that cracked players join with other launchers — the block
  is the *vanilla client giving up client-side before the handshake finishes*,
  not the server refusing cracked accounts outright.

## The discovery

`https://api.mcsrvstat.us/3/lemonmc.fun` (queried from the sandbox, which
cannot resolve the domain directly):

- software **`Velocity`**, version `1.7.2-26.2` (protocol 776, MC 1.16–26.X)
- IP `193.123.73.195`, SRV → `lemonmc.lemonstudio.online:3007`
- MOTD: "**Premium & Cracked supported**"

A Velocity proxy with `online-mode=true` plus a cracked-bypass plugin sends an
`EncryptionRequest` to *every* client. The vanilla client then calls
`MinecraftSessionService.joinServer(...)`, which throws on Cubeon's
`accessToken="0"`, and the client disconnects with
`disconnect.loginFailedInfo.invalidSession` **before it sends the encryption
response** — so the proxy's cracked-fallback plugin never gets a chance to run.
Premium players (valid session) and *modified* cracked clients (which send the
response anyway) get in; the vanilla cracked client does not. That is why the
same server works for the user's other launchers but not Cubeon.

## The fix (mod-side, not launcher-side)

New mixin:
`mod/src/main/java/com/cubeon/client/mixin/YggdrasilSessionServiceMixin.java`,
registered in `cubeon-client.mixins.json` (`client` list).

It cancels `joinServer` at HEAD. That method only POSTs to Mojang's session
server and then throws on failure, so cancelling is a clean no-op: no POST, no
exception, and the caller (`hie.b()` in the 1.21.11 client) treats the missing
exception as success and proceeds with the handshake. The encryption response is
then sent, and the proxy's cracked-fallback can do its job.

Scope, stated plainly:

- **Client-side only.** It does not make token `"0"` pass any server's real
  check. A plain online-mode server with no fallback still kicks the player —
  just by its own check instead of the client giving up first.
- **Offline-mode servers unaffected.** `joinServer` is only called on the
  encrypted path; offline servers never send `EncryptionRequest`.
- **`mazer.club` and other working servers unaffected** — same reason.

## Build safety (why this is one shared source file)

authlib was restructured in 10.x (Minecraft 26.x): `YggdrasilMinecraftSessionService`
is gone there. Rather than splitting the source across the two build brackets
(`mod/brackets.json`: `1.20-1.21` and `26`), the mixin uses a **string target**:

```java
@Mixin(targets = "com/mojang/authlib/yggdrasil/YggdrasilMinecraftSessionService",
       remap = false)
```

- The target class is resolved at **RUNTIME**, not compile time, so the file
  never imports authlib and compiles on both brackets.
- `remap = false`: authlib is a Mojang library with unobfuscated names — there
  is nothing to remap, and loom must not touch the target string.
- On 26.x (authlib 10.x) the target is simply not found and the mixin is
  skipped (`required: false` in the config, `defaultRequire: 0` for injectors)
  rather than failing the load.

## What was built and verified

- `python3 tools/build_mod_jars.py` — the **`1.20-1.21` bracket (covers
  1.21.11, the player's version) built successfully** through Gradle+loom.
  The `26` bracket failed, but for a pre-existing **environment** reason
  unrelated to this change: Minecraft 26.x requires JDK 25 and the available
  Gradle is on JDK 21 (fails at *configuration* time, before compiling any
  source). The old 26 jar is left untouched.
- Mixin confirmed inside the built jar, and — the critical bit — the
  string-target `com/mojang/authlib/yggdrasil/YggdrasilMinecraftSessionService`
  and `joinServer` survived loom's remap to intermediary **unchanged** (they are
  unobfuscated authlib names).
- Jar is identical in `~/.cubeon_launcher/cache/`, `assets/jars/`, and
  `mod/build/libs/` (sha `ac5e7353…`). The launcher reinstalls it on **every**
  launch (`ensure_installed` runs in the pre-launch path in `cubeon/launch.py`;
  `find_jar` checks the cache first), so a rebuild is live on the next launch
  with no manual reinstall.
- Tests all green: `test_launch_fixes.py` 101/0, `test_ui_smoke.py` 176/0,
  `test_mega_smoke.py --static` 16/0, `test_mod_matrix.py` 68/0,
  `test_client_json.py` 40/0.

## Live test result (same day) — mixin works; username is the remaining lever

The player retested `lemonmc.fun` right after the build shipped. **The mixin
did its job.** The game log (`~/.cubeon_launcher/game-3bf27bdd….log`) shows:

```
[16:35:44] Connecting to lemonmc.fun, 25565
[16:35:45] Cubeon Client: skipped the online-mode session check (offline accessToken) so cracked-enabled proxies can let this player in.
[16:35:45] Disconnected: literal{You are not logged into your Minecraft account. If you are logged into your Minecraft account, try restarting your Minecraft client.}
```

The vanilla "Invalid session" key is **gone** — the client no longer gives up
before the handshake. The new kick is Velocity's own
`velocity.error.online-mode-only`. Source-confirmed in Velocity's
`InitialLoginSessionHandler.handle(EncryptionResponse)`: after the client sends
the encryption response, the proxy calls Mojang's `hasJoined`, and **204 No
Content** (no session registered — unavoidable, since the mixin skipped
`joinServer`) maps exactly to that message. So the failure moved from the
*client* giving up to the *server* deciding — which is the entire point: a
cracked-bypass plugin can only act on a connection that actually reaches it.

**The remaining lever is the username, not the code.** `shadoww_` is a REAL
premium Minecraft account (Mojang profile id `4e491dc22b654e8aa024d9ac1532f1de`).
Cracked-support proxies (FastLogin and friends) treat a premium name as
premium-only and demand a valid session, so a cracked client using that name is
kicked for impersonation even though the server advertises cracked support. A
NON-premium name — e.g. `shadow4638`, already sitting in the launcher config and
confirmed to have **no** Mojang profile — is treated as cracked and forwarded to
the backend for register/login.

**Next test (no code change):** in the Play/Account username field, switch to a
non-premium name (`shadow4638` or something fresh like `shadoww_craft`) and
rejoin `lemonmc.fun`. Expected outcomes:

- **Register/login prompt or straight in** → cracked support confirmed; done.
- **Same `online-mode-only` kick** → that entry point has no active cracked
  bypass; only the server admins can change that, and the previous note's advice
  stands for it.

Do NOT conclude "lemonmc.fun is premium-only" from a `shadoww_` test alone —
that name is premium, so the test was biased toward the premium-only path.

