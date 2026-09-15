# Visual Flow Diagrams

> ASCII diagrams of Cubeon's core flows: mod profile sync, skin network,
> server hosting, friends/P2P, backups — plus content compatibility/doctor
> and modpack install (added 2026-09-15). This is a MAIN reference: when a
> flow changes in code, change it here too.

---

## 1. Mod Profile Sync - The Complete Lifecycle

This is the flow that makes per-version, per-loader mods work. It's the core of why Cubeon's mod system is different from "just drop jars into `.minecraft/mods/`."

### The Problem It Solves

```
❌ WITHOUT profiles:
  .minecraft/mods/
    ├── sodium-1.20.1.jar
    ├── sodium-1.21.jar       ← conflicts with 1.20.1 version!
    ├── iris-1.20.1.jar
    └── lithium-1.21.jar

  All mods in one flat folder. Switching versions = broken mods.
```

```
✅ WITH profiles:
  ~/.cubeon_launcher/mod_profiles/
    ├── 1.20.1-fabric/
    │   ├── sodium-1.20.1.jar
    │   └── iris-1.20.1.jar
    ├── 1.21-fabric/
    │   ├── sodium-1.21.jar
    │   └── lithium-1.21.jar
    └── 1.20.1-forge/
        └── some-forge-mod.jar

  .minecraft/mods/  ← synced at launch, only contains the right mods
```

### Install Flow

```
User clicks "Download" on Modrinth search result
                    │
                    ▼
    ┌───────────────────────────────────┐
    │  mods.py:                         │
    │  install_mod_with_dependencies()  │
    │                                   │
    │  1. Resolve profile directory:    │
    │     mod_profiles/1.20.1-fabric/   │
    │                                   │
    │  2. Download jar from Modrinth    │
    │     (via global cache for dedup,  │
    │     byte progress reported)       │
    │                                   │
    │  3. Save jar to profile folder    │
    │                                   │
    │  4. Pull REQUIRED dependencies    │
    │     the profile doesn't have yet  │
    │     (Fabric API is the classic)   │
    │     - same download path          │
    │                                   │
    │  5. Write sidecar metadata:       │
    │     sodium.cubeon.json            │
    │     {"slug": "sodium"}            │
    │                                   │
    │  Progress is reported in FILE     │
    │  UNITS across the whole install:  │
    │  "Downloading… 42% (file 2/3)"    │
    │  - one continuous climb, it never │
    │  restarts per dependency          │
    └───────────────────────────────────┘
                    │
                    ▼
    ┌───────────────────────────────────┐
    │  mod_profiles/1.20.1-fabric/      │
    │  ├── sodium-1.20.1.jar           │
    │  ├── sodium-1.20.1.cubeon.json   │
    │  ├── iris-1.20.1.jar             │
    │  └── iris-1.20.1.cubeon.json     │
    └───────────────────────────────────┘
```

### Toggle Flow (Enable/Disable)

```
User clicks toggle switch on "sodium-1.20.1.jar"
                    │
                    ▼
    ┌───────────────────────────────────┐
    │  mods.py: toggle_mod()            │
    │                                   │
    │  Renames file:                    │
    │  sodium-1.20.1.jar                │
    │       ↓                           │
    │  sodium-1.20.1.jar.disabled       │
    │                                   │
    │  (Instant - no download, no copy) │
    └───────────────────────────────────┘
                    │
                    ▼
    ┌───────────────────────────────────┐
    │  mod_profiles/1.20.1-fabric/      │
    │  ├── sodium-1.20.1.jar.disabled  │  ← disabled, won't be synced
    │  └── iris-1.20.1.jar             │  ← still enabled
    └───────────────────────────────────┘
```

### Launch Sync Flow

This is the critical moment - the 2 seconds between clicking Play and the game starting.

