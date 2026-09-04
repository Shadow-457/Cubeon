# Cubeon Roadmap - adapted from the P2P launcher plan to what's actually built

Status: working doc, cross-checked against the current codebase on 2026-08-23.

The plan this is adapted from assumes a **Rust binary + custom P2P/NAT-punching
stack** (STUN, KCP/QUIC, log-tailing LAN-port sniffing, virtual loopback). That's
not this project. Cubeon is a **Python + Flet desktop app** that gets friends
into the same world by running a **real dedicated server** (vanilla/Paper/
Fabric/Forge, via `cubeon/server.py`) and exposing it with the **playit.gg**
tunnel agent (via `cubeon/playit.py`), not by punching a hole between two
Minecraft clients directly. Below is the same phase structure, rewritten
against what exists, what's missing, and where a phase's *goal* is already met
a different way than the original plan assumed.

---

## Phase 1 - Core Launcher & Mod Cache

**Goal (adjusted):** a SHA-256 global mod cache + a symlink engine + a JVM
execution pipeline. Dropped from the original plan, on purpose: **Prism-style
per-instance isolation (separate Java/configs/metadata per instance)** and
**Microsoft OAuth** - neither fits what this launcher is for.

**Status here: done, for the scope that's actually wanted.**

- ✅ **Global mod cache, SHA-256, symlink engine** - `cubeon/global_mod_cache.py`.
  Content-addressed by SHA-256 (`global_cache/mods/<sha256>.jar`), a hash-alias
  index so a Modrinth manifest's sha1/sha512 resolves to a cache hit before any
  download, and `link_into_place()` tries a real OS symlink first, hardlink
  second, copy last. Wired into modpack installs and the Mods tab
  (`cubeon/modpacks.py`, `cubeon/mods.py`).
- ✅ **JVM execution pipeline** - `cubeon/launch.py` builds the full launch
  command (classpath, natives, memory args, CustomSkinLoader/skin re-mirroring)
  via `minecraft-launcher-lib`.
