# Cubeon Launcher - Developer Guide

> A plain-English walkthrough of how the launcher works, module by module. No assumed knowledge beyond basic Python.

---

## What Is Cubeon?

Cubeon is a **desktop Minecraft launcher** for playing with friends on offline/cracked servers. It's built with Python and Flet (a Flutter-based UI framework). Think of it as a free, simplified alternative to TLauncher or MultiMC - but with a twist: it has a built-in social layer, skin sharing network, and one-click world hosting.

---

## The Big Picture

```
┌──────────────────────────────────────────────────────┐
│                   THE USER SEES                       │
│                                                       │
│   ┌─────────┐    ┌──────────────────────────────┐    │
│   │ Sidebar  │    │       Content Area            │    │
│   │          │    │                                │    │
│   │  Play    │    │  [Tab content lives here]      │    │
│   │  Mods    │    │                                │    │
│   │  Packs   │    │                                │    │
│   │  Friends │    │                                │    │
│   │  Profile │    │                                │    │
│   │  Servers │    │                                │    │
│   │  Settings│    │                                │    │
│   └─────────┘    └──────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
         │                         │
         ▼                         ▼
   ┌───────────┐          ┌────────────────┐
   │  cubeon/   │          │  Cloudflare    │
   │  (Python)  │◄────────►│  Workers (JS)  │
   │  Business  │  HTTP    │  Backend API   │
   │  Logic     │          └────────────────┘
   └───────────┘
         │
         ▼
   ┌───────────┐
   │  Minecraft │
   │  Game      │
   │  (.minecraft)│
   └───────────┘
```

**Three layers:**
1. **UI** (`main.py` + `ui/`) - What the user clicks and sees
2. **Business logic** (`cubeon/`) - Everything behind the scenes (downloading, launching, networking)
3. **Backend** (`worker/`) - Cloudflare Workers that power the skin network, invite codes, and friends system

---

## How Code Is Organized

### The Entry Point: `main.py`

This is a **2,800-line monster** - and that's intentional. It's the single file that:
- Sets up the window, sidebar, and every tab
- Wires all the buttons to their callbacks
- Manages the version dropdown, loader toggle, play button states
- Starts background threads for installs and game launches

**Why so big?** Flet (the UI framework) works best when everything is wired together in one place. Splitting it further would mean passing dozens of widget references between files. The tab modules (`ui/`) are the exception - each one is a self-contained builder function that receives just the widgets it needs.

### The Facade: `launcher_core.py`

This file does almost nothing. It just re-exports everything from `cubeon/` under one import:

```python
import launcher_core as core
core.find_java()      # actually cubeon.launch.find_java()
core.list_mods(...)   # actually cubeon.mods.list_mods(...)
core.install_version(...)  # actually cubeon.versions.install_version(...)
```

This exists so `main.py` and the UI tabs can write `core.something()` instead of importing from a dozen different modules. It's backward compatibility glue - when the code was split out of one big file, this facade kept all the call sites working.

### The Business Logic: `cubeon/`

This is where the real work happens. Every file here is a focused module with **no UI imports** (no `flet`, no `page.update()`). The rule: business logic never touches the UI; the UI calls business logic.

---

## Module-by-Module Walkthrough

### Identity & Config

| Module | What It Does |
|--------|-------------|
| `config.py` | Loads/saves `~/.cubeon_launcher/config.json`. Also manages `auth_key.json` - the machine's stable identity (UUID + secret) that survives username changes. |
| `paths.py` | Every filesystem path in one place. `MINECRAFT_DIR`, `SKINS_DIR`, `SERVERS_DIR`, etc. If you need to know "where does X live on disk?", it's here. |
| `profile.py` | Profile picture upload/remove. Simple file copy to `~/.cubeon_launcher/profile/`. |

**Key concept:** The launcher uses a **dual-layer identity**. Your *username* is just a display name anyone can type. Your *real identity* is a random UUID in `auth_key.json` that never changes. This means renaming yourself doesn't reset your saves, skins, or friends list.

### Version Management

| Module | What It Does |
|--------|-------------|
| `versions.py` | Installs Minecraft versions from Mojang's manifest. Uses `minecraft-launcher-lib` under the hood. |
| `mod_loaders.py` | Installs Fabric, Forge, NeoForge, Quilt. Wraps `minecraft-launcher-lib`'s loader support. |
| `launch.py` | Builds the `java -jar ...` command and starts the game process. Also handles the "client.json repair" for broken TLauncher installs. |