```
User clicks PLAY
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  main.py: do_install_and_launch()                             │
│                                                               │
│  1. Install MC version (if needed)                            │
│  2. Install mod loader (if needed)                            │
│  3. Skin/cape sync (see Skin Network diagram below)           │
│  4. CSL setup                                                 │
│                                                               │
│  5. ┌─────────────────────────────────────────────────────┐   │
│     │  doctor.py: run_doctor(mc, loader, auto_fix=True)   │   │
│     │                                                     │   │
│     │  Pre-repair BEFORE the game reads the folder:       │   │
│     │  - mods: duplicates, version conflicts, deps        │   │
│     │  - resourcepacks: pack_format vs THIS version       │   │
│     │    (repair_pack widens the declared range,          │   │
│     │    atomic temp-file + os.replace)                   │   │
│     │  - shaders: shaders/ folder structure               │   │
│     │  Fast + offline. Best-effort: a failed check        │   │
│     │  must never block playing.                          │   │
│     └─────────────────────────────────────────────────────┘   │
│                                                               │
│  6. ┌─────────────────────────────────────────────────────┐   │
│     │  mods.py: sync_mods_to_game("1.20.1", "fabric")    │   │
│     │                                                     │   │
│     │  Step A: WIPE .minecraft/mods/                      │   │
│     │  ┌─────────────────────────────┐                    │   │
│     │  │ .minecraft/mods/            │                    │   │
│     │  │   (empty after this step)   │                    │   │
│     │  └─────────────────────────────┘                    │   │
│     │                                                     │   │
│     │  Step B: COPY enabled jars from profile             │   │
│     │  ┌──────────────────────┐    ┌──────────────────┐   │   │
│     │  │ mod_profiles/        │    │ .minecraft/mods/ │   │   │
│     │  │ 1.20.1-fabric/       │───►│                  │   │   │
│     │  │  ├── iris.jar   ✓   │    │  ├── iris.jar    │   │   │
│     │  │  └── sodium.jar ✗  │    │  └── (no sodium) │   │   │
│     │  │     (.disabled)     │    │                  │   │   │
│     │  └──────────────────────┘    └──────────────────┘   │   │
│     │                                                     │   │
│     │  (Only .jar files are copied, not .disabled)        │   │
│     └─────────────────────────────────────────────────────┘   │
│                                                               │
│  7. Build java command                                        │
│  8. Start subprocess                                         │
│  9. Game reads .minecraft/mods/ → loads iris, skips sodium   │
└───────────────────────────────────────────────────────────────┘
```

### Version Switch Flow

```
User selects "1.21" in version dropdown
        │
        ▼
┌───────────────────────────────────────┐
│  main.py: on_version_selected()       │
│                                       │
│  state["selected_mc_version"] = "1.21"│
│                                       │
│  refresh_mods_list()                  │
│  ┌───────────────────────────────┐    │
│  │ Reads: mod_profiles/          │    │
│  │   1.21-fabric/                │    │
│  │   ├── sodium-1.21.jar        │    │
│  │   └── lithium-1.21.jar       │    │
│  │                               │    │
│  │ Shows in Mods tab:            │    │
│  │   ✓ sodium-1.21.jar          │    │
│  │   ✓ lithium-1.21.jar         │    │
│  └───────────────────────────────┘    │
│                                       │
│  (The 1.20.1 mods are still there     │
│   in their own profile - untouched)   │
└───────────────────────────────────────┘
        │
        ▼
User clicks PLAY
        │
        ▼
  sync_mods_to_game("1.21", "fabric")
        │
        ▼
  .minecraft/mods/ now has sodium-1.21 + lithium-1.21
```

### Global Cache Deduplication

When multiple profiles share the same mod jar (e.g. Fabric API across 5 profiles):

