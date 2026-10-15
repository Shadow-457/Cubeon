# Phantom "QUIT GAME" on an empty launcher (2026-10-15)

## What the user asked
"Why the heck it shows quit game when there's isn't even a game" — and then the
repro: "when i changed my modloader it just suddenly showed quit game even if i
wasnt running game neither installed".

## Root cause — a `None == None` comparison
`on_version_selected()` (main.py) does `version_id = version_dropdown.value`.
With nothing installed the dropdown value is `None`, so `version_id` is `None`.
Near the end it had:

```python
if state.get("running_version") == version_id:
    set_button_mode("running")      # paints the red QUIT GAME
```

`state["running_version"]` is `None` whenever no game is live — so the bare
comparison matched `None == None` and the button painted **QUIT GAME on a
completely empty launcher**. The reason it appeared "when I changed the mod
loader" is that `on_loader_toggle_change()` calls `on_version_selected()`
(unconditionally, four call sites), so the change re-ran the buggy path.

This is NOT the watchdog or an on_exit miss — no game had ever been launched;
the claim was never set. Purely a comparison bug.

## Fix (main.py, `on_version_selected`)
1. Guard the running check: `if version_id and state.get("running_version") == version_id:`.
2. The `else` (not-installed) branch also had `set_button_mode("download")` +
   `prefetch_version(version_id)` unguarded, so an empty launcher would have
   flipped to a cyan "DOWNLOAD & PLAY" of *nothing*. It now only paints
   `download`/prefetches when `version_id` is truthy, and otherwise keeps the
   neutral PLAY that the empty startup state mounts (`on_play_click` is already
   a no-op with no selection).

Regression pinned in `tools/test_ui_smoke.py` (source-level: the comparison must
carry the `version_id and` guard and must not appear bare).

## How I verified
- `tools/test_ui_smoke.py`: 207/207.
- `tools/test_mega_smoke.py --suites`: 42/42.
- `main.py` compiles.

## The "strange black border" — VM window decorations, NOT the app
The user's other screenshot (a VirtualBox VM) showed a black border/title bar
around the window. Confirmed cause: that chrome is the **VM's window-manager
decoration**, not Cubeon. The app never draws a title bar or window frame — it
only sets `page.title = "Cubeon"` (main.py:586) and `page.padding = 0`, then
fills the window. That's why the repo's own `ux_shots` (dev machine) show no
such border. The user chose to **leave the OS decorations as-is** (fix it in the
VM, not the app), so no code change was made. If it ever needs removing, the
only app-side route is `title_bar_hidden` + a custom draggable header with our
own close/min/max — a large, cross-platform-risky change; not done.

## Note for the next agent
If a "QUIT GAME with no game" report reappears, check EVERY comparison against
`state["running_version"]`/`version_dropdown.value` for the same `None == None`
trap — `on_version_selected` was the only unguarded one left (the others already
sit after a `if not version_id: return`).
