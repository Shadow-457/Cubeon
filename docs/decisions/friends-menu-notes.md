# Cubeon Friends, end-to-end research notes (launcher -> bridge -> Worker -> in-game mod)

- **Agent:** opencode (deepseek-v4-flash)
- **Date:** 2026-09-03
- **Task:** "everything the friends mod" — read the whole friends stack and leave
  full summary notes in `agents/` for the user to review and fold in later.

## TL;DR

There is no Friends *tab* anymore. The launcher owns all friends state headlessly
(`FriendsService`, `cubeon/friends_service.py`); the UI is a small Fabric mod
(`mod/`) that draws Minecraft's own widgets and polls a token-authenticated
localhost HTTP bridge (`cubeon/local_api.py`); the backend is a Cloudflare
Worker + one Durable Object (`worker/cubeon-friends.js`). The launcher drops the
right mod jar into the profile right before every launch (`cubeon/launch.py`
`launch_game()`), so the in-game Friends button "just exists". This note maps the
whole thing file-by-file so later agents/user can navigate without re-reading
every source.

Verified by source reading + `tools/test_friends_service.py` (136 passed) and
`tools/test_friends.py` (37 passed). Not verified in a live game (launcher not
running) — same caveat as prior notes.

## The stack, file by file

### 1. Identity (launcher-side, `cubeon/`)
- `cubeon/config.py`: `ensure_auth_key()` — one durable per-machine account
  (secret_token + public_uuid) minted once. A Cubeon name is a *public handle
  over this one secret*, which is why a rename keeps the same account/uuid.
- `cubeon/friends.py`:
  - Name rules: `/^[A-Za-z0-9_]{3,16}$/`, case-insensitive-unique (canonical =
  lowercase), reserved set `{cubeon, admin, system, server, moderator, mod,
  staff}` (`friends.py:144-173`). Same constants mirrored in the Worker
  (`worker/cubeon-friends.js:64-67`), asserted by `test_friends.py`.
  - `identity.json` (0600) holds `{name, secret, uuid}`; secret = capability.
    Server stores only SHA-256 (so a DB dump leaks nothing replayable).
  - Claim via HTTP `POST /claim` (`friends.claim()`, idempotent — re-claiming
    your own name is how you re-verify and how **rename** works).
  - `FriendsClient` (`friends.py:409-708`): threaded `websocket-client` app
    (daemon thread `cubeon-friends-ws`), reconnect backoff `[1,2,5,10,20,30]`,
    auth secret sent as the **first WS frame** (never in URL → no request logs).
    `ping_interval=25` keeps it alive past Cloudflare's idle timeout. Roster
    cached to `friends_cache.json` for instant first paint.
  - Protocol `T_*` constants are the single source of truth; `test_friends.py`
    reads the Worker source and asserts parity.

### 2. The headless owner (`cubeon/friends_service.py`, 1659 lines)
`FriendsService(cfg, state, client)` — created once in `main.py:2332-2336`,
started at boot, lives for the whole process. `cfg`/`state` are held **by
reference** so a Play-tab change mid-session is picked up.
- `start()` idempotent: binds client callbacks, runs one stale-P2P-session sweep
  (`p2p.cleanup_stale_sessions()`), then registers bridge providers and starts
  `local_api` (providers *before* `start()`, so a polling mod never sees 503).
- Replacements for the dead Flet UI: `_notify()` appends to a bounded 200-event
  ring (`events_since(since)`, negative cursor = "first sync, no backlog" — a
  fresh mod must not replay an hour of old toasts); `_changed()` bumps a
  revision counter the mod's poll can detect.
- Read models: `roster_payload()` (GET /friends) and `status_payload()`
  (GET /status, `{}` when idle; quality line only when connected/launching).
- Actions all reachable from the bridge: `invite` (host), `join`, `cancel`,
  `retry`, `add_friend`, `accept`, `decline`, `remove`, `set_whitelisted`,
  `rename`. Every path is a dict `{ok, error}`.
