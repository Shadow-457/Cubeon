# Data Flow & Configuration

> How data moves through the Cubeon system - config files, identity, mod profiles, and the data lifecycle.

---

## Filesystem Layout

Everything Cubeon touches lives under two roots:

```
~/.minecraft/                          # Shared game directory
├── versions/                          # Installed MC versions (one folder per version)
│   └── 1.20.1/
│       ├── 1.20.1.jar                 # Client jar
│       ├── 1.20.1.json                # Version manifest (may be repaired by launch.py)
│       └── 1.20.1/                    # Assets, libraries, etc.
├── mods/                              # Active mod profile (synced at launch)
│   ├── sodium-fabric-1.20.1-0.5.8.jar
│   └── fabric-api-0.92.0-1.20.1.jar
├── resourcepacks/                     # Shared resource packs (all versions)
├── shaderpacks/                       # Shared shader packs (all versions)
├── CustomSkinLoader/                  # CSL mod data
│   ├── LocalSkin/skins/<USERNAME>.png # Your skin (local-only)
│   ├── LocalSkin/capes/<USERNAME>.png # Your cape (local-only)
│   └── ExtraList/                     # Cubeon's skin source registrations
└── versions/<loader-id>/             # Loader-specific version (e.g. fabric-loader-0.15.11-1.20.1)

~/.cubeon_launcher/                    # All Cubeon-specific data
├── config.json                        # Launcher settings (username, RAM, etc.)
├── auth_key.json                      # Stable identity (UUID + secret)
├── identity.json                      # Cubeon name + secret (Friends)
├── invites.json                       # Invite codes this machine minted/joined
├── skin_net.json                      # Last published skin state (write-frugality)
├── friends_cache.json                 # Cached friends roster
├── skins/                             # Uploaded skin PNGs
│   ├── skins.json                     # Metadata for all uploaded skins
│   └── <name>_<hash>.png
├── capes/                             # Uploaded cape PNGs
│   ├── capes.json                     # Metadata for all uploaded capes
│   └── <name>_<hash>.png
├── profile/                           # Profile picture
│   └── avatar.png
├── mod_profiles/                      # Per-(version, loader) mod folders
│   ├── 1.20.1-fabric/
│   │   ├── _profile.json              # {mc_version: "1.20.1", loader: "fabric"}
│   │   ├── sodium-fabric-1.20.1-0.5.8.jar
│   │   └── sodium-fabric-1.20.1-0.5.8.cubeon.json  # {"slug": "sodium"}
│   └── 1.20.1-forge/
│       └── ...
├── servers/                           # Local Paper server data
│   └── 1.20.1/
│       ├── server-paper.jar
│       ├── server.properties
│       ├── eula.txt
│       ├── world/                     # Server world
│       └── plugins/                   # Server plugins
├── global_cache/mods/                 # Dedup cache (SHA-256-keyed)
│   ├── <sha256>.jar                   # One copy per unique mod
│   └── .hash_index.json              # sha1/sha512 → sha256 alias map
├── backups/                           # Backup zips
├── cache/                             # API response cache (24h TTL)
├── bin/                               # Downloaded helper executables
├── p2p_sessions/                      # P2P session state
└── logs/                              # (future) structured log files
```

---

## Config Lifecycle

### On Startup

```python
cfg = core.load_config()
# Reads ~/.cubeon_launcher/config.json
# Merges with DEFAULT_CONFIG (new keys get defaults)
# Seeds ram_mb from detected system RAM on first run
```

### During Use

The `cfg` dict is mutated directly by UI callbacks:

```python
# User changes username
cfg["username"] = "Steve"
core.save_config(cfg)

# User adjusts RAM slider
cfg["ram_mb"] = 8192
core.save_config(cfg)
```

`save_config()` writes the entire dict to `config.json`. It's called after every meaningful change.

### The Two Dicts

| Dict | Persisted? | Contents |
|------|-----------|----------|
| `cfg` | Yes (config.json) | Username, RAM, version, skin, settings |
| `state` | No (rebuilt from filesystem) | Selected version, installed versions, running process, mod loader |

---

## Identity Lifecycle

### First Launch

```
1. ensure_auth_key() → creates ~/.cubeon_launcher/auth_key.json
   ├── public_uuid: "a1b2c3d4-..."  (random v4)
   └── secret_token: "sec_..."       (128 hex chars)
```

### Username Change

```
1. User types new username
2. cfg["username"] = "newname"
3. sync_local_skin_to_csl(cfg)
   → copies skin to LocalSkin/skins/newname.png
   → deletes LocalSkin/skins/oldname.png
4. save_config(cfg)
5. _publish_skin_async(cfg)
   → heartbeat: POST /api/heartbeat {username: "newname", uuid: <same>}
   → Worker updates pointer:newname → <same UUID>
```

The UUID never changes. Only the pointer moves.

### Game Launch

```
1. build_launch_command()
   → --uuid <public_uuid> from auth_key.json
   → --username <cfg["username"]>
2. Minecraft joins servers with this UUID
3. Servers store per-UUID data (inventory, position)
4. Renaming never resets this data
```

---

## Mod Profile Lifecycle

### Installing a Mod

