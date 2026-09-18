# Testing Guide

## Test Suite Overview

Cubeon uses **standalone test scripts** in `tools/` - no pytest, no test framework. Each script prints `N passed, M failed` and exits 0 on pass, non-zero on failure.

## Running Tests

### Mega Smoke (One-Command Gate)

```bash
# Full gate: syntax → imports → contracts → control flow → headless runtime
python tools/test_mega_smoke.py

# Static only (fast, CI-friendly)
python tools/test_mega_smoke.py --static

# Also run sub-suites
python tools/test_mega_smoke.py --suites

# Machine-readable output
python tools/test_mega_smoke.py --json
```

**Mega smoke runs:**
1. Syntax check (`compile` all .py files)
2. Import check (62 modules)
3. Type/contract (launcher_core facade, forbidden Flet APIs, None-in-controls, THEME/signatures, type hints)
4. AST control flow (unreachable code, duplicate defs, bare except)
5. Headless runtime (every nav tab opens, every handler fires, no errors, no None children, second build idempotent)

### Test Suites by Category

#### Friends / Social / Identity

| Command | What it Covers |
|---------|----------------|
| `python tools/test_friends.py` | Friends identity/client logic + format parity with `worker/cubeon-friends.js` |
| `python tools/test_friends_service.py` | Headless friends service + localhost bridge + **contract check reading `mod/Bridge.java`** |

#### UI / Framework

| Command | What it Covers |
|---------|----------------|
| `python tools/test_ui_smoke.py` | Boots Flet UI headless-ish, every tab builds, invariants hold |
| `python tools/test_seasonal.py` | Season tables + precedence + palette AA contrast (98 checks) |
| `python tools/test_launch_indicator.py` | Play tab's launch progress bar: phase ordering, no stalls |

#### Mods / Modpacks / Content

| Command | What it Covers |
|---------|----------------|
| `python tools/test_mod_bridge.py` | Compiles `Json.java`/`Bridge.java` with `-Werror`, 100+ assertions |
| `python tools/test_mod_compile.py` | Compiles ALL mod sources against hand-written Minecraft API stub |
| `python tools/test_mod_matrix.py` | `mod/brackets.json` - no overlapping ranges, correct jar routing |
| `python tools/test_mod_detail.py` | Mod detail dialog + auto-repair (81 checks) |
| `python tools/test_modpacks.py` | Modpack install/version-matching (64 checks) |
| `python tools/test_modpacks_cf_keyless.py` | CurseForge packs without API key (zip→mrpack) |
| `python tools/test_mod_store.py` | Global mod store (27 checks, concurrency + copy-failure) |
| `python tools/test_mod_install_progress.py` | Install progress in FILE UNITS (39 checks) |
| `python tools/test_content_doctor.py` | Unified doctor (88 checks) |
| `python tools/test_content_instance.py` | Per-instance content isolation |
| `python tools/test_csl.py` | CustomSkinLoader ExtraList registration (14 checks) |
| `python tools/test_capes.py` | Cape pipeline (19 checks) |
| `python tools/test_gallery.py` | Local library pipeline (32 checks) |
| `python tools/test_perf_mods.py` | Sodium/Lithium auto-install (17 checks) |

#### P2P / Networking / Servers

| Command | What it Covers |
|---------|----------------|
| `python tools/test_p2p_*.py` | Transport/session/relay/hybrid/batch6/stress |
| `python tools/test_invites.py` | Invite-code format parity launcher ↔ Worker |
| `python tools/test_server_integrity.py` | Server install validation (59 checks) |
| `python tools/test_orphan_server.py` | Server lifecycle cleanup (16 checks) |
| `python tools/test_net.py` | Download retry/resume/cap + updater (21 checks) |
| `python tools/test_local_api_gate.py` | Local API gate handlers (5 checks) |

#### Version / Launch / Config

| Command | What it Covers |
|---------|----------------|
| `python tools/test_client_json.py` | TLauncher-style client.json sanitizing |
| `python tools/test_versions_manifest.py` | Manifest download + caching |
| `python tools/test_version_integrity.py` | Fake mll injection, jar validation |
| `python tools/test_launch_fixes.py` | L1-L3 launch path fixes |
| `python tools/test_milestones.py` | Playtime durable sessions |

#### Fuzzing / Chaos

| Command | What it Covers |
|---------|----------------|
| `python tools/test_fuzz.py` | UI chaos monkey: 100% handler surface, ~26k invocations |
| `python tools/app_driver.py explore` | AI driver: guided usage pass, 822 invocations, 100% coverage |
| `python tools/app_driver.py fuzz` | AI driver: hostile corpus, 100% coverage |
| `python tools/ux_capture.py` | Screenshot/UI capture (outputs to `agents/docs/ux_shots/`) |

## Test Architecture

### Hermetic Tests

All tests are **hermetic** - they sandbox `HOME` via `CUBEON_GAME_DIR` etc. and stub network calls:

```python
# In test scripts:
import _sandbox_home
_sandbox_home.isolate()  # Rewrites HOME to temp dir

# Network stubs in tools/_fuzz_common.py:
install_safe_stubs()  # Patches subprocess.Popen, requests, etc.
```

### FakePage Harness

`tools/_fuzz_common.FakePage` mimics Flet 0.86:
- `page.update()` / `page.run_task()` / dialog stack
- `show_dialog` / `pop_dialog` (0.86 API)
- Control tree walking for assertions

### App Driver

`tools/app_driver.py` boots the **real UI headless** under safe stubs:
- `Driver` class with `tabs()`, `open_tab()`, `click()`, `type_fields()`, `fire_all()`
- `fire_all()` fires: on_click, on_change, on_submit, on_hover, on_focus, on_blur, on_result
- `report()` returns JSON with `handler_coverage` = fired/seen + missed names

## Adding New Tests

1. Create `tools/test_<feature>.py`
2. Follow pattern: standalone script, prints `N passed, M failed`, exits 0/1
3. Use `_sandbox_home.isolate()` for HOME sandboxing
4. Use `install_safe_stubs()` for network/subprocess stubbing
5. Add to `tools/test_mega_smoke.py` `SUITES` list if it should run in mega

## CI Integration

`.github/workflows/build.yml` runs:

```yaml
- name: Run test suite
  run: |
    set -e
    failed=0
    for t in tools/test_*.py; do
      case "$t" in
        tools/test_visual_*.py) echo "skip (manual) $t"; continue;;
      esac
      export CUBEON_GAME_DIR="/tmp/cubeon-game-ci-$RANDOM-$RANDOM"
      rm -rf "$CUBEON_GAME_DIR"
      if ! python3 "$t"; then
        echo "::error::$t failed"
        failed=1
      fi
    done
    exit $failed
```

Each test gets a fresh `CUBEON_GAME_DIR` to avoid cross-test pollution.

## Debugging Test Failures

```bash
# Run single test with verbose output
python -m pytest tools/test_friends_service.py -xvs  # if pytest available
# OR just run the script directly
python tools/test_friends_service.py

# For UI tests: run with visual capture
python tools/fuzz_visual.py --dry  # headless self-check
python tools/fuzz_visual.py --bots 4 --pace 0.5  # windowed
```