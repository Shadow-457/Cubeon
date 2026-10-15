# Windows build ran with NO window - Flet silently drops `visible = True`

**Reported (2026-10-15)**: after the Actions run published the binaries, the
Windows build was downloaded to a real Windows VM. Launching it put
`Cubeon.exe` in Task Manager, but no window ever appeared - anywhere. The
process stayed alive instead of exiting.

## Cause

The window is started hidden on purpose (`ft.run(..., view=FLET_APP_HIDDEN)`)
so the splash -> app handoff can be one clean transition instead of a
default-size flash. The reveal did the documented thing:

```python
page.window.visible = True
```

That is a **no-op**. Flet declares `Window.visible` with a default of `True`,
and `Prop.__set__` drops any write equal to the declared default: no value
stored, no dirty flag, nothing sent to the client. So the client - created
hidden - was never told to show its window, and the process just sat there.

Proven at the object level with the repo's own venv:

```
w = ft.Window(); w.visible        # True (declared default)
w.visible = True                  # _values {} _dirty []           <- nothing sent
w.visible = False; w.visible = True   # _values {} _dirty ['visible']  <- sent
```

Tracing the patch builder confirms the second case emits `visible: true`
(`object_patch.py`: a dirty prop with no `_values` entry falls back to the
declared default).

**Why it was never caught**: the hidden start is not honoured everywhere.
Linux/GTK - the dev box - and Wine (how the Windows packages were smoke-tested
here) map the window anyway, so a user always saw it. The real Windows Flutter
client honours `FLET_APP_HIDDEN`, so the window was created and then never
shown. Simultaneously confirmed the CI Windows bundle itself was fine: the
run log shows `+ bundled flet client (38 MB)`.

## Fix (`main.py`)

New `_show_window()` helper, called from `_reveal_splash`, `_reveal_window`
and both headless fallbacks:

```python
page.window.visible = False
page.window.visible = True      # now a REAL change -> patch carries visible: true
page.window.update()
```

Writing `False` first stores a real state, so the `True` is a genuine change.
Where the window is already visible (Linux/Wine) the patch is a no-op, so no
flicker is introduced - deliberately no platform guard. The pair is
load-bearing; a comment and a test say so.

Also bounded the `wait_until_ready_to_show()` handshake with a 5 s
`asyncio.wait_for` in both reveals: a client that never answers must not be
able to keep a hidden window hidden forever.

## Verified

- `tools/test_ui_smoke.py`: **208 passed, 0 failed** (new check "the window is
  shown with a REAL visible change, not a no-op True" asserts the False->True
  order inside `_show_window()` and that `_reveal_window()` calls it).
- `tools/test_mega_smoke.py --suites`: syntax/imports/contracts/control-flow
  layers green; `test_mod_store.py` flaked at 3 in the parallel run and passed
  27/27 standalone (pre-existing flake, unrelated - launcher window only).
- Object-level flet check above; `main.py` AST-parses.

**Still needs**: a CI rebuild so the fixed Windows EXE reaches the user; the
user must confirm on the real VM.

## Note for the next agent

The KeyHUD -> Cubeon Client merge is **paused mid-flight** in the working tree
(overlay dirs untracked, `mod/src/main/java/**` CubeonClient/TabListTag/
WorldPlayers/PlayerTabOverlayMixin deleted, `fabric.mod.json` merged,
`mod/brackets.json` still the old 2-bracket version). **Nothing of the merge is
committed**; this session only committed the launcher fix below.
