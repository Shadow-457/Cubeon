[Documentation](../docs/README.md) / Development tools

# Development tools

Run commands from the repository root, using the project's Python
environment. Test scripts, interactive helpers, and build tools have
different prerequisites; not everything in this directory is offline.

## Tests

```bash
python tools/test_mega_smoke.py
python tools/test_mega_smoke.py --suites
```

The first command runs the main smoke gate. The second also runs the
registered regression suites. Use `--static` to omit the runtime pass.

Run an individual check directly, for example:

```bash
python tools/test_ui_smoke.py
python tools/test_mod_ui_stability.py
python tools/test_chat_avatar_stability.py
node worker/test-worker.mjs
```

See [Testing](../docs/development/testing.md) for test selection, isolation,
Java prerequisites, and the distinction between headless and visual checks.

## Launcher debugging

| Tool | Use |
| --- | --- |
| `debug_run.py` | Start the launcher with diagnostic output |
| `app_driver.py` | Exercise the UI with headless fixtures; `explore` runs a usage pass |
| `launch_sandbox.py` | Start a separate launcher environment for multi-user checks |
| `fuzz_visual.py` | Interactive visual exercise; requires a desktop |
| `ux_capture.py` | Capture UI images; requires the tool's display setup |

Examples:

```bash
python tools/debug_run.py
python tools/app_driver.py explore
python tools/launch_sandbox.py TestUser
```

Sandbox identities and captured logs can contain private information.
Review them before sharing.

## Build and release tools

- `build_mod_jars.py` assembles the brackets in `mod/brackets.json`. It needs
  Gradle, a suitable JDK, and network access for uncached dependencies.
- `release_version.py next` previews the next release version.
- `release_version.py stamp <version>` changes the version in the source and,
  for a stable release, the website. It is not a read-only check.

Platform packaging scripts live in `packaging/`. Follow the
[build guide](../docs/release/build.md) instead of copying a generic
PyInstaller command that may omit the desktop client or bundled assets.