**How launching works:**
1. User clicks Play
2. `launch.py` builds the Java command with the right JVM args, classpath, etc.
3. Starts `subprocess.Popen` with stdout piped
4. A background thread drains stdout (Minecraft writes a LOT)
5. Another thread watches for the process to exit and reports success/crash

### Mod System

| Module | What It Does |
|--------|-------------|
| `mods.py` | Per-(version, loader) mod profiles. Downloads from Modrinth, toggles enabled/disabled, syncs the active profile into `.minecraft/mods` at launch. |
| `modpacks.py` | Installs Modrinth `.mrpack` files - a ZIP with a manifest listing MC version + loader + mods + configs. One click installs everything. |
| `global_mod_cache.py` | Deduplication: one SHA-256-keyed copy of each mod jar, hardlinked into every profile that uses it. |
| `local_cache.py` | In-memory + disk cache for API responses (Modrinth searches, version checks). 24-hour TTL. |

**How mod profiles work:**
- Each (version, loader) combo gets its own folder under `~/.cubeon_launcher/mod_profiles/`
- Example: `mod_profiles/1.20.1-fabric/` holds all Fabric mods for 1.20.1
- At launch, `sync_mods_to_game()` copies enabled jars from the profile into `.minecraft/mods/`
- This means switching versions doesn't conflict - each version has its own isolated mod set

### Skins & Cosmetics

| Module | What It Does |
|--------|-------------|
| `skins.py` | Uploads skins locally AND publishes to the Cloudflare Worker so other players see them. |
| `csl.py` | Installs CustomSkinLoader (the mod that makes skins work offline) and registers Cubeon's skin sources with it. |
| `capes.py` | Same as skins but for capes - stored locally, synced to CSL. |
| `cosmetics.py` | Pixel hats baked into the skin's hat layer. Pure PIL image manipulation. |

**How the skin network works:**
1. Your skin is uploaded to the Worker, keyed by your UUID
2. Other players' CustomSkinLoader asks the Worker "what skin does player X have?"
3. The Worker looks up `pointer:<username>` → `<uuid>` → `skin:<uuid>` → texture URL
4. CSL renders the skin in-game for everyone

### Server Hosting

| Module | What It Does |
|--------|-------------|
| `server.py` | Manages a local Paper server. Install, start/stop, edit properties, manage plugins, whitelist. |
| `minekube.py` | Tunnel sharing via Minekube Connect - makes your local server accessible over the internet. |
| `gate.py` | CubeonGate plugin - per-UUID password protection for public servers. |

### Social Layer

| Module | What It Does |
|--------|-------------|
| `friends.py` | The client for the friends system. Claims a unique "Cubeon name", connects via WebSocket, handles presence/chat/calls. |
| `invites.py` | Invite codes: `CUBE-7F4K-9QMN` maps to your server address. Friends type the code to join. |

### Networking

| Module | What It Does |
|--------|-------------|
| `p2p.py` | Direct player-to-player connections via UDP hole-punching + a relay fallback over the friends WebSocket. |
| `voice.py` | Voice call audio (optional, requires `sounddevice` + `numpy`). |

### Utilities

| Module | What It Does |
|--------|-------------|
| `theme.py` | Design tokens (colors, fonts, radii) and the Flet theme setup. The single source of truth for how the app looks. |
| `thread_safe_ui.py` | Makes `page.update()` safe from background threads (Flet 0.80+ loses updates from non-UI threads). |
| `backup.py` | Zips config + mod profiles + skins + server configs into a single restore point. |
| `emoji.py` | Discord-style `:shortcode:` emoji expansion for chat. |

---

## The UI Layer

### `main.py` - The Orchestrator

This is where everything is wired together. The key flow:

1. **Startup:** Load config → ensure auth key → build sidebar → build all tabs → populate version dropdown
2. **Tab switching:** `switch_tab(key)` replaces `content_area.content` with the selected tab
3. **Play flow:** Validate username → install version if needed → install loader if needed → launch game → monitor stdout → report crash/exit

### `ui/` - Tab Builders

Each tab is a function that returns a Flet Column (the root widget):

```python
# ui/mods_tab.py
def build_mods_tab(page, cfg, state, version_dropdown, *, section_label, BG, SURFACE, ...):
    # ... build all the widgets ...
    return mods_tab, refresh_mods_list, load_recommended_mods, refresh_browse_for_new_profile
```

The return values are the tab widget + callback functions that `main.py` needs to call when state changes (e.g., "refresh the mods list because the user switched versions").

