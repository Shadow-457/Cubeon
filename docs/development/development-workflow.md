# Development Workflow

## Branching Strategy

- **main** - stable, deployable
- Feature branches - `feature/<description>`
- Bug fixes - `fix/<issue-number>-<description>`
- Release tags - `vN.N.N` (e.g., `v1.2.3`)

## Code Standards

### Python
- Type hints on all public functions
- Docstrings for modules, classes, and public methods
- `ruff` for linting (run `ruff check .`)
- No `except:` bare clauses (use `except Exception:`)
- No mutable default arguments

### Java (mod/)
- Java 17 bytecode target (all brackets)
- `-Xlint:all` clean compile
- Fabric Loom 1.14.10
- One jar per bracket in `mod/brackets.json`

### JavaScript (worker/)
- ES modules (`type: module` in package.json)
- No external deps for tests (stub KV)
- Cloudflare Workers compatible

## Testing Before Commit

```bash
# 1. Syntax + imports + contracts + control flow + headless runtime
python tools/test_mega_smoke.py

# 2. Static checks only (fast)
python tools/test_mega_smoke.py --static

# 3. Specific area tests
python tools/test_friends_service.py    # Friends + bridge
python tools/test_ui_smoke.py           # UI tabs
python tools/test_mod_compile.py        # Mod compilation
python tools/test_mod_matrix.py         # Bracket routing

# 4. Worker tests
cd worker && node test-worker.mjs
```

## Pull Request Checklist

- [ ] All tests pass (`test_mega_smoke.py`)
- [ ] No new bare `except:` clauses
- [ ] No mutable default arguments
- [ ] Type hints on new public functions
- [ ] Docstrings updated for changed behavior
- [ ] Worker protocol parity maintained (if touching friends/invites/skins)
- [ ] `mod/brackets.json` updated if Minecraft version support changed
- [ ] CHANGELOG updated (if user-facing change)

## Code Review Focus Areas

1. **Security**: No secrets in code, no SQL injection, no path traversal
2. **Atomic writes**: All JSON state via `atomicio.write_json()` or `os.replace()`
3. **Thread safety**: `_chat_lock`, `_metadata_lock`, `_sync_lock`, `_state_lock` usage
4. **Error handling**: Human-readable messages, no raw exceptions in UI
5. **Test coverage**: New code has regression tests

## Release Process

See `docs/release/build.md` and `docs/release/release-checklist.md`.

## Debugging Workflow

1. **Reproduce** with `tools/app_driver.py script <steps.json>`
2. **Isolate** with `tools/test_fuzz.py` (hostile corpus)
3. **Visual debug** with `tools/fuzz_visual.py --bots 4`
4. **Logs**: `tail -f ~/.cubeon_launcher/cubeon.log`
5. **Inspector**: `CUBEON_INSPECT=1 python main.py` → F12