```
mod_profiles/
├── 1.20.1-fabric/
│   └── fabric-api-0.92.0.jar  ──symlink──┐
├── 1.21-fabric/                           │
│   └── fabric-api-1.0.0.jar  ──symlink──┐│
└── 1.19.4-fabric/                        ││
    └── fabric-api-0.87.0.jar ──symlink──┐││
                                          ▼▼▼
global_cache/mods/
├── <sha256-of-0.92.0>.jar   ← real bytes (one copy)
├── <sha256-of-1.0.0>.jar    ← real bytes (one copy)
├── <sha256-of-0.87.0>.jar   ← real bytes (one copy)
└── .hash_index.json          ← sha1/sha512 → sha256 lookup
```

```
Installation path:
  1. Check hash_index.json for manifest hash (sha1/sha512)
  2. Hit? → hardlink/symlink from cache (zero download)
  3. Miss? → download, compute sha256, store in cache, link
```

---

## 2. Skin Network - End-to-End

### Overview

```
┌─────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  YOUR        │     │  Cloudflare Worker    │     │  FRIEND'S       │
│  LAUNCHER    │     │  (cubeon-skins.js)    │     │  LAUNCHER       │
│              │     │                       │     │                 │
│  Upload skin │────►│  Store texture        │     │  CSL asks:      │
│  Heartbeat   │────►│  Update pointer       │     │  "what skin     │
│              │     │                       │     │   does Alex     │
│              │     │                       │     │   have?"        │
│              │     │                       │────►│                 │
│              │     │                       │◄────│  Gets texture   │
│              │     │                       │     │  Renders in-game│
└─────────────┘     └──────────────────────┘     └─────────────────┘
```

### Upload Flow

```
User uploads "cool_skin.png" (64x64)
        │
        ▼
┌───────────────────────────────────────────┐
│  skins.py: add_custom_skin()              │
│                                           │
│  1. Validate: PNG? 64x64 or 64x32?       │
│  2. Copy to ~/.cubeon_launcher/skins/     │
│  3. Register in skins.json metadata       │
└───────────────────────────────────────────┘
        │
        ▼
User clicks "Use" on the skin
        │
        ▼
┌───────────────────────────────────────────┐
│  skins.py: set_active_skin(cfg, filename) │
│                                           │
│  1. cfg["active_skin"] = filename         │
│  2. sync_local_skin_to_csl(cfg)           │
│  3. save_config(cfg)                      │
└───────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────┐
│  sync_local_skin_to_csl()                 │
│                                           │
│  LOCAL (for you):                         │
│  ┌─────────────────────────────────────┐  │
│  │ Compose: base skin + hat (if any)   │  │
│  │ Save to:                             │  │
│  │   .minecraft/CustomSkinLoader/      │  │
│  │   LocalSkin/skins/<USERNAME>.png    │  │
│  └─────────────────────────────────────┘  │
│                                           │
│  NETWORK (for others):                    │
│  ┌─────────────────────────────────────┐  │
│  │ _publish_skin_async(cfg)            │  │
│  │ Runs on daemon thread               │  │
│  │                                     │  │
│  │ Check: did username/uuid/hash       │  │
│  │         change since last publish?  │  │
│  │                                     │  │
│  │ No change → do nothing (0 writes)   │  │
│  │                                     │  │
│  │ Username changed:                   │  │
│  │   POST /api/heartbeat               │  │
│  │   {username, uuid}                  │  │
│  │   → Worker: pointer:name → uuid     │  │
│  │                                     │  │
│  │ Skin changed:                       │  │
│  │   POST /api/skin                    │  │
│  │   {uuid, model, skin(base64)}       │  │
│  │   → Worker: stores texture          │  │
│  │   → Worker: skin:uuid → texture URL │  │
│  └─────────────────────────────────────┘  │
└───────────────────────────────────────────┘
```

### How Other Players See Your Skin