- Not building, and not gaps: **per-instance Java/config/metadata isolation**
  (Cubeon shares one `.minecraft`, isolates only mods per `(mc_version,
  loader)` profile - see `cubeon/mods.py`'s docstring) and **Microsoft OAuth**
  (Cubeon is offline/cracked-account by design - see `cubeon/friends.py`'s
  docstring on the self-issued "Cubeon name"). Both were in the original
  generic plan, neither matches this project, both are off the list.

---

## Phase 2 - Getting Friends Into the Same World

**Goal (original):** a custom signaling server + STUN/ICE hole punching + a
KCP/QUIC transport with ChaCha20/AES-GCM encryption, to connect two Minecraft
clients directly with no dedicated server and no third-party relay.

**Status here: the underlying goal (friends play together with ~zero manual
networking) is already solved a different, much simpler way - Cubeon doesn't
build a P2P stack at all.**

- ✅ **Tunneling** - `cubeon/playit.py` downloads and manages the **playit.gg**
  agent per-platform (resolved from the GitHub releases API at runtime, not
  hardcoded - see that module's docstring for the asset-naming landmines it
  already hit). playit does the NAT traversal; Cubeon doesn't reimplement
  STUN/ICE/hole-punching itself.
- ✅ **Real dedicated server, not LAN-hosting** - `cubeon/server.py` installs
  and runs an actual server process (vanilla/Paper/Fabric/Forge), with its own
  `server.properties`, plugins dir, EULA handling, RAM/ping tuning, orphan-
  process detection. A friend joins the tunneled address like any normal
  multiplayer server - no client-side virtual loopback, no packet
  encapsulation needed, because it was never peer-to-peer traffic in the first
  place.
- ❌ **Fully P2P (host's own singleplayer world, no server process)** - if the
  actual requirement is "two people play a *singleplayer* world together with
  zero dedicated server," that genuinely isn't built and isn't what
  `server.py`/`playit.py` do. That would mean the original plan's STUN/KCP/QUIC
  work for real, or embedding a lightweight relay. Worth confirming which one
  is actually wanted before scoping further - they're very different amounts
  of work, and the current architecture (real server + tunnel) already covers
  "friends join and play together," just not "no server process exists."
- ❌ **End-to-end encryption on game traffic** - not applicable to the current
  model; playit's tunnel handles transport, Minecraft's own protocol handles
  the rest. Nothing to add here unless the P2P path above gets built.

---

## Phase 3 - Log Sniffing & Local Socket Proxy

**Goal (original):** tail `latest.log` for the "Open to LAN" port, bridge it
over the P2P tunnel with a host-side proxy and a client-side loopback listener.

**Status here: N/A under the current architecture, not missing.**

This entire phase exists to work around *not* having a dedicated server -
it's how you'd expose a singleplayer world's ephemeral LAN port over a P2P
link. Cubeon sidesteps the problem by running a real server (Phase 2 above),
so there's no LAN port to sniff and no loopback bridge to build. This phase
only becomes relevant if the "no dedicated server, host's singleplayer world
only" mode from Phase 2 gets greenlit.

---

## Phase 4 - Auto-Sync & Ephemeral Sessions

**Goal (original):** pre-flight hash comparison of mods/configs between host
and joiner, auto-fetch missing mods into the global cache, spin up a temp
session dir with symlinks, garbage-collect on exit.

**Status here: the mod-fetching and cache half is built; the
session-lifecycle half isn't, because sessions aren't ephemeral in this model.**

- ✅ **Auto-resolving missing mods via Modrinth into the global cache** -
  `cubeon/modpacks.py`'s `.mrpack` installer already does exactly this: reads
  a manifest, resolves each mod's download via the Modrinth-hosted URL
  allowlist, and (via `global_mod_cache.py`, Phase 1) stores it once and links
  it in. `mods.py`'s `copy_mods_between_profiles()` does the same thing for
  copying an existing mod set to a different version/loader - refetches a
  build that actually matches the target instead of blindly copying a
  possibly-incompatible jar.
- ❌ **P2P pre-flight hash exchange between host and joiner** - not
  applicable; joining is "connect to the tunneled server address," not
  "negotiate a mod diff with another running client," so there's no peer to
  exchange hashes with in the first place.
- ❌ **Ephemeral `/temp_sessions/<id>` + garbage collection on PID exit** -
  doesn't exist and doesn't fit the current model: profiles under
  `mod_profiles/` are **persistent** by design (that's the whole point of the
  per-version/loader profile - see `mods.py`'s docstring on the "sometimes
  works, sometimes doesn't" bug this fixed). If a genuinely ephemeral,
  auto-torn-down instance mode is wanted for one-off sessions, that's new
  behavior to design deliberately, not a gap in what's there - persistent
  profiles and ephemeral sessions are different products and shouldn't be
  half-merged.

---

## Phase 5 - Polish, UI & Creator Features

**Goal (original):** Tauri/Electron/native overlay UI, TURN relay fallback,
key remapping, live-reload dev tools.

**Status here:**

- ✅ **UI framework** - already built, just a different one: Flet (Python,
  Flutter-backed), not Tauri/Electron. `main.py` + the `*_tab.py` files are
  the existing "modern overlay" equivalent - nav sidebar, Play/Mods/Modpacks/
  Chat/Friends/Profile/Settings/Servers tabs, live status pills, progress UI.
  Rebuilding this in Tauri/Electron would be throwing away a working UI to
  chase a stack match with the original plan, not a real improvement - no
  reason to unless there's a concrete reason Flet is blocking something.
- ✅ **"1-click host/join" equivalent** - the Servers group (`server_tab.py`)
  + `playit.py` tunnel already gets a host to "install → start → share
  address" in a few clicks; joining is just connecting to that address like
  any server.
- ✅ **Presence / "who's online, what are they playing"** - `cubeon/friends.py`
  (Cubeon-name identity, realtime WebSocket presence/chat/groups/voice-call
  signalling) plus the two UI tabs on top of it: `friends_tab.py` (Chat) and
  `friends_status_tab.py` (Friends - online/away + "Playing `<version>`" per
  friend, added this session). Not in the original plan at all, but it's the
  actual "see what your friends are up to" feature this project has.
- ✅ **Creator/power-user extras that exist today, uncalled-for by the
  original plan:** world backups (`cubeon/backup.py`), invite codes
  (`cubeon/invites.py`), skins/capes via CustomSkinLoader with a network skin
  API (`cubeon/skins.py`, `csl.py`, spec in `docs/phase1-skins-capes.md`),
  voice call signalling (`cubeon/voice.py`), server plugin management
  (`server.py`'s plugin functions).
- ❌ **TURN relay fallback** - not applicable without the P2P engine from
  Phase 2 existing first.
- ❌ **OS-level key remapping / live-reload dev tools** - not built. Genuinely
  new scope, not tied to anything else here - fine to pick up independently
  whenever it's prioritized.

---

## Phase 2b - True P2P Worlds (decided scope, ready to build)

This is the one gap Phase 2 flagged as "needs a deliberate decision." Decided,
2026-08-23. No TURN, no VPS, no silent fallback to the dedicated-server path -
if direct hole-punching fails, the UI shows an explicit error and stops.

**New module: `cubeon/p2p.py`.** Client-only, no worker/Durable Object changes
needed - everything below rides infrastructure that already exists:
`friends.py`'s `call_invite`/`call_accept`/`call_decline`/`call_end` (already
generic room lifecycle server-side, nothing voice-specific in the SQL or
routing) for session invite/accept, and `signal()` (opaque passthrough,
server never inspects payload) for exchanging STUN candidates and mod-fetch
control messages once in a room.

**Corrected 2026-08-23 (same day, after implementation review):** step 1
below was originally written as "Cubeon launches the game and opens to LAN
automatically." That doesn't work and was never actually possible -
Minecraft has no external API to load a world or click "Open to LAN" from
outside the running client; that only happens via a mouse click inside the
game itself. The first pass of `p2p.py`/`friends_tab.py` had a `log_cb`
watching for the LAN-open log line, but nothing was driving the game
towards producing that line - a host clicking "Start P2P World" launched
vanilla Minecraft to the title screen and then sat stuck in
`hosting_wait_port` forever, since nothing prompted the actual click. That
implementation gap is fixed by the corrected flow below (manual step,
Cubeon-detected) - see the "why not an in-game button" note under step 1.

**Flow, in order:**

1. **Host starts, manually, in-game - Cubeon detects it rather than
   triggering it.** Clicking "Start P2P World" in Cubeon launches the game
   (`launch.py`'s `launch_game(..., log_cb=...)`) and shows a waiting state:
   *"Load your world, then Open to LAN from the pause menu."* The host does
   that themselves, same as vanilla always required. `log_cb` (already
   streamed off the game's stdout pipe, no disk log-tailing needed) watches
   for the "Open to LAN on port `<port>`" line and reacts the moment it
   appears - that's the only part that's automatic.
   - **Why not an in-game "one-click" button instead:** considered and
     rejected, 2026-08-23. A button rendered inside Minecraft needs a mod
     loader to inject into - no such hook exists on vanilla or Paper (Paper
     is server-only, never touches the client jar at all). Cubeon already
     hits this exact wall for skins/capes: `csl.py`'s `ensure_ready()` only
     installs CustomSkinLoader when the profile's loader is in
     `mod_loaders.MOD_CAPABLE_LOADERS` (`fabric`, `quilt`, `forge`,
     `neoforge`) - on vanilla it's a documented no-op ("Vanilla can't load
     mods at all. Not a failure, just nothing to do."), which is why a
     vanilla host's own uploaded skin never actually renders in-game either.
     Gating P2P hosting on the same loader subset would silently exclude
     vanilla hosts, which isn't acceptable - so this stays a manual in-game
     click on every loader, including vanilla, rather than a nicer button
     that only some hosts could ever see.
2. **Host invites specific friend(s).** Host picks who from their friends
   list; only those friends' Join button lights up (not a broadcast to
   everyone). Uses `call_invite(to)` with a p2p-specific payload marker so
   it's distinguishable from a voice call room on the client side (server
   doesn't care, it's still just a room).
3. **On accept, both sides start in parallel, join happens when both finish:**
   - **Network path:** STUN (free public servers, e.g.
     `stun.l.google.com:19302`) to learn each side's public UDP endpoint,
     exchanged over `signal()`, then simultaneous UDP hole-punch. On success,
     a local UDP relay/proxy on the joiner's side forwards to/from the punched
     endpoint, target being the host's LAN port from step 1 (this is the
     original plan's Phase 3 log-sniffing/local-proxy idea, finally
     applicable). **On failure: explicit error shown, stop. No fallback to
     server.py/playit.py** - different feature, different UX, per 2026-08-23
     decision.
   - **Mod/config path (parallel with the above, not blocking it):**
     joiner compares its mod set against the host's (hash list sent over
     `signal()`). Missing mods are fetched - first check
     `global_mod_cache.py` (existing SHA-256 cache/hash-index, may already
     have it from Modrinth), and only pull peer-to-peer from the host over
     the data channel for anything not already resolvable that way. Whatever
     arrives, host- or Modrinth-sourced, lands in the global cache exactly
     like today's `.mrpack` install path, then gets symlinked into the
     joiner's active profile the normal way (`global_mod_cache.link_into_place`).
     Beyond mods: anything else Minecraft/the modloader needs to run
     correctly and match the host - resourcepacks, loader-required configs -
     goes through the same fetch-if-missing path. The world save itself is
     never copied; the joiner connects live to the host's running instance
     like any multiplayer client, same as today's dedicated-server model.
4. **Join.** Once both the direct transport is up and mods/config are synced, the
   joiner connects through a localhost TCP listener that carries Minecraft TCP
   over the punched UDP path. **Implemented:** Cubeon launches the joiner's
   Minecraft client with `--server 127.0.0.1 --port <relay-port>`, so the final
   Direct Connect step is automatic. The transport is versioned as
   `cubeon-tcp-over-udp-v2` and protected by a per-session token + per-frame HMAC.
5. **Teardown on the joiner leaving/logging out:** remove the session's
   symlinks from the joiner's active profile and any session-only config
   written for this P2P world. The global cache itself is untouched - those
   are shared, persistent, content-addressed files, only this profile's
   links go. **Second join (same friend, same mods):** cache already has
   everything from step 3's first run, so it's link-only, no re-fetch.

**UI split (decided - friends_tab only, server_tab untouched by this):**
- `friends_tab.py`: "Start P2P World" control for the host; for each friend
  in the roster, a Join button that's greyed out by default and enables the
  moment that friend receives a P2P invite (via `call_invite`-equivalent),
  matching how presence ("Playing 1.20.1") already renders per-friend today.
- `server_tab.py`: **not touched by this phase.** It stays exactly what it is
  - the dedicated vanilla/Paper/Fabric/Forge server hosting UI. P2P is a
  genuinely different feature/flow living entirely in Friends, not a fourth
  option bolted onto Server.

**Explicitly not building:** TURN relay (no VPS, per 2026-08-23 - direct
hole-punch or explicit failure, nothing in between), any fallback that
silently switches a failed P2P attempt over to the server+playit.gg path.

**Update 2026-08-25 - punch-failure relay added (narrow exception):** when the
hole-punch fails outright (CGNAT/symmetric NAT), the session now falls back to
`RelaySession` (`cubeon/p2p.py`), which carries the same TCP stream over the
friends signalling channel as base64 chunks - no Worker changes, no VPS, free
tier. This is not TURN and not the server+playit path: it reuses the existing
authenticated friends WebSocket, only runs after direct fails, and the UI says
so ("Relayed via Cubeon servers"). Direct remains the normal path.

---

## Phase 2b Batch 4 - Transport & Lifecycle Hardening

**Status: implemented.**

- ✅ Reliable transport send-window backpressure and retransmission ceiling.
- ✅ Heartbeat/idle detection and bounded receive buffers.
- ✅ TCP bridge moved off the UDP transport loop to prevent local TCP
  backpressure from starving ACKs and retransmissions.
- ✅ Graceful FIN handling and explicit failure reasons.
- ✅ Crash/stale-session cleanup and process-exit cleanup.
- ✅ P2P UI watchdog for post-connect transport failures.
- ✅ Mod-sync timeout and progress tracking.

See `docs/phase2b-batch4.md` for the implementation notes and validation.

## Net summary

The original roadmap is written for a **different networking model** than
this codebase uses (custom P2P vs. real-server-plus-tunnel), so several of its
phases (2, 3, most of 4) don't apply as written - not because they're
unfinished, but because Cubeon solves the same user-facing problem
("play together with your friends, minimal setup") a structurally different
way that's already working. The parts that *do* carry over 1:1 - the SHA-256
mod cache and symlink engine (Phase 1) - are now built, with Prism-style
instance isolation and Microsoft OAuth dropped from scope since neither fits
this project. The one real gap worth a deliberate decision, not a quiet patch:

- ~~**True P2P singleplayer-world sharing with no dedicated server**~~ -
  decided 2026-08-23, scoped as Phase 2b above. Client-only (STUN +
  hole-punch, no TURN/VPS), lives entirely in `friends_tab.py`, explicit
  error on connect failure rather than a fallback to the server+tunnel model.

Everything else in the original plan is either already covered by a different
mechanism (tunneling, mod cache, UI) or is out-of-scope net-new work
(Microsoft OAuth, TURN relay, key remapping) that isn't blocked on anything
above - pick it up independently if/when it's actually needed.


## Phase 2b Batch 5 - Large Session Sync

**Status: implemented.**

- Added resourcepack and allowlisted config synchronization alongside the existing mod sync.
- Added session-safe backups/restoration for replaced config/resource files.
- Added bounded asset manifests, file sizes, aggregate transfer size, and chunk validation.
- Join now waits for network + mods + shared assets before auto-launch.

See `docs/phase2b-batch5.md`.


## Phase 2b Batch 6 - Session Recovery, Security & Diagnostics

Implemented 2026-08-23.

- Upgraded the direct transport to `cubeon-tcp-over-udp-v2` with a 128-bit HMAC tag on every frame.
- Added transport metrics: RTT samples, frame/byte counters, retransmits, dropped frames, outstanding window, and peer-idle age.
- Added a pre-Minecraft reconnect path that can rebuild the UDP mapping while preserving the same session token. A live Minecraft TCP stream is intentionally not resumed in place because Minecraft's TCP state cannot be safely replayed.
- Added process-local SHA-256 stat caching for P2P mod/config/resource manifests, invalidated by file size + mtime_ns, so repeated manifests avoid unnecessary disk hashing.
- Added a targeted Retry action for join failures that occur before the direct network path is established.
- Added live direct-P2P quality information to the Friends banner when RTT samples are available.
- Added regression tests for frame tamper rejection, wrong-token rejection, hash-cache invalidation, and transport metrics.

Validation: Python compileall, P2P loopback, P2P stress, session cleanup, and Batch 6 regression tests pass. Full launcher runtime remains dependent on optional desktop/Minecraft dependencies.