```
1. User clicks "Download" on a Modrinth search result
2. download_mod(url, filename, mc_version="1.20.1", loader="fabric", slug="sodium")
3. Profile dir: ~/.cubeon_launcher/mod_profiles/1.20.1-fabric/
4. Jar saved: sodium-fabric-1.20.1-0.5.8.jar
5. Sidecar saved: sodium-fabric-1.20.1-0.5.8.cubeon.json → {"slug": "sodium"}
6. (Optional) Global cache: ~/.cubeon_launcher/global_cache/mods/<sha256>.jar
```

### Toggling a Mod

```
1. User clicks the toggle switch
2. toggle_mod("1.20.1", "fabric", "sodium-fabric-1.20.1-0.5.8.jar")
3. Renames to: sodium-fabric-1.20.1-0.5.8.jar.disabled
4. On next launch, sync_mods_to_game() skips .disabled files
```

### Launch Sync

```
1. sync_mods_to_game("1.20.1", "fabric")
2. Deletes everything in ~/.minecraft/mods/
3. Copies every .jar (not .disabled) from mod_profiles/1.20.1-fabric/
4. Game starts, reads ~/.minecraft/mods/
```

### Version Switch

```
1. User selects "1.21" in the dropdown
2. state["selected_mc_version"] = "1.21"
3. refresh_mods_list() → reads mod_profiles/1.21-fabric/
4. Different profile, different mods shown
5. On launch, sync_mods_to_game("1.21", "fabric") syncs the right profile
```

---

## Skin Network Flow

### Upload

```
1. User picks a skin PNG
2. add_custom_skin(path, "MySkin") → saves to ~/.cubeon_launcher/skins/
3. set_active_skin(cfg, "myskin_abc123.png")
4. sync_local_skin_to_csl(cfg)
   → copies to ~/.minecraft/CustomSkinLoader/LocalSkin/skins/<USERNAME>.png
5. _publish_skin_async(cfg)
   → POST /api/heartbeat {username, uuid} → Worker updates pointer
   → POST /api/skin {uuid, model, skin(base64)} → Worker stores texture
```

### Other Players See It

```
1. Player joins server
2. CSL resolves: GET /skins/<their_name>.json
3. Worker: pointer:name → uuid → skin:uuid → texture URL
4. CSL fetches texture from /textures/<sha256>
5. Renders skin in-game
```

### Rename

```
1. User changes username to "NewName"
2. Heartbeat fires: POST /api/heartbeat {username: "NewName", uuid: <same>}
3. Worker: deletes pointer:oldname, creates pointer:newname → <same uuid>
4. LocalSkin: renames oldname.png → newname.png
5. CSL: next lookup serves newname → same skin
```

---

## Backup Lifecycle

### Manual Backup

```
1. User clicks "Back up now"
2. create_backup() runs on background thread
3. Scans: config.json, mod_profiles/, skins/, capes/, profile/, servers/
4. Writes: ~/.cubeon_launcher/backups/cubeon-backup-2026-08-28_14-30-00.zip
5. Rotates: keeps last N backups, deletes older ones
```

### Scheduled Backup

```
1. _backup_scheduler() thread runs every 30 minutes
2. Checks: is_due() → enabled + interval elapsed since last backup
3. If due: create_backup() + update status
```

### Restore

```
1. User picks a backup .zip
2. restore_backup(path) extracts each entry
3. Routes by top-level folder name to the right root
4. Overwrites existing files, leaves new files alone
```

---

## Data Relationships

```
config.json
  ├── username ──────────► LocalSkin/skins/<USERNAME>.png
  │                        pointer:<username> (Worker)
  ├── active_skin ────────► skins/<filename>.png
  ├── active_cape ────────► capes/<filename>.png
  ├── last_version ───────► version dropdown selection
  └── cubeon_name ────────► identity.json name field

auth_key.json
  ├── public_uuid ────────► Minecraft --uuid
  │                        skin:<uuid> (Worker)
  │                        owner:<uuid> (Worker)
  └── secret_token ───────► Bearer header for Worker writes
                            identity.json secret field

identity.json
  ├── name ───────────────► friends WebSocket hello frame
  ├── secret ─────────────► (same as auth_key.json secret_token)
  └── uuid ───────────────► (same as auth_key.json public_uuid)

mod_profiles/<version>-<loader>/
  ├── _profile.json ──────► records which version+loader this profile is for
  └── *.jar ──────────────► synced to .minecraft/mods/ at launch
      └── *.cubeon.json ──► records the Modrinth slug (for re-download)
```

---

## Key Invariants

1. **UUID never changes.** `auth_key.json` is created once and survives renames, reinstalls, and config resets. Losing it means a new identity (new saves, new skin ownership).

2. **Config always has all keys.** `{**DEFAULT_CONFIG, **loaded}` merge ensures new settings get defaults automatically.

3. **One profile per (version, loader).** Mods are isolated. Switching versions doesn't conflict.

4. **Sync at launch, not at install.** Mods are installed into profiles but only copied to `.minecraft/mods/` at launch time. This means toggling a mod is instant (just rename the jar) and the change takes effect on next launch.

5. **Write-frugal backend.** Every Worker write is gated on "did something actually change?" The free tier has strict limits, so unchanged operations must cost zero writes.

6. **Atomic writes for sensitive files.** `auth_key.json`, `invites.json`, `identity.json`, and `client.json` all use temp-file + `os.replace()` for crash safety. `config.json` is the exception (a known bug).
