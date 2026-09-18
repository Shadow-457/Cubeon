# Development Setup

## Prerequisites

- **Python 3.11+** (3.12/3.13 supported)
- **JDK 17+** (for mod compilation - `test_mod_compile.py`, `test_mod_bridge.py`)
- **Node.js 20+** (for worker tests - `node worker/test-worker.mjs`)
- **Git**

## Initial Setup

```bash
# Clone the repository
git clone https://github.com/Shadow-457/Cubeon.git
cd Cubeon

# Install Python dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Install Java 17+ (if not present)
# Ubuntu: sudo apt install openjdk-17-jdk
# macOS: brew install openjdk@17
# Windows: winget install EclipseAdoptium.Temurin.17.JDK

# Verify mod compilation works
python tools/test_mod_compile.py

# Run the full test suite
python tools/test_mega_smoke.py
```

## Development Environment

### IDE Setup
- **PyCharm/VS Code** with Python extension
- Enable `mypy` / `pyright` for type checking
- Recommended: `ruff` for linting (configured in `pyproject.toml`)

### Running the Launcher

```bash
# Normal run
python main.py

# With debug logging
python tools/debug_run.py

# With specific seasonal theme (for testing)
CUBEON_SEASON=winter python main.py

# Headless UI smoke test (no display needed)
python tools/test_ui_smoke.py
```

### Sandbox for Multi-Launcher Testing

```bash
# Launch a second isolated launcher (fresh HOME → fresh friends account)
python tools/launch_sandbox.py "TestUser"

# List sandboxes
python tools/launch_sandbox.py --list

# Wipe a sandbox
python tools/launch_sandbox.py --wipe "TestUser"
```

## Project Structure

```
Cubeon/
├── main.py                 # UI entry point - builds tabs, boots Flet
├── launcher_core.py        # Facade: import launcher_core as core
├── cubeon/                 # ALL business logic (no UI imports)
├── ui/                     # Flet UI layer - one module per tab
├── ui_new/                 # Preview UI (--new-ui flag)
├── mod/                    # In-game Fabric mod (Gradle)
├── worker/                 # Cloudflare Workers (JS)
├── templates/              # Color-theme palettes
├── assets/                 # Icons, art, jars, fonts, pets
├── packaging/              # Build scripts + PyInstaller specs
├── tools/                  # Tests + dev scripts
├── agents/                 # AI-agent notebook + docs + memory
├── docs/                   # Documentation (this directory)
├── archive/                # Old snapshots & regenerable build output
├── dist/                   # PyInstaller output (gitignored)
└── build/                  # Build artifacts (gitignored)
```

## Key Module Entry Points

| Module | Purpose |
|--------|---------|
| `cubeon/launch.py` | `launch_game()` - Java command construction + game process |
| `cubeon/friends_service.py` | Headless friends owner: roster, chat, P2P, notifications |
| `cubeon/local_api.py` | Localhost HTTP bridge the mod polls |
| `cubeon/friends.py` | Relay client (WebSocket), name rules, identity |
| `cubeon/p2p.py` | P2P worlds: STUN + relay fallback, mod/asset sync |
| `cubeon/mods.py` | Mod management, dependencies, doctor |
| `cubeon/modpacks.py` | Modpack install/version-matching |
| `cubeon/content.py` | Unified content (resource packs, shaders) |
| `cubeon/paths.py` | Every filesystem path + `ensure_disk_space()` |
| `cubeon/config.py` | Config schema, username validation, auth key |

## Useful Commands

```bash
# Run specific test
python tools/test_friends_service.py
python tools/test_ui_smoke.py
python tools/test_mod_compile.py

# Run worker tests
cd worker && node test-worker.mjs

# Build mod jars (needs network + JDK)
python tools/build_mod_jars.py

# Regenerate cape + patch worker
python tools/make_cape.py

# AI driver - explore the app headless
python tools/app_driver.py explore
python tools/app_driver.py fuzz
python tools/app_driver.py tabs

# Update seasonal geography data
python tools/make_seasonal_geo.py

# Generate corner icon
python tools/make_corner_icon.py
```

## Debugging Tips

- **Logs**: `~/.cubeon_launcher/cubeon.log` (rotating, 5MB x3)
- **Config**: `~/.cubeon_launcher/config.json`
- **Window geometry**: `~/.cubeon_launcher/window_geometry.json`
- **Friends identity**: `~/.cubeon_launcher/identity.json`
- **Local API token**: `~/.cubeon_launcher/local_api.json` (mode 0600)

- **Flet inspector**: Press `F12` or click bug button in sidebar (requires `CUBEON_INSPECT=1`)
- **Repaint profiler**: `CUBEON_PERF=1 python main.py` - times every `page.update()` by call site
- **GPU crash recovery**: Set `LIBGL_ALWAYS_SOFTWARE=1` to force software rendering

## Common Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: flet` after sandbox | Set `PYTHONUSERBASE=<real home>/.local` when running sandbox |
| Mod jar not found | Run `python tools/build_mod_jars.py` |
| Tests fail with "no Minecraft version selected" | Ensure `CUBEON_GAME_DIR` is set in test environment |
| Worker tests fail | Ensure Node.js 20+ is installed |
| Gradle build fails | Check JDK version matches bracket requirements (17/21) |