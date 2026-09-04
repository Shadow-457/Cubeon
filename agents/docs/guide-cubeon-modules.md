# The `cubeon/` Package - Module Reference

> Detailed guide to every module in the business logic layer. Each section explains the module's purpose, key functions, and how it connects to the rest of the system.

---

## Table of Contents

1. [paths.py - Where Everything Lives](#pathspy)
2. [config.py - Settings & Identity](#configpy)
3. [versions.py - Minecraft Version Management](#versionspy)
4. [mod_loaders.py - Fabric, Forge, etc.](#mod_loaderspy)
5. [mods.py - Per-Profile Mod Management](#modspy)
6. [modpacks.py - One-Click Modpack Installs](#modpackspy)
7. [launch.py - Starting the Game](#launchpy)
8. [skins.py - Skin Upload & Network Publishing](#skinspy)
9. [csl.py - CustomSkinLoader Setup](#cslpy)
10. [capes.py - Cape Management](#capespy)
11. [cosmetics.py - Pixel Hats](#cosmeticspy)
12. [server.py - Local Server Hosting](#serverpy)
13. [friends.py - Social Layer Client](#friendspy)
14. [invites.py - Invite Codes](#invitespy)
15. [p2p.py - Direct Connections](#p2ppy)
16. [theme.py - Design System](#themepy)
17. [backup.py - Data Backup](#backuppy)

---

## paths.py

**Purpose:** Every filesystem path in one place. If you need to know where something lives on disk, look here.

**Key constants:**

| Constant | What It Points To |
|----------|-------------------|
| `MINECRAFT_DIR` | `~/.minecraft` (the shared game directory) |
| `MODS_DIR` | `~/.minecraft/mods` |
| `CUBEON_HOME` | `~/.cubeon_launcher/` (all Cubeon-specific data) |
| `CONFIG_PATH` | `~/.cubeon_launcher/config.json` |
| `SKINS_DIR` | `~/.cubeon_launcher/skins/` |
| `CAPES_DIR` | `~/.cubeon_launcher/capes/` |
| `PROFILES_DIR` | `~/.cubeon_launcher/mod_profiles/` |
| `SERVERS_DIR` | `~/.cubeon_launcher/servers/` |
| `CSL_DIR` | `~/.minecraft/CustomSkinLoader/` |
| `BIN_DIR` | `~/.cubeon_launcher/bin/` (downloaded helper executables) |

**Key function:** `ensure_dirs()` - runs at import time, creates every directory Cubeon needs. If a folder can't be created (permissions), it logs a warning but doesn't crash - each feature handles its own missing directory gracefully.

---

## config.py

**Purpose:** Loads and saves settings. Also manages the machine's stable identity (auth_key.json).

**How config works:**

```python
cfg = core.load_config()  # reads ~/.cubeon_launcher/config.json
cfg["username"] = "Steve"
core.save_config(cfg)     # writes it back
```

The config is a flat dictionary. `DEFAULT_CONFIG` defines every known key with a default value. On load, `{**DEFAULT, **loaded}` merges saved values over defaults - so adding a new key to `DEFAULT_CONFIG` automatically gives existing installs the default.

**Default config keys:**
- `username` - display name (3-16 chars, letters/numbers/underscores)
- `ram_mb` - Java heap size in megabytes
- `last_version` - which version was selected last time
- `java_path` - custom Java executable (None = auto-detect)
- `width`, `height` - game window resolution
- `active_skin` - filename of the selected skin in SKINS_DIR
- `active_cape` - filename of the selected cape in CAPES_DIR
- `manage_skin_mod` - whether Cubeon auto-installs CustomSkinLoader
- `server_ram_mb` - RAM for the local server
- `cubeon_name` - the claimed social handle (Friends tab)
- `version_labels` - per-version display nicknames

**Identity system (`auth_key.json`):**

The identity file holds two things:
- `public_uuid` - a random v4 UUID, sent to Minecraft as `--uuid` and used as the skin network key
- `secret_token` - a private secret (`sec_` + 64 hex chars), used to authorize backend writes

The UUID **never changes** when you rename your username. This is the whole point: your saves, skins, and friends list are tied to the UUID, not the name.

`ensure_auth_key()` is idempotent and self-healing: if the file is missing, it creates one. If it's corrupt, it repairs it. If it has the old key names (`uuid`/`secret`), it migrates to the new names (`public_uuid`/`secret_token`) without regenerating either value.

---

## versions.py

**Purpose:** Installs Minecraft versions from Mojang's manifest.

**Key functions:**

| Function | What It Does |
|----------|-------------|
| `get_installed_versions()` | Scans `~/.minecraft/versions/` for installed versions |
| `get_available_versions(include_snapshots)` | Fetches the full version list from Mojang |
| `install_version(version_id, progress_cb, status_cb, max_cb)` | Downloads and installs a version |
| `delete_version(version_id)` | Removes a version's folder from `~/.minecraft/versions/` |
| `extract_mc_version(version_id)` | Extracts the numeric MC version from a launchable id (e.g. `fabric-loader-0.15.11-1.20.1` → `1.20.1`) |

**How it uses minecraft-launcher-lib:**
The heavy lifting (downloading assets, libraries, client.jar) is done by `minecraft_launcher_lib`. Cubeon just orchestrates the callbacks and handles progress reporting.

---

## mod_loaders.py

**Purpose:** Installs mod loaders (Fabric, Quilt, Forge, NeoForge) on top of a Minecraft version.

**Key constants:**

```python
SUPPORTED_LOADERS = {
    "vanilla": "Vanilla",
    "fabric": "Fabric",
    "quilt": "Quilt",
    "forge": "Forge",
    "neoforge": "NeoForge",
}

MOD_CAPABLE_LOADERS = ("fabric", "quilt", "forge", "neoforge")
```

`MOD_CAPABLE_LOADERS` is the single source of truth for "which loaders can actually load mods." Other modules check against this instead of re-deriving their own list.

**How loader installation works:**
1. `install_mod_loader(loader_id, mc_version, ...)` calls `minecraft_launcher_lib`'s unified loader API
2. It diffs the installed versions before/after to find the new launchable id
3. Returns the new id (e.g. `fabric-loader-0.15.11-1.20.1`)

**How loader detection works:**
`find_installed_loader_version()` scans installed version ids for one that contains both the MC version and the loader name. It's sorted deterministically to avoid a bug where Python's set iteration order caused different loaders to be picked on different runs.

---

## mods.py

**Purpose:** Per-(version, loader) mod management. This is one of the most important modules.

**The profile model:**
- Each (version, loader) combo gets its own folder under `~/.cubeon_launcher/mod_profiles/`
- Example: `mod_profiles/1.20.1-fabric/` holds all Fabric mods for 1.20.1
- Each folder has a `_profile.json` metadata file recording `{mc_version, loader}`
- Mod jars live directly in the profile folder
- A `.cubeon.json` sidecar file next to each jar records its Modrinth slug

**Key functions:**

| Function | What It Does |
|----------|-------------|
| `list_mods(mc_version, loader)` | Returns all mods in a profile (enabled + disabled) |
| `toggle_mod(mc_version, loader, filename)` | Renames `foo.jar` ↔ `foo.jar.disabled` |
| `delete_mod(mc_version, loader, filename)` | Removes the jar + its sidecar |
| `install_local_mod(src_path, mc_version, loader)` | Copies a local .jar into the profile |
| `sync_mods_to_game(mc_version, loader)` | **The critical function:** copies enabled jars from the profile into `.minecraft/mods/` |
| `get_recommended_mods(...)` | Fetches popular mods from Modrinth |
| `search_mods(query, ...)` | Searches Modrinth |
| `download_mod(url, filename, ...)` | Downloads a mod jar into the profile |

**The sync step (`sync_mods_to_game`):**
This runs at every launch. It:
1. Deletes everything in `.minecraft/mods/`
2. Copies every *enabled* `.jar` from the active profile into `.minecraft/mods/`

This is what makes per-profile mods work: the game only sees `.minecraft/mods/`, so Cubeon has to copy the right jars there before launch.

**The bug this fixed:** Previously, `sync_mods_to_game()` was called without the loader argument, which silently treated it as "vanilla" and wiped `.minecraft/mods/` without restoring anything. That's why mods "sometimes worked, sometimes didn't."

---

## modpacks.py

**Purpose:** Installs Modrinth `.mrpack` files - one-click modpack installs.

**What a `.mrpack` is:** A ZIP file containing:
- `modrinth.index.json` - the manifest (MC version, loader, list of mods with download URLs)
- `overrides/` - config files, resource packs, etc. that get copied into `.minecraft/`

**Install flow:**
1. Download the `.mrpack` ZIP
2. Read `modrinth.index.json` to get MC version + loader + mod list
3. Install the MC version (if not already installed)
4. Install the mod loader (if not already installed)
5. Download each mod jar into the profile folder (using the global cache for dedup)
6. Extract `overrides/` into `.minecraft/`
7. Write `_modpack.json` metadata so the tab can list it as installed

**Security:** Download URLs are restricted to a host allowlist (modrinth.com, github.com, gitlab.com). File paths are checked for zip-slip/traversal attacks. File hashes are verified when the manifest provides them.

---

## launch.py

**Purpose:** Builds the Java command and starts the Minecraft process.

**The launch sequence:**
1. `build_launch_command()` - constructs the full `java -Xmx... -cp ...` command
2. `launch_game()` - starts the process, sets up stdout draining, starts the exit watcher

**Key detail:** Minecraft's stdout is a pipe with a ~64KB buffer. If nothing reads it, the game blocks on its next write and hangs forever. So `launch_game()` starts a daemon thread that continuously reads stdout, storing the last 200 lines for crash reporting.

**Client.json repair:** Older Cubeon versions had a sanitizer that deleted argument entries it couldn't parse, corrupting TLauncher-derived installs permanently. `launch.py` has two repair functions:
- `_sanitize_client_json()` - renames TLauncher's `values` key to `value` (what mll expects)
- `_restore_emptied_arguments()` - rebuilds an entirely emptied arguments block from a vanilla template

Both run before every launch and are idempotent (no-ops on healthy installs).

---

## skins.py

**Purpose:** Manages custom skins locally AND publishes them to the network.

**Two mechanisms:**
1. **LocalSkin** - copies the skin to `~/.minecraft/CustomSkinLoader/LocalSkin/skins/<USERNAME>.png`. Only YOU see it. Works offline.
2. **Network publishing** - uploads the skin to the Cloudflare Worker, keyed by your UUID. Other Cubeon players see it via CSL's network lookup.

**Write-frugal publishing:**
The Worker runs on Cloudflare's free tier with strict KV write limits. So `_publish_skin()` only fires when something actually changed:
- Username changed → heartbeat only (one KV write)
- Skin PNG changed → upload only (one KV write)
- Nothing changed → no network call at all

The publish state is tracked in `skin_net.json` (separate from config to avoid racing the main thread's `save_config()`).

---

## csl.py

**Purpose:** Installs and configures CustomSkinLoader (CSL) - the mod that makes skins work offline.

**Why CSL is needed:** Vanilla Minecraft with offline/cracked auth has no session server to fetch skins from. You always see Steve/Alex. CSL replaces that lookup with a configurable list of skin sources.

**What this module does:**
1. Downloads the CSL jar into the active mod profile (via Modrinth)
2. Registers two skin sources in CSL's ExtraList:
   - **Cubeon** - the network API (serves your uploaded skin + shared cape)
   - **CubeonLocalSkin** - the local file (serves your skin to yourself)

**The load-order trick:** CSL merges sources in order and is "first-source-wins" per texture slot. Cubeon's entries are prepended to the load list so they win over Mojang (which would otherwise serve a premium player's skin if your name matches theirs). The `./` in the cape path (`LocalSkin/./capes/...`) is load-bearing: it resolves to the same file but compares differently, dodging CSL's dedupe logic.

---

## capes.py

**Purpose:** Same as skins but for capes. Upload a cape PNG, store it locally, sync to CSL.

Capes work identically to skins: stored in `~/.cubeon_launcher/capes/`, synced to `~/.minecraft/CustomSkinLoader/LocalSkin/capes/<USERNAME>.png`, and optionally published to the network.

---

## cosmetics.py

**Purpose:** Pixel hats baked into the skin's hat layer.

**How it works:**
1. A hat is a 32x16 pixel template that maps to Minecraft's hat layer region
2. `apply_hat_layer(skin, hat_id)` composites the hat over the skin
3. `compose_skin_with_hat(cfg)` builds the full composed sheet (active skin + hat)
4. The composed sheet is what gets synced to CSL and published to the network

No extra mods needed - the hat layer is a built-in Minecraft feature.

---

## server.py

**Purpose:** Manages a local Paper server for the selected version.

**Key capabilities:**
- Install Paper server jar (from papermc.io or a local file)
- Start/stop the server process
- Edit server.properties (motd, gamemode, difficulty, etc.)
- Manage plugins (install from Modrinth, toggle enable/disable)
- Whitelist management (add/remove players)
- Orphan detection (finds servers left running from a previous Cubeon session)
- High-ping optimization preset ("Smooth mode")

**The orphan problem:** Servers are started detached (`start_new_session=True`) so closing the terminal can't kill them. But this means a Cubeon restart leaves a running server that `_server_processes` knows nothing about. The fix: `world_lock_holder()` uses `fcntl.F_GETLK` to probe the world's `session.lock` for the actual holder PID, regardless of whether Cubeon tracks it.

---

## friends.py

**Purpose:** The client for the realtime social system.

**Three layers:**
1. **Name format + validation** - pure, offline, testable with no network
2. **Identity file** (`identity.json`) - this machine's claimed Cubeon name + owning secret
3. **Network client** - HTTP for name claims/lookups, WebSocket for realtime (presence, chat, calls)

**The Cubeon name system:**
- Unique social handle (3-16 chars, letters/numbers/underscores)
- Owned by a 256-bit secret stored in `identity.json` (0600 permissions)
- The Worker stores only the secret's SHA-256 (no plaintext)
- No signup, no email - ownership is created at claim time

**The WebSocket client (`FriendsClient`):**
- Connects to the Durable Object via WebSocket
- Authenticates with the first `hello` frame (secret goes in the frame, not the URL)
- Handles reconnection with exponential backoff
- Carries presence, chat, voice signalling, and P2P session data

---

## invites.py

**Purpose:** Invite codes that map to server addresses.

**Code format:** `CUBE-7F4K-9QMN` - two groups of 4 characters from a 25-character unambiguous alphabet (no 0/O, 1/I/L, etc.).

**How it works:**
1. Host generates a code + secret, claims it on the Worker
2. Host shares the code with friends
3. Friend types the code, the Worker resolves it to the server address
4. Friend connects

The code is an indirection layer: the address behind it can change (tunnel reassigned), but the code stays the same. The secret proves ownership and allows the host to update the address.

---

## p2p.py

**Purpose:** Direct player-to-player connections for hosting worlds without a dedicated server.

**The strategy (relay-first):**
1. Session starts on a relay (the friends WebSocket) - guaranteed path, works through NATs
2. While data flows, both peers run STUN probes to diagnose NAT type
3. If direct connection is possible, they coordinate a "spray" of UDP packets to punch through
4. First authenticated direct frame proves the path - stream flips to UDP
5. If spray fails, session stays on relay (degraded ping, never a failure)

---

## theme.py

**Purpose:** The design system - colors, fonts, radii, and the Flet theme.

**Key concept:** One small corner radius (`RADIUS = 2`) drives the entire UI. Minecraft is cubic; the UI is too. No pill-shaped buttons, no rounded cards.

**Color discipline:** 60% dark canvas, 30% structural neutrals, 10% chromatic. Green (ACCENT) is the hero. Diamond cyan (INFO) is the secondary. Gold (WARNING) and redstone (DANGER) are semantic. Every fill has an explicit `on_*` foreground chosen for contrast.

**`apply_page_theme(page)`:** Installs the design system onto Flet's own controls (dialogs, buttons, menus, scrollbars) so they match the hand-built Container widgets.

---

## backup.py

**Purpose:** Zips Cubeon-managed data into restore points.

**What gets backed up:**
- Config (always)
- Mod profiles (always)
- Skins + capes (always)
- Profile picture (always)
- Server configs (always)
- World saves (opt-in, can be large)

**Scheduling:** Configurable daily/weekly automatic backups. Checked on a 30-minute timer thread. Rotation keeps the last N backups and deletes older ones.