- Client callbacks (`_on_state`…`_on_signal`) fire on the WS thread and are kept
  short; anything slow (STUN, hashing mods/assets, launching MC) goes to a named
  daemon worker thread. `_on_signal` (`friends_service.py:1401-1659`) is the P2P
  signalling router (`p2p_offer/answer/use_relay/use_minekube/modlist/assetlist/
  modreq/modchunk/assetreq/assetchunk/relay_chunk`), with legacy-voice fallback
  to `cubeon/voice.py` at the end.
- `_LOCAL_API_BINDINGS` (`friends_service.py:113-128`) maps local_api setters →
  service methods; missing setters are skipped so the module tolerates an older
  bridge.

### 3. The localhost bridge (`cubeon/local_api.py`, 317 lines)
- `ThreadingHTTPServer` on `127.0.0.1:0`, random token written atomically to
  `~/.cubeon_launcher/local_api.json` (0600). Every request needs
  `X-Cubeon-Token` header else 401. Deliberately thin: exposes what the service
  already knows, forwards clicks straight into it, no backend logic.
- GET: `/friends`, `/status`, `/events?since=N`. POST route tables:
  `_NAME_ROUTES = add, accept, decline, remove, rename, join` (require a name,
  400 if missing); `_BARE_ROUTES = cancel, retry`; plus special-cased `invite`
  and `whitelist` (takes `on`).
- Fail-safe: if it can't bind, the mod just reports "launcher not running" and
  the launcher is unaffected. Handlers wrapped so an exception becomes a clean
  500 `{ok:false,error}` instead of a dead socket.

