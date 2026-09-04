# The UI Layer - `main.py` + `ui/`

> How the user interface is structured, how tabs are built, and how the Play button orchestrates everything.

---

## Architecture

```
main.py
  ├── Sidebar (nav buttons, brand, "Signed in as")
  ├── Content area (switches between tabs)
  │     ├── play_tab          (inline in main.py, ~1500 lines)
  │     ├── profile_tab       (inline in main.py, ~200 lines)
  │     ├── settings_tab      (inline in main.py, ~300 lines)
  │     ├── mods_tab          (ui/mods_tab.py)
  │     ├── modpacks_tab      (ui/modpacks_tab.py)
  │     ├── server_console_tab    (ui/server_tab.py)
  │     ├── server_plugins_tab    (ui/server_tab.py)
  │     └── server_settings_tab   (ui/server_tab.py)
  └── Backup system (Settings section)
```

**Why Play/Profile/Settings are inline:** These tabs have the most complex state wiring (version dropdown, loader toggle, play button, username fields, avatar). Keeping them in `main.py` avoids passing 50+ widget references between files. The other tabs are simpler and live in `ui/`.

---

## main.py - The Core

### Startup Flow

```python
def main(page: ft.Page):
    # 1. Thread-safe UI
    thread_safe_ui.install(page)

    # 2. Window config
    page.title = "Cubeon Launcher"
    page.window.width = 1180
    ...

    # 3. Load config
    cfg = core.load_config()

    # 4. Ensure identity
    core.ensure_auth_key()

    # 5. Build sidebar
    sidebar = build_sidebar(...)

    # 6. Build all tabs
    play_tab = build_play_tab(...)
    mods_tab, refresh_mods, ... = build_mods_tab(...)
    modpacks_tab, ... = build_modpacks_tab(...)
    server_tab, ... = build_server_tab(...)

    # 6b. Friends has no tab - start the headless service the in-game mod drives
    friends_service = FriendsService(cfg, state, friends_client); friends_service.start()

    # 7. First paint
    refresh_version_list()

    # 8. Bring up Friends connection
    friends_client.connect()
```

### The Sidebar

The sidebar is a fixed 200px-wide column on the left:
- **Brand** - animated cube GIF + "Cubeon" wordmark
- **Nav items** - Play, Mods, Modpacks, Friends, Servers (expandable group), Profile, Settings
- **"Signed in as"** - avatar + username, clickable to open Profile tab

Each nav button has a hover state (faint wash) and an active state (green tint + accent bar). The Servers group is collapsible with a chevron.

### Tab Switching

```python
def switch_tab(key):
    active_tab["value"] = key
    # Update nav button styles
    for k, btn in nav_buttons.items():
        _style_nav_button(btn, k == key)
    # Replace content area
    content_area.content = ft.Container(tabs[key], ...)
    # Trigger tab-specific refresh
    if key == "mods":
        refresh_mods_list()
    elif key == "profile":
        refresh_profile_tab()
    ...
    page.update()
```

### The Play Tab (Inline)

The Play tab is the most complex. It contains:

**Hero panel:**
- Big title ("Minecraft 1.20.1")
- Loader chip ("Fabric")
- Rename/Delete instance buttons
- Account field (username)
- Version dropdown (with online/offline filtering)
- Loader segmented toggle (Vanilla/Fabric/Quilt/Forge/NeoForge)
- PLAY button (changes color/text based on state)
- Progress bar + status text

**Play button states:**
| State | Color | Text | Action |
|-------|-------|------|--------|
| `play` | Green | "PLAY" | Launches game |
| `download` | Cyan | "DOWNLOAD & PLAY" | Installs version, then launches |
| `busy` | Dim | "WORKING..." | Disabled, shows progress |
| `running` | Green accent | "GAME RUNNING..." | Disabled while game is open |
| `incomplete` | Red | "INCOMPLETE INSTALL" | Disabled, version is broken |

**Version filtering:**
The online version list has 600+ entries. A live filter field narrows it as you type (e.g. "1.20" → only 1.20.x releases). The filter is hidden when only installed versions are shown (short list, no need).

### The Profile Tab (Inline)