```
Friend joins a server where you're playing
        │
        ▼
┌───────────────────────────────────────────────────┐
│  Friend's CustomSkinLoader (CSL)                   │
│                                                   │
│  CSL has ExtraList entries registered by Cubeon:   │
│  ┌─────────────────────────────────────────────┐  │
│  │ Priority 1: Cubeon (Worker API)             │  │
│  │   GET /skins/<your_name>.json               │  │
│  │                                             │  │
│  │ Priority 2: CubeonLocalSkin (local file)    │  │
│  │   LocalSkin/skins/<your_name>.png           │  │
│  │                                             │  │
│  │ Priority 3: Mojang (official)               │  │
│  │   (only used if Cubeon entries miss)        │  │
│  └─────────────────────────────────────────────┘  │
│                                                   │
│  CSL queries Cubeon first (highest priority):      │
└───────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────┐
│  GET /skins/alex.json                              │
│                                                   │
│  Worker (cubeon-skins.js):                         │
│  1. pointer:alex → "a1b2c3d4-..."  (the UUID)    │
│  2. skin:a1b2c3d4-... → {url, model}             │
│  3. Return:                                       │
│     {                                              │
│       "username": "Alex",                          │
│       "textures": {                                │
│         "default": "https://.../textures/abc123",  │
│         "cape": "https://.../textures/c9124..."    │
│       }                                            │
│     }                                              │
└───────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────┐
│  GET /textures/abc123                               │
│                                                   │
│  Worker:                                           │
│  1. Check: is id == CAPE_ID (hardcoded)?           │
│     Yes → return inlined cape PNG (0 KV reads)     │
│  2. No → look up texture:abc123 in KV              │
│  3. Return the PNG bytes                           │
└───────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────┐
│  Friend's game renders your skin                   │
│  + the shared Cubeon cape                          │
└───────────────────────────────────────────────────┘
```

### Username Rename Flow

```
You rename: "Alex" → "CoolPlayer"
        │
        ▼
┌───────────────────────────────────────────────┐
│  1. LocalSkin sync                             │
│     Delete: LocalSkin/skins/Alex.png           │
│     Create: LocalSkin/skins/CoolPlayer.png     │
│                                               │
│  2. Network heartbeat                          │
│     POST /api/heartbeat                        │
│     {username: "CoolPlayer", uuid: same-uuid}  │
│                                               │
│  3. Worker updates pointer:                    │
│     pointer:alex → (deleted)                   │
│     pointer:coolplayer → same-uuid             │
│                                               │
│  4. Skin/cape texture stays the same           │
│     (keyed by UUID, not name)                  │
│                                               │
│  5. Friends see:                               │
│     "CoolPlayer is now online"                 │
│     (same skin, same cape, new name)           │
└───────────────────────────────────────────────┘
```

### CSL Load Order

```
CSL merges skin sources in priority order (lower = checked first):

  ┌─────────────────────────────────────────────────┐
  │ Priority 100: Mojang (official session server)   │
  │   → Serves skins for premium accounts            │
  │   → Would hijack taken names!                    │
  │                                                   │
  │ Priority 200: LittleSkin                          │
  │ Priority 300: BlessingSkin                        │
  │   ...                                             │
  │                                                   │
  │ Priority 710: LocalSkin (built-in)                │
  │   → Reads LocalSkin/skins/<NAME>.png              │
  │   → LOCAL ONLY - only you see this                │
  │                                                   │
  │ Priority 0 (prepended): CubeonLocalSkin           │
  │   → Also reads LocalSkin/skins/<NAME>.png         │
  │   → BUT with cape + elytra paths                  │
  │   → Wins the merge order game                     │
  │                                                   │
  │ Priority 0 (prepended): Cubeon (Worker API)       │
  │   → GET /skins/<name>.json                        │
  │   → Serves skin + cape to OTHER players           │
  │   → Checked BEFORE Mojang (prevents hijacking)   │
  └─────────────────────────────────────────────────┘

Why CubeonLocalSkin has "./" in cape path:
  "LocalSkin/capes/<NAME>.png"      ← same as built-in entry
  "LocalSkin/./capes/<NAME>.png"    ← resolves to same file
                                      but COMPARES differently
                                      → survives CSL's dedupe
                                      → stays ahead of Worker
```