### 4. The Cloudflare backend (`worker/cubeon-friends.js`, 729 lines)
One Worker, one Durable Object `Hub` (`idFromName("global")`) — KV deliberately
unused (free-tier ~1000 writes/day can't hold 30s presence heartbeats; DO SQLite
storage isn't metered). Routes: `POST /claim`, `GET /name/<name>`, `GET /ws`
(WebSocket Hibernation API + SQLite `new_sqlite_classes`; state derived from
`getWebSockets()` + SQL so it's correct across hibernation eviction).
- Tables: `names` (canonical name → display/secret_hash/uuid/blocked), `friends`
  (bidirectional, two rows), `requests`, `groups`/`group_members`, `messages`
  (trimmed to `HISTORY_KEEP=50`/conv), `calls` (room membership).
- Auth on the WS is the first `hello` frame; `claim-on-connect` also exists for
  clients that skip `/claim`. Presence: a user is online iff ≥1 live socket
  carries their name; close handler broadcasts them offline to friends.
- `calls`/`onCallInvite`/`onSignal` are **feature-agnostic**: `kind` on an
  invite is opaque (currently `p2p` vs legacy voice), `signal` payloads are
  relayed uninspected — that's the entire hook P2P worlds and voice ride on.

### 5. The in-game mod (`mod/src/main/java/com/cubeon/friends/`)
- `CubeonFriendsClient.java` — `ClientModInitializer`: starts the `Bridge` and
  routes launcher toasts to `Gui.setOverlayMessage` (above-hotbar overlay; the
  one API stable across versions). No Fabric API modules at all — loader only.
- `Bridge.java` (626 lines, **no Minecraft imports** → plain-Java, unit-testable
  with bare JDK via `mod/tools/SelfTest.java`). One daemon poll thread:
  ACTIVE_POLL 1.2 s while the Friends screen is open, IDLE 6 s otherwise,
  backoff 1-8 s when the launcher looks down. Publishes an immutable
  `Snapshot` (value-compared, so the screen only rebuilds on real change), and
  drains `/events` after each refresh. Actions are blocking HTTP → the screen
  always calls them from a worker thread. This single-threaded-poll + immutable
  snapshot split is the fix for the old "four blocking HTTP round trips on the
  render thread froze the pause menu" bug.
- `CubeonFriendsScreen.java` (1182 lines) — three tabs (Friends / Requests /
  Account) + a session banner. Widget-only by design (see module docstring): it
  never overrides `render`/`mouseClicked`/`mouseScrolled`/`keyPressed` and only
  uses `Screen` lifecycle + `addRenderableWidget` + `Button`/`EditBox`/
  `StringWidget`, so one source tree compiles for both namespace eras. Costs
  (deliberate): page-buttons not wheel-scroll, no Enter-to-submit. The badge
  button label ("Friends (N online)" / "N invites" / "N pending") is generated
  from the cached, never-blocking snapshot.
- `mixin/PauseScreenMixin.java` + `mixin/TitleScreenMixin.java` — inject at
  `init()` TAIL, `require=0`, wrapped in a catch-all, button placed by measuring
  `children()` for the lowest real widget (bottom-edge decorations skipped).
  Fail-soft everywhere: a mismatch or exception costs the button, never the
  game. `canInvite` = singleplayer pause menu only; title screen/remote-server
  pause open the screen with Invite greyed out.
- `Json.java` — tiny hand-rolled JSON reader (Bridge has no JSON lib).
- Cross-version story (`mod/brackets.json` + `cubeon/cubeonfriends.py`): two
  brackets because of the **namespace** split, not an API one — ≤1.21.x ships
  obfuscated (jar refs in intermediary namespace, needs gradle+loom remap,
  `1.20-1.21` bracket open-ended below 26), 26.x ships unobfuscated (built with
  plain javac, `26` bracket `below:null` open-ended so future versions still get
  the button). Below 1.20.1 there is deliberately no jar.

### 6. Auto-injection at launch
- `cubeon/launch.py` `launch_game()` (`:438-454`): for fabric/quilt, calls
  `cubeonfriends.ensure_installed(mc_version, loader, profile_dir)` **before**
  `sync_mods_to_game()`, so the freshly dropped jar is in `~/.minecraft/mods`
  for that same launch. Best-effort; missing jar → a `status_cb` notice about
  the absent button, never a launch blocker. Same call in
  `cubeon/modpacks.py:484-485` for modpack installs.
- `cubeon/cubeonfriends.py`: `ensure_installed` = remove any other
  `cubeon-friends-*.jar` from the profile (a duplicate/era-mismatched jar is a
  duplicate-mod-id or class-load crash) then copy the matched bracket's jar
  (searched in `~/.cubeon_launcher/cache/` then `mod/build/libs/`). No fallback
  across brackets — wrong namespace = crash on load, absent is correct.
- `main.py:2960-2966`: on startup, if `websocket-client` is available *and* an
  identity is claimed, `friends_client.connect()` — the in-game UI has no way to
  trigger a connect itself. `main.py:1819` pushes `set_version(version_id)`
  after a successful launch and `:1730` `set_version(None)` on exit → presence
  "playing <version>".

## Three flows worth remembering

- **Presence:** connect → WS `hello{name,secret,uuid,version,status}` → server
  `hello_ok` + full `roster` frame → live `presence` frames cached into
  `client.roster` and re-surfaced by `roster_payload()` → mod's `/friends` poll.
- **Add a friend (full round trip):** in-game Add → `Bridge.addFriend` POST
  `/add` → `FriendsService.add_friend` (local validate → `check_name` REST
  pre-flight rejects a nonexistent name → `client.add_friend`) → WS `add` →
  Worker `onAdd` → `requests` row + `REQUEST` frame to target + both rosters.
- **P2P world invite → join** (host Alice, joiner Bob):
  1. Alice taps Invite on Bob's row → session `hosting_wait_port`; game launches
     with a `log_cb` watching for the "Open to LAN on port N" line
     (`p2p.watch_for_lan_port`, regex `p2p.py:172`).
  2. Port found → `call_invite(Bob, kind="p2p")`, state `ringing_out`. Worker
     creates room `r_<uuid>`, rows in `calls`, relays to both.
  3. Bob gets `call_invite` (kind p2p) → `_remember_pending` lights Bob's Join →
     he taps Join → `call_accept(room)` → state `connecting`.
  4. Alice's `_on_call_accept` → background `prepare_offer`: HybridSession
     relay-first, STUN `probe_nat`, sends `p2p_offer` (with `session_token`,
     `nat_info`, `transport` tag) then `p2p_modlist` + `p2p_assetlist`.
  5. Bob's `_run_joiner_punch`/`_run_joiner_hybrid` bring the relay pipe up
     (`net_ready`), diff+fetch mods/assets over `p2p_modchunk`/`p2p_assetchunk`
     (`mods_ready`/`assets_ready`); when all three ready, `_maybe_finish_join`
     auto-launches MC direct-connecting to `127.0.0.1:<relay_port>` (or the
     Minekube public address on the host-side fallback).
  6. Any failure prefers a fallback over a dead session: relay (`p2p_use_relay`)
     → host Minekube public server (`p2p_use_minekube`); every failure is also a
     notification, never a silent hang. Leaving = `call_end` → `_on_call_end`
     single teardown path (close punch, `p2p.teardown` strips this session's mod
     symlinks from the joiner's profile).

## How I verified
- Read every file named above end-to-end (plus `cubeon/voice.py`, `main.py`
  wiring `:2323-2336`, `:1715-1730`, `:1815-1819`, `:2955-2966`, `:3084`,
  `mod/brackets.json`).
- Ran the two relevant headless harnesses — both green with zero failures:
  - `python3 tools/test_friends_service.py` → **136 passed** (the mod↔bridge
    contract test reads the endpoints out of `Bridge.java` and asserts the
    launcher serves them; plus roster/status/events semantics, host/join/retry
    flows, whitelist, rename, real-HTTP auth checks).
  - `python3 tools/test_friends.py` → **37 passed** (incl. WS-frame ↔
    `worker/cubeon-friends.js` protocol parity).
- Not verified in a live game (launcher not running / no online friend) — treat
  the on-disk + harness picture as accurate, the in-world feel as unconfirmed.

## Notes for the next agent / user
- `agents/memory/cubeon-friends-mod.md` (2026-08-29) is the historical build log
  (how to compile the 26.x jar by hand, gotchas, deploy targets) but **predates
  the friends_tab → FriendsService port**: it still references `friends_tab.py`
  and `local_api.start()` from `main.py` directly, both of which are gone.
  Treat it as build/toolchain history, not current wiring.
- The full set of bridge routes is `GET /friends /status /events` + `POST
  /invite /join /cancel /retry /add /accept /decline /remove /rename /whitelist`
  (`local_api.py` route tables). Adding a name-scoped action = one entry in
  `_NAME_ROUTES` + a `set_*_handler` + a `FriendsService` method.
- Mod polling means "push" doesn't exist: everything the mod sees flows through
  `/friends`, `/status`, `/events?since=`. Notifications are fire-and-forget —
  a dropped `/events` drain is a lost toast by design (bounded 200-event ring).
- `kind:"p2p"` on `call_invite` is what lets the receiver distinguish a P2P world
  invite from legacy voice; voice UI was removed with chat, so non-p2p incoming
  rings are auto-declined (`_on_call_invite`).
- FriendsSystem, P2P, and worker docs also live in `agents/docs/`
  (`guide-cubeon-modules.md`, `guide-worker-backend.md`, `guide-data-flow.md`,
  `phase2b-*.md`, `architecture-infrastructure.md`).

## Question for the next agent
The note-baton asks: the 09-02 friends-account note's live-game wording check is
still pending. Beyond that — `Bridge.java` polls `/friends`+`/status` then
`/events` **every cycle**, and the launcher answers three separate HTTP requests
~1-6 s apart. If an action's effect lands in the events feed on a different poll
than the roster, is there any window where the screen shows a stale roster with a
new toast that contradicts it? My reading says no (screen repaints on revision
bump from either), but it's worth a second pair of eyes if anyone wires a live
end-to-end test with two real launchers.