Shows:
- Avatar with animated parrot
- Username field (mirrors the Play tab's field)
- Profile picture upload/remove
- In-game skin section (reuses `build_skin_section()` from `skin_tab.py`)
- Hat picker
- Cape picker

### The Settings Tab (Inline)

Shows:
- RAM slider (bounded by system RAM, with warning above recommended)
- Window resolution fields
- Java path field
- Backup system (enable/disable, frequency, restore)

---

## ui/mods_tab.py

**Purpose:** Browse/download mods from Modrinth, manage installed mods.

**Structure:**
```
Header ("Mods" / "Resource Packs" / "Shaders")
  ├── Content-type tabs (text_tab style, underline indicator)
  ├── Search field (live search with debounce)
  ├── Category chips (collapsed behind "..." button)
  ├── Browse results (paginated, 5 per page)
  │     ├── Recommended/popular mods
  │     └── Search results
  └── Installed list
        ├── Filter field
        ├── Mod rows (icon + name + size + toggle + delete)
        └── "Show all" expander
```

**Key behaviors:**
- **Live search:** Typing triggers a debounced search (450ms). No search button needed.
- **Category filters:** Collapsed behind a "..." button to save vertical space. Green dot shows when a filter is active.
- **Content type switching:** The same UI works for Mods, Resource Packs, and Shaders. Mods use per-profile folders; resource packs/shaders go into shared game folders.
- **Mod icons:** Installed mods only store their Modrinth slug, not the icon URL. A bulk slug→icon lookup fetches real art after the list renders.

---

## ui/modpacks_tab.py

**Purpose:** Browse/install Modrinth modpacks.

**Structure:**
```
Installed packs list
  ├── Pack cards (name, version, mods, Play button)
  └── "Install from file" button

Browse packs
  ├── Search field
  ├── Pack results (icon, name, description, install button)
  └── Install flow (confirmation → progress → done)
```

**Install flow:**
1. User clicks "Install" on a browse result
2. Summary dialog shows pack name, version, mod count
3. User confirms
4. Background thread: download `.mrpack` → install MC version → install loader → download mods → extract overrides
5. Pack appears in "Installed" list

---

## Friends - there is no Friends tab

**Purpose:** Social features - Cubeon name, friends list, friend requests, P2P worlds.

**Where the UI lives:** inside Minecraft. `mod/` is a Fabric mod that adds a
Friends button to the game's own pause menu and draws Minecraft's widgets. You
want your friends list when you're *in a world* deciding who to invite, not
behind an alt-tab, so the UI went to where the player already is.

**Where the logic lives:** `cubeon/friends_service.py` - headless, no Flet. It
owns the realtime client's callbacks, the P2P state machine, and a notification
feed. `cubeon/local_api.py` exposes it over 127.0.0.1 with a random token
written 0600 to `~/.cubeon_launcher/local_api.json`; the mod reads that file.

```
Minecraft (mod/)                 launcher (this process)
  CubeonFriendsScreen  --HTTP-->  local_api.py  -->  FriendsService
    polls GET /friends, /status, /events?since=
    POSTs /invite /join /add /accept /decline /remove
          /whitelist /rename /cancel /retry
```

**Key behaviors:**
- Connects at startup, so presence is live before the game even launches
- One jar per Minecraft bracket (`mod/brackets.json`), installed into the active
  Fabric profile at launch by `cubeon/cubeonfriends.py`
- Every notification the tab used to toast is an event in the feed the mod drains

**Adding an in-game action:** add the method to `FriendsService`, a setter +
route to `local_api.py`, a call to the mod's `Bridge.java`, and a button in
`CubeonFriendsScreen.java`. `tools/test_friends_service.py::test_contract`
reads the mod's source and fails if the launcher doesn't serve what it calls.

---

## ui/server_tab.py

**Purpose:** Local Paper server management.

**Three sub-tabs:**
1. **Console** - live server output, command input, start/stop buttons
2. **Plugins** - install/search/toggle/delete plugins from Modrinth
3. **Settings** - motd, gamemode, difficulty, max players, view distance, whitelist, EULA

**Key behaviors:**
- Server process is tracked per-version in `_server_processes`
- Orphan detection finds servers left running from previous sessions
- "Smooth mode" auto-installs a curated low-ping plugin stack
- AuthMe is auto-installed and protected from deletion (it's the login security layer for public servers)

---

## ui/skin_tab.py

**Purpose:** Skin/cape/hat management. Embedded inside the Profile tab.

**Structure:**
```
In-Game Skin
  ├── Preview (160x260, rendered from actual pixels)
  ├── Your Skins list (each with Use/Delete menu)
  └── Upload skin button

Cosmetics - hat
  ├── Hat tiles (None + 8 hats, each with preview)
  └── Status text

Cape
  ├── Preview (150x232)
  ├── Your Capes list (Cubeon Cape default + custom)
  └── Upload cape button
```

**Key behaviors:**
- Previews are rendered from the actual skin pixels using PIL (no external API)
- The skin section rebuilds every time the Profile tab opens to reflect the current version/loader
- Uses a shared FilePicker passed in from main.py (not creating its own each rebuild)

---

## Shared Patterns Across Tabs

### Builder Functions

Every tab module exports a builder function:

```python
def build_mods_tab(page, cfg, state, version_dropdown, *, section_label, BG, ...):
    # Build widgets
    return mods_tab, refresh_mods_list, load_recommended_mods, ...
```

Returns: (tab_widget, callback1, callback2, ...). The callbacks let `main.py` trigger refreshes from other tabs (e.g., "version changed → refresh mods list").

### State Sharing

Two shared dicts flow through the system:
- `cfg` - persistent settings (saved to disk)
- `state` - transient runtime state (rebuilt on startup)

Both are passed by reference, so any module can read/write them.

### Background Threads

Every long operation (download, install, network call) runs on a daemon thread:

```python
def worker():
    try:
        result = core.do_something(...)
        # Update UI
        status_text.value = result
        page.update()
    except Exception as ex:
        status_text.value = f"Error: {ex}"
        page.update()

threading.Thread(target=worker, daemon=True).start()
```

### Error Display

Business logic returns result dicts, not exceptions:

```python
result = core.some_operation()
if result["ok"]:
    status_text.value = "Success!"
else:
    status_text.value = result["message"]  # Already human-readable
```

### FilePicker Registration

Flet FilePickers must be registered once and reused. Every tab that needs file picking follows this pattern:

```python
# Created once in main.py
skin_file_picker = ft.FilePicker()
page.overlay.append(skin_file_picker)

# Passed to the tab builder
build_skin_section(page, cfg, ..., file_picker=skin_file_picker)

# The tab points on_result at its own handler
file_picker.on_result = on_files_picked
```

Creating a new FilePicker each rebuild would silently break - only the first registration ever receives results.