### Write-Frugal State Machine

```
┌─────────────────────────────────────────────────────────────┐
│  _publish_skin() decision tree                              │
│                                                             │
│  Load publish state from skin_net.json                      │
│  (username, uuid, hash, model, base)                        │
│                                                             │
│  Identity changed?                                          │
│  (username ≠ stored OR uuid ≠ stored OR base ≠ stored)      │
│    YES → fire heartbeat (1 KV write)                        │
│    NO  → skip                                               │
│                                                             │
│  Skin changed?                                              │
│  (hash ≠ stored OR model ≠ stored)                          │
│    YES → fire upload (1 KV write)                           │
│    NO  → skip                                               │
│                                                             │
│  Nothing changed?                                           │
│    → return immediately (0 KV writes)                       │
│                                                             │
│  Typical launch (unchanged): 0 writes                       │
│  Username rename:            1 write  (heartbeat only)      │
│  New skin upload:            2 writes  (heartbeat + upload) │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Server Hosting Flow

### Server Start

```
User clicks "Start" in Server Console tab
        │
        ▼
┌───────────────────────────────────────────────┐
│  server.py: start_server()                     │
│                                               │
│  1. Check: is_server_running()?               │
│     → world_lock_holder() probes session.lock │
│     → If locked by orphan: raise error        │
│                                               │
│  2. Check: is_server_installed()?             │
│     → server-paper.jar must exist             │
│                                               │
│  3. Check: eula_accepted()?                   │
│     → User must have ticked EULA checkbox     │
│                                               │
│  4. Find Java for this MC version             │
│     → find_java_for_version()                 │
│     → Checks major version requirement        │
│                                               │
│  5. Build command:                             │
│     java -Xmx2048M -jar server-paper.jar nogui│
│     ( + Aikar's G1GC flags if smooth mode)    │
│                                               │
│  6. Start detached:                            │
│     subprocess.Popen(..., start_new_session=True)│
│     → Server survives terminal close          │
│                                               │
│  7. Pipe stdout to console UI                  │
│  8. Auto-install AuthMe + Minekube Connect    │
└───────────────────────────────────────────────┘
```

### Orphan Detection

```
Cubeon restarts while server is still running from previous session
        │
        ▼
┌───────────────────────────────────────────────┐
│  _server_processes = {}  (empty - fresh start) │
│                                               │
│  User clicks "Start"                          │
│  → is_server_running() checks:                │
│    1. _server_processes.get(id) → None         │
│    2. world_lock_holder(id) → PID 4231         │
│    3. Returns True (orphan detected!)          │
│                                               │
│  Error message:                                │
│  "A Minecraft server is already running        │
│   (process 4231) from an earlier Cubeon        │
│   session. Click 'Stop leftover server'        │
│   to shut it down, then start again."          │
│                                               │
│  User clicks "Stop leftover server"            │
│  → stop_orphaned_server()                      │
│    1. SIGTERM to PID 4231                      │
│    2. Wait up to 45s for clean shutdown        │
│    3. If still alive: SIGKILL                  │
│    4. Wait for world_lock_holder() → None      │
│                                               │
│  Now safe to start a new server                │
└───────────────────────────────────────────────┘
```

---

## 4. Friends System Flow

### Claiming a Name

```
User types "BlueFox" and clicks "Claim"
        │
        ▼
┌───────────────────────────────────────────────┐
│  friends.py: claim("BlueFox")                  │
│                                               │
│  1. POST /claim                                │
│     {                                          │
│       name: "BlueFox",                         │
│       secret: "abc123...",                     │
│       uuid: "a1b2c3d4-..."                    │
│     }                                          │
│                                               │
│  Worker (cubeon-friends.js):                   │
│  1. Validate name format                       │
│  2. Check: is name already taken?              │
│     YES → return 409 "name_taken"              │
│  3. Hash the secret (SHA-256)                  │
│  4. INSERT INTO names:                         │
│     (bluefox, BlueFox, hash, uuid, created)    │
│     RACE-SAFE: two launchers claiming the      │
│     same name simultaneously both hit the DB;  │
│     the PRIMARY KEY violation is caught +      │
│     re-read, the loser gets a clean 409        │
│     (never a 500, never a double claim)        │
│  5. Return {ok: true, name, uuid}              │
│                                               │
│  Client saves identity.json:                   │
│  {name: "BlueFox", secret: "abc123..."}        │
│  DEPLOYED (2026-09-15): all four workers run   │
│  the swept code - per-IP pre-auth WS flood     │
│  gate, blocked-account gating, body caps,      │
│  enforced rate limiters. cubeon-invites is     │
│  LIVE too (KV-backed; was never deployed       │
│  before this).                                 │
└───────────────────────────────────────────────┘
```

### WebSocket Connection

```
Launcher starts (or Friends tab opens)
        │
        ▼
┌───────────────────────────────────────────────┐
│  friends.py: FriendsClient.connect()           │
│                                               │
│  1. Load identity.json → name + secret         │
│  2. Open WebSocket to /ws                      │
│  3. First frame: hello                         │
│     {                                          │
│       t: "hello",                              │
│       name: "BlueFox",                         │
│       secret: "abc123...",                     │
│       version: "1.20.1",                       │
│       status: "online"                         │
│     }                                          │
│                                               │
│  Worker:                                       │
│  1. Hash secret, verify against stored hash    │
│  2. If mismatch → close with "not_yours"       │
│  3. If match → hello_ok + full roster          │
│                                               │
│  Client receives:                              │
│  {t: "hello_ok", name: "BlueFox", uuid: "..."} │
│  {t: "roster", friends: [...], requests: [...]} │
│                                               │
│  Connection is live! Presence broadcasts to    │
│  all friends: "BlueFox is online"              │
└───────────────────────────────────────────────┘
```

### Sending a Chat Message

```
You type "hey!" in DM to friend "GreenWolf"
        │
        ▼
┌───────────────────────────────────────────────┐
│  Client sends:                                 │
│  {t: "dm", to: "greenwolf", text: "hey!"}     │
│                                               │
│  Worker:                                       │
│  1. Verify: are BlueFox and GreenWolf friends? │
│  2. Store in SQLite:                           │
│     INSERT INTO messages (conv, sender, ...)   │
│     VALUES ("d:bluefox:greenwolf", "bluefox",  │
│             "BlueFox", "hey!", ts, mid)        │
│  3. Echo to sender:                            │
│     {t: "dm", from: "BlueFox", text: "hey!"}   │
│  4. Send to recipient:                         │
│     {t: "dm", from: "BlueFox", text: "hey!"}   │
│                                               │
│  Both see the message in their thread.         │
│  History limited to 50 messages per conv.      │
└───────────────────────────────────────────────┘
```

### P2P World Session

```
Host: "Open to LAN on port 51234"
        │
        ▼
┌───────────────────────────────────────────────┐
│  1. Host starts Minecraft in LAN mode          │
│  2. watch_for_lan_port() detects port 51234    │
│  3. Host sends call_invite to friend           │
│     {t: "call_invite", to: "GreenWolf",        │
│      kind: "p2p_world"}                        │
│                                               │
│  4. Friend accepts: call_accept(room)          │
│                                               │
│  5. Both run HybridSession.begin():            │
│     ┌─────────────────────────────────────┐   │
│     │ RELAY PHASE (immediate)              │   │
│     │ Game data flows over friends         │   │
│     │ WebSocket → guaranteed path          │   │
│     │ Friend joins world instantly         │   │
│     └─────────────────────────────────────┘   │
│                    │                           │
│     ┌──────────────▼──────────────────────┐   │
│     │ DIAGNOSTICS (background)             │   │
│     │ Both run STUN probes                 │   │
│     │ Detect NAT type + port delta         │   │
│     │ Swap results over relay              │   │
│     └─────────────────────────────────────┘   │
│                    │                           │
│     ┌──────────────▼──────────────────────┐   │
│     │ COORDINATED SPRAY                    │   │
│     │ Both blast UDP packets across        │   │
│     │ predicted port range                 │   │
│     └─────────────────────────────────────┘   │
│                    │                           │
│     ┌──────────────▼──────────────────────┐   │
│     │ HANDOVER (if direct path found)      │   │
│     │ First authenticated UDP frame → flip │   │
│     │ CUBP stream from relay to UDP        │   │
│     │ Lower ping, same session             │   │
│     └─────────────────────────────────────┘   │
│                    │                           │
│     If spray fails: stays on relay (no fail)  │
└───────────────────────────────────────────────┘
```

---

## 5. Backup & Restore Flow

### Backup

```
User clicks "Back up now"
        │
        ▼
┌───────────────────────────────────────────────┐
│  backup.py: create_backup()                    │
│                                               │
│  Scan sources:                                │
│  ├── config.json          ✓ always             │
│  ├── mod_profiles/        ✓ always             │
│  ├── skins/               ✓ always             │
│  ├── capes/               ✓ always             │
│  ├── profile/             ✓ always             │
│  ├── servers/             ✓ always             │
│  └── saves/               ✗ opt-in (can be GB) │
│                                               │
│  Write: cubeon-backup-2026-08-28_14-30.zip    │
│  Rotate: keep last N, delete older             │
│  Update: last_backup_ts in backup_settings     │
└───────────────────────────────────────────────┘
```

### Restore

```
User picks a backup .zip
        │
        ▼
┌───────────────────────────────────────────────┐
│  backup.py: restore_backup(path)               │
│                                               │
│  For each entry in the zip:                    │
│  1. Determine destination by top-level folder: │
│     config.json → ~/.cubeon_launcher/          │
│     mod_profiles/ → ~/.cubeon_launcher/        │
│     world/ → ~/.minecraft/                     │
│                                               │
│  2. Zip-slip guard:                            │
│     dest must stay under its root              │
│                                               │
│  3. Overwrite existing, leave new files alone  │
│                                               │
│  Result: settings restored, mods restored,     │
│          any new stuff since backup preserved  │
└───────────────────────────────────────────────┘
```

---

## 6. Content Compatibility & Doctor Flow

The answer to "why does my resourcepack show as Incompatible in game?".
Two halves: keep broken content OUT of browse results, and REPAIR what's
already installed. `cubeon/packformat.py` decides, `cubeon/doctor.py` acts.

### Browse-Time Filter (never offer what can't work)

```
User opens Mods/Resourcepacks/Shaders browse
        │
        ▼
┌────────────────────────────────────────────────┐
│  content.py: search_content(mc_version, ...)   │
│                                                │
│  For each search result:                       │
│  1. Ask Modrinth for its file list             │
│  2. Is there a build for THIS MC version?      │
│     NO  → dropped BEFORE rendering             │
│           (the user never sees it)             │
│     YES → shown                                │
│                                                │
│  Download time re-checks (defense in depth):   │
│  get_content_download() refuses a file with    │
│  no build for the selected version             │
└────────────────────────────────────────────────┘
```

### Installed-Content Verdict (packformat.py)

```
┌────────────────────────────────────────────────┐
│  pack_verdict(zip_path, targets)               │
│                                                │
│  Reads pack.mcmeta INSIDE the zip:             │
│  ├── not a zip / unreadable                    │
│  │     → ok=False  "truncated download?"       │
│  ├── pack.mcmeta inside a folder               │
│  │     → ok=False  "game never reads it"       │
│  ├── no pack.mcmeta / invalid JSON             │
│  │     → ok=False                              │
│  ├── declares no pack_format                   │
│  │     → ok=False  (never guessed at)          │
│  └── pack_format / supported_formats /         │
│      min-max keys vs targets (one per          │
│      installed MC version)                     │
│        all covered    → ok=True                │
│        any missing    → ok=False + WHY         │
│  targets unknown (snapshot) → ok=None          │
│  (never treated as a problem)                  │
│                                                │
│  shader_verdict(): same idea, but shaders      │
│  have no pack_format - it checks the           │
│  shaders/ folder STRUCTURE instead             │
└────────────────────────────────────────────────┘
```

### The Unified Doctor (doctor.py: run_doctor)

```
         run_doctor(mc, loader, auto_fix, include=(...))
                          │
     ┌────────┬───────────┼────────────┬─────────────┐
     ▼        ▼           ▼            ▼             ▼
   mods   resourcepacks  shaders   modpacks      plugins
 (delegates  pack_format  shaders/  marker vs    server
  to mods.   verdicts +   folder    profile:     plugin
  mod_doctor) repair       structure missing MC   checks
     │        │           │       version,        │
     │        │           │       gutted mods,    │
     │        │           │       lying marker    │
     ▼        ▼           ▼            ▼             ▼
┌────────────────────────────────────────────────┐
│  Report: {checked, problems, fixed, unfixed,   │
│  sections}; entries: section/kind/item/        │
│  detail/fixed/fix                              │
│                                                │
│  SAFETY RULES:                                 │
│  - unfixable things (corrupt zip, gutted       │
│    pack) are REPORTED, never deleted           │
│  - repairs are atomic (temp file +             │
│    os.replace) - a crash can never leave a     │
│    half-written pack                           │
│  - packs with no declared format are never     │
│    "fixed" into one                            │
└────────────────────────────────────────────────┘
```

The doctor runs from THREE places: at every game launch (offline, fast,
best-effort), from the Mods tab with a one-click fix on flagged items,
and per-section for future UI hooks. Suite: tools/test_content_doctor.py.

---

## 7. Modpack Install Flow

Modpacks are the two-phase content: download the ARCHIVE, then build a
whole isolated profile from it. Each phase reports its own progress.

```
User clicks Install on a pack (row or detail dialog)
        │
        ▼
┌────────────────────────────────────────────────┐
│  PHASE 1: get the archive                      │
│  Modrinth:  get_modpack_file(version=None)     │
│             → newest build for the selected    │
│             MC version, else newest overall    │
│             (detail dialog can pin an EXACT    │
│             published version instead)         │
│  CurseForge: same idea, different API          │
│  → run_install(url, ...)                       │
│     URL must pass the trusted-host ALLOWLIST   │
│     (before a single byte is fetched)          │
│  → download_content(url, progress_cb)          │
│     "Downloading modpack... 42%" (byte pct)    │
│     retry + resume supported                   │
└────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────┐
│  PHASE 2: build the profile                    │
│  install_modpack_from_url(archive)             │
│                                                │
│  1. Detect manifest (Modrinth .mrpack /        │
│     CurseForge manifest.json / mcbrawlers)     │
│  2. Read the pack's DECLARED Minecraft version │
│     + loader - the pack installs its OWN       │
│     version, the Play-tab selection doesn't    │
│     matter (that's the point of the version    │
│     picker)                                    │
│  3. Create isolated profile dir + mods/,       │
│     resourcepacks/, shaderpacks/ inside it     │
│  4. Resolve + download every mod the pack      │
│     lists (through the global cache dedup)     │
│  5. Write the tracking marker the doctor and   │
│     the modpacks tab both read                 │
└────────────────────────────────────────────────┘
        │
        ▼
  Play tab lists the pack as its own entry;
  launching it uses the pack's version + loader.
  If its mods later vanish or its MC version is
  uninstalled, run_doctor's modpacks section is
  the thing that notices and says what to do.
```
