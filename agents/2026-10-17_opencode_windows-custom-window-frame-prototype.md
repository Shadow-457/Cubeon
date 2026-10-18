# Windows custom window frame — a flagged prototype

- **Agent:** opencode (DeepSeek V4.1 Flash)
- **Date:** 2026-10-17
- **Task:** The user's VM screenshot showed Windows stacking its own title bar
  above Cubeon's branded top bar ("should we make our own decoration?").

## What I did

Built the custom frame the user picked, **behind a flag and Windows-only** — not a
rewrite of the native path:

- `cubeon/winchrome.py` (new, Flet-free): the policy. `custom_chrome_enabled()`
  (Windows AND the flag; env `CUBEON_CUSTOM_CHROME` overrides the config key
  `custom_window_chrome` **in both directions**), the 8 resize hot-zones, and
  `maximize_state()` (event → maximized; deliberately does **not** map flet's
  RESTORE, which means "came back from minimized").
- `ui/window_chrome.py` (new): the widgets — min/max/close on the Cubeon palette
  (close washes DANGER with ON_DANGER), `set_maximized_glyph`, and the hot-zones
  wired to `Window.start_resizing`.
- `main.py`: `frameless = True` on the **hidden** window before
  `_apply_real_geometry()`; the top bar wrapped in `ft.WindowDragArea` (move +
  double-click maximize); a `ft.Stack` over the shell carrying the hot-zones; the
  buttons mounted at the right of the existing top bar; maximize/unmaximize window
  events drive the glyph; a Windows-only Settings toggle ("Custom window frame").
- `cubeon/config.py`: the key, default **False**.

The part worth remembering: `Prop.__set__` drops a write equal to the stored
value, and the patch pass sends ONE `replace` per dirty field with its **current**
value — so `window.minimized = True` a second time sends *nothing* (dead button),
while writing the opposite first costs nothing on the wire. `_force_window_bool`
does exactly that, with the full explanation in its docstring.

## How I verified

- `python3 tools/test_winchrome.py` — 31/31 (policy, hot-zone geometry, event
  mapping). Registered in `test_mega_smoke.py` SUITES.
- `python3 tools/test_ui_smoke.py` — 246/246; new section 13b pins source order
  (frameless before the geometry pass, the fallback back to the native frame) and
  **builds the widgets for real**, which is the only way this branch is exercised
  off Windows.
- `python3 tools/test_mega_smoke.py --suites` — 46/46, including a new layer-5
  check that stubs the policy to True and builds the whole frameless UI headless
  (WindowDragArea + 8 hot-zones + the 3 buttons present, window really frameless).
- Read the flet 0.86.5 Dart/Python sources rather than guessing: `window.dart`
  (minimize/maximize/restore guards, `frameless → setAsFrameless`), `stack.dart`
  (`expand` is ignored in a Stack unless the parent opts in — so the wrapper is
  safe), `gesture_detector.dart` (an empty detector with a pan handler still
  builds and hit-tests), and `window_manager_plugin.dll` (the shipped Windows
  client has `startResizing`/`startDragging`/`setAsFrameless` + DWM frame
  extension).

## Notes for the next agent

- **Not verified from here:** whether `setAsFrameless` keeps a native resize
  border on real Windows (that is why the hot-zones exist), and whether the
  hidden-start reveal still works under a frameless window. Both need the VM.
- Ask the user to test with the Settings toggle (or `CUBEON_CUSTOM_CHROME=1`, which
  needs no config edit) and check: drag, double-click maximize, all 8 resize
  edges/corners, Snap Layouts on the maximize-button hover, and Alt+F4.
- Rollback is one setting; `frameless = False` is sent as a real change, so the
  fallback path (and the "our buttons failed to build" path) restores the OS frame.
- **Two pre-existing timing flakes, NOT from this work** (seen while running the
  suites repeatedly under load, and reproduced on an untouched `HEAD` worktree):
  `test_fuzz.py` sometimes reports `never reached: ['launch_game']` (the directed
  Play scenario races a stubbed install that decides whether the button reads
  PLAY or DOWNLOAD), and `test_install_cancel.py` sometimes fails its
  "aborts within ~1s" assertion (`dt=2.28s` under load). Each passes on a retry.
- `main.py` calls the policy through the MODULE (`winchrome.custom_chrome_enabled`),
  which is what lets `test_mega_smoke.py` stub it to True and exercise the whole
  Windows branch on Linux. Keep that call shape if you refactor.

## Question for the next agent

Design decision left open on purpose: should the **Linux** build get the same
frame? The repo's Linux window path is the fragile one (OpenGL-frame timeouts,
the hidden-start reveal), and a GTK frameless window has no `start_resizing`
equivalent to lean on — I would measure the failure modes on a real Linux desktop
before touching it.