**Why builder functions instead of classes?** Flet works best with plain functions that create and return widget trees. The state lives in `cfg` and `state` dicts that are shared by reference.

---

## The Backend: Cloudflare Workers

Three small JavaScript files power the online features:

| Worker | Purpose | Storage |
|--------|---------|---------|
| `cubeon-skins.js` | Skin uploads, identity heartbeats, CSL lookups | KV (key-value store) |
| `cubeon-invites.js` | Invite code creation/resolution | KV |
| `cubeon-friends.js` | Realtime friends, chat, voice signalling | Durable Object (SQLite) |

**Why Cloudflare Workers?** They're free tier, serverless, and globally distributed. No VPS to maintain. The downside: no persistent database - KV has write limits, so the code is obsessively write-frugal (e.g., skins only upload when the image actually changes).

**Why a Durable Object for friends?** KV's free tier allows ~1,000 writes/day. A single 30-second presence heartbeat would exhaust that. Durable Objects hold WebSocket connections in memory and use SQLite for persistence - no write metering.

---

## Data Flow: A Complete Launch

Here's what happens end-to-end when a user clicks **Play**:

```
User clicks Play
    │
    ▼
main.py: on_play_click()
    │  validates username
    │  saves config
    │  starts background thread
    │
    ▼
main.py: do_install_and_launch()
    │
    ├─ Version not installed? ──► cubeon/versions.py: install_version()
    │                              (downloads from Mojang)
    │
    ├─ Loader needed? ─────────► cubeon/mod_loaders.py: install_mod_loader()
    │                              (downloads Fabric/Forge/etc)
    │
    ├─ Skin sync ──────────────► cubeon/skins.py: sync_local_skin_to_csl()
    │                              (copies skin to CSL folder)
    │                              cubeon/skins.py: _publish_skin_async()
    │                              (uploads to Cloudflare Worker)
    │
    ├─ CSL setup ──────────────► cubeon/csl.py: ensure_ready()
    │                              (installs CSL jar, registers skin sources)
    │
    ├─ Mod sync ───────────────► cubeon/mods.py: sync_mods_to_game()
    │                              (copies enabled jars to .minecraft/mods/)
    │
    └─ Launch ─────────────────► cubeon/launch.py: launch_game()
                                   (builds java command, starts subprocess)
                                   │
                                   ▼
                               Game runs, stdout drained by background thread
                                   │
                                   ▼
                               Game exits → on_exit callback
                                   │  reports crash message or "Ready"
                                   ▼
                               Back to Play button
```

---

## Common Patterns

### Background Threads
Almost every long operation runs on a `threading.Thread(target=..., daemon=True)`. The UI stays responsive while downloads, installs, and network calls happen in the background. `page.update()` is made cross-thread-safe by `cubeon/thread_safe_ui.py`.

### Callbacks, Not Returns
Background threads can't return values to the UI. Instead they mutate shared state (`cfg`, `state`) and call `page.update()` directly. Status messages are set by writing to a `ft.Text.value` and calling `page.update()`.

### The `cfg` Dict
The config dictionary is loaded once at startup and mutated throughout the session. It's the single source of truth for username, RAM, version selection, skin, etc. It's saved to disk with `core.save_config(cfg)` after every meaningful change.

### The `state` Dict
A separate dict for transient runtime state: which version is selected, which loader is active, whether the game is running, installed version IDs. Not persisted to disk - rebuilt from the filesystem on startup.

### Error Handling
Business logic functions never raise into the UI. They return result dicts like `{"ok": True, ...}` or `{"ok": False, "error": "message"}`. The UI checks `ok` and shows the message. This keeps dead buttons from becoming uncaught exceptions.

---

## Where to Start Reading

| If you want to understand... | Start with... |
|------------------------------|---------------|
| How the app starts up | `main.py` lines 1-130 (imports + `main()` function entry) |
| How the sidebar works | `main.py` lines 200-400 (nav items, `build_nav()`, `switch_tab()`) |
| How Play/Launch works | `main.py` `on_play_click()` → `do_install_and_launch()` |
| How mods are managed | `cubeon/mods.py` (especially `sync_mods_to_game()`) |
| How skins work | `cubeon/skins.py` + `cubeon/csl.py` |
| How the friends system works | `cubeon/friends.py` + `worker/cubeon-friends.js` |
| How the design system works | `cubeon/theme.py` (read the module docstring first) |
| How the server hosting works | `cubeon/server.py` |
