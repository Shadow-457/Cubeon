# Windows: "Cubeon.exe is in Task Manager but no window ever appears"

**Reported by the user (2026-10-16)**: after installing the Windows build and
launching it, nothing appears - Task Manager shows `Cubeon` under *Background
processes* (47.6 MB, 0% CPU) next to a `Flet description` process (156.6 MB,
41.7% CPU). The screenshot is dated 23:35 local on 2026-10-15, i.e. **after**
the CI run for `24a955d` ("Windows: fix the launcher running with no window at
all", 22:36 +0500) had already refreshed the release assets (17:40Z).

So the previous fix - `_show_window()` writing `visible = False` then `True` -
was in the build the user ran, and it was not enough. Why:

- `page.window.visible = True` is a **property patch**. The desktop client
  (`packages/flet/lib/src/services/window.dart`) calls `showWindow()` only when
  the value differs from **its own cached native visibility**. A client that
  already holds `_visible == true` therefore applies `visible: true`, sees no
  change and shows nothing. (The previous fix only guarantees the patch is
  *sent*; it cannot make the client act on it.)
- `page.window.to_front()` is a **method call**, and its client implementation
  (`utils/desktop.dart::windowToFront`) calls `windowManager.show()` with **no
  `isVisible()` guard** - the one reveal flet cannot skip.
- If the client processes nothing at all (wedged UI thread - plausible with a
  41.7% CPU client on a VM), no message-based reveal can help. Only the OS can:
  `ShowWindow()` on the client's own top-level window.

## Fix

Three reveals per reveal path, none of them droppable (`main.py`):

1. `_show_window()` - unchanged (`visible = False` then `True`; a bare `True` is
   dropped by flet's `Prop.__set__` before it is sent).
2. `_reveal_to_front()` - `await asyncio.wait_for(page.window.to_front(), 5)`,
   scheduled with `page.run_task` so it is ordered but never awaited inline.
3. `_backstop_window_visible()` - Windows only, on a daemon thread:
   `cubeon/winwindow.py::ensure_client_window_visible()`, new module. It finds
   OUR flet client's top-level window (psutil; two-factor: name contains
   "flet" AND (our direct child OR our assets dir in its cmdline) - same rule
   `_kill_flet_client` uses, so a second instance's window and Minecraft's java
   are both untouched), filters engine tool-windows and sub-40px shims, calls
   `ShowWindow()` (SW_RESTORE if minimized), and **logs the outcome** at
   INFO/WARNING into cubeon.log. It polls up to 10s, hence the thread - it may
   never run on flet's event loop. Off Windows it is an immediate no-op.

`_window_backstop` (one `armed` flag per window session) makes both reveals
share a single backstop thread per session.

## Verified

- `tools/test_winwindow.py` (NEW, 28 checks, 0 failed): the policy loop against
  an injected user32 stand-in - already-visible window is left alone and
  returns without waiting; a hidden one is ShowWindow'd and re-checked; a
  window that stays hidden times out with the "exists but stays hidden" WARNING;
  no window at all logs the difference; a client that starts a beat later is
  still found; `ShowWindow`/`pids_of` raising degrades to `False`; the process
  filters, the 64-bit argtypes and the SW_RESTORE choice are pinned.
- `tools/test_ui_smoke.py`: **214 passed, 0 failed** (was 208) - new checks pin
  `to_front` + the nudge + the backstop in BOTH reveals, and record a real
  call sequence `visible=False -> visible=True -> window.update -> to_front`;
  the backstop is inert off Windows and arms exactly one thread on win32.
  `_ui_functions` now also matches `AsyncFunctionDef` (it only found sync defs
  before, so an async helper looked like it did not exist).
- `tools/test_mega_smoke.py --suites`: **43 passed, 0 failed** (static +
  imports + contracts + control flow + runtime UI boot + every suite,
  including the new `test_winwindow.py`, which is registered in `SUITES`).
- **NOT verified**: that user32 `ShowWindow` really un-hides the window on real
  Windows. This box is Linux, and Wine never honoured the hidden start, so the
  bug has never been reproducible here - which is exactly why the module logs
  its outcome now. The user needs a freshly built installer (CI rebuilds on a
  push to main) and, if it still fails, the tail of `cubeon.log`.
