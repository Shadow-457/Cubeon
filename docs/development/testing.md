[Documentation](../README.md) / Development

# Testing

Most checks are standalone scripts in `tools/`. Run them with the Python
environment from [Development setup](setup.md), from the repository root.
They report failures and return a nonzero exit status; pytest is not required.

## Smoke gate

```bash
python tools/test_mega_smoke.py
```

The default gate compiles Python source, checks imports and contracts,
examines control flow, and exercises the UI with headless fixtures.
It does **not** run every regression script.

| Command | Scope |
| --- | --- |
| `python tools/test_mega_smoke.py --static` | Source, imports, and contract checks without the runtime pass |
| `python tools/test_mega_smoke.py --suites` | Gate plus its registered regression suites |
| `python tools/test_mega_smoke.py --json` | Default gate with a JSON report |

The registered suite list is `SUITES` in `tools/test_mega_smoke.py`.
Additional test scripts exist outside that list.

## Focused checks

Start with the area your change affects. These are examples, not a complete
catalog; the scripts in `tools/` are the current inventory.

| Area | Scripts |
| --- | --- |
| UI construction | `test_ui_smoke.py`, `test_version_ui.py` |
| Navigation and input | `test_tab_navigation.py`, `test_keyboard_shortcuts.py` |
| Motion and scrolling | `test_motion.py`, `test_scrolling.py` |
| Artwork and avatars | `test_mod_ui_stability.py`, `test_chat_avatar_stability.py`, `test_faces.py` |
| Cosmetics | `test_appearance_preview.py`, `test_capes.py`, `test_skins_net.py` |
| Mods and packs | `test_modpacks.py`, `test_mod_store.py`, `test_loader_content_rules.py` |
| Content isolation | `test_content_instance.py`, `test_instances.py` |
| Friends and chat | `test_friends.py`, `test_friends_service.py`, `test_chat_optimistic.py` |
| Local bridge and mod | `test_mod_bridge.py`, `test_mod_compile.py`, `test_mod_matrix.py` |
| Launch and downloads | `test_version_integrity.py`, `test_launch_fixes.py`, `test_net.py` |
| Release tooling | `test_release_version.py`, `test_release_pipeline.py` |

For example:

```bash
python tools/test_chat_avatar_stability.py
python tools/test_chat_optimistic.py
```

Worker route and storage tests use Node.js and stubbed services:

```bash
node worker/test-worker.mjs
```

Java compile checks need a JDK with `javac`. Stub compilation is not a
replacement for building the mod jars or testing them in Minecraft.

## Isolation

Tests that write launcher state should call `_sandbox_home.isolate()` before
importing modules that resolve paths. Use the existing fixtures to stub
network requests and child processes. `CUBEON_GAME_DIR` isolates game files,
not every file under the launcher's home directory.

Not every tool is headless or offline. Visual tests and
`test_wedge_watchdog.py` can start real desktop clients. Jar assembly and
deployment tools may need network access. Check a script's prerequisites
before running it in automation.

## Adding a regression test

- Add `tools/test_<feature>.py`, following the adjacent standalone scripts.
- Make failures produce a nonzero exit status.
- Use temporary directories and deterministic service fixtures.
- Add the script to `SUITES` if it belongs in the extended smoke gate.

For a UI stability fix, assert control identity or emitted updates as well
as displayed values. Equal text does not prove that an image stayed mounted.

## CI and manual checks

The Python test loop, exclusions, and platform jobs are defined in
[`.github/workflows/build.yml`](../../.github/workflows/build.yml).
CI is not identical to the default smoke gate.

Report exact commands, failures, and skips. A passing headless run does not
establish desktop frame rate, window visibility, or platform packaging.
Use [Windows smoke testing](../WINDOWS_SMOKE_TEST.md) and the
[release checklist](../release/release-checklist.md) for those checks.
