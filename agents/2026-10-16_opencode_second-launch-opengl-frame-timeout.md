# "its just crashinggggg" — a window the flet client can never render

**Reported by the user (2026-10-16)**, twice:

```
[fuckarch@archlinux Cubeon]$ python main.py
** (flet:55672): WARNING **: Timed out waiting for OpenGL frame of size 1060x760 (have 360x200)
[fuckarch@archlinux Cubeon]$ its just crashinggggg
```

…then they narrowed it down themselves: *"when i size it too much it doesnt
open on second launch, it needs to be a specific size to launch otherwise it
gives errors and stuff."*

## What was actually happening

Two independent ways to ask the flet desktop client for a window size it can
never produce. Either one makes the client log

```
Timed out waiting for OpenGL frame of size WxH (have W'xH')
```

after a ~5 s wait and then die **before the finished UI paints**: the window
flashes and closes (or never shows), `ui_painted_ok` is never written, and the
exit watcher sees a clean client exit — so the launcher just quits.

Measured here (KDE/X11, 1920x1200), 8–10 launches per arm:

| build | early exit / crash |
|---|---|
| `2dd1ce5` (before) | **2 / 8** |
| with this fix | **0 / 10** |

### 1. Resizing a VISIBLE window

`main()` used to reveal the splash at 360x200 and call
`_apply_real_geometry()` (the saved 1360x808) later in `_reveal_window` — i.e.
on the already-visible splash. A visible resize is the trigger; pre-Phase-1
code did the same resize while the window was still hidden and never warned.

**Fix:** `_apply_real_geometry()` now runs *before* `await _reveal_splash()`,
on the still-hidden window, and `cfg = core.load_config()` moved up with it
(a plain ~1 ms disk read). The splash is no longer a small window that grows;
it is a card in the window the app keeps. The old "small splash" design cannot
be kept without a visible resize, so it had to go.

### 2. A saved size bigger than the WORK AREA

The second half is the "size it too much" half. KDE reserves 48 px on this
1920 screen, so `_NET_WORKAREA = 1872x1200`, and a WM clamps every window to
its **work area** — while `_screen_size()` only read `xrandr` (the full
screen). Saving a window dragged near-fullscreen therefore asked for

```
Timed out waiting for OpenGL frame of size 1900x1170 (have 1872x1170)
```

and the 1872-wide window could never satisfy the 1900 request. Because the
saved geometry is only restored on the NEXT start, this is exactly a *second
launch* failure.

**Fix:** new `_work_area()` (`xprop -root -notype _NET_WORKAREA`;
`SystemParametersInfoW(SPI_GETWORKAREA)` = 0x0030 on Windows) plus a new
module-level, pure `fit_geometry_to_area()` that clamps the saved width/height
to it and pulls a saved position back inside. `min_width`/`min_height` are
also capped at the size actually requested, so the WM cannot be forced to a
bigger frame than we asked for. The clamped size is saved back, so a wedged
install self-heals on the next start (verified: the sandbox's 1900x1170 became
1872x1170).

## Also verified

- Works for the saved geometries that matter: the user's real 1360x808, a
  small 1000x700, `maximized: true`, and the clamped 1872x1170 — all stayed
  alive with no OpenGL warning. One run in ten still logs
  `... of size WxH (have 1x1)` (a client that has not created its surface
  yet); it is harmless now and the app keeps running.
- Startup profiler (sandbox): `main() entered 638 ms → config loaded 766 ms →
  splash revealed 939 ms → UI built 1242 ms → finished UI revealed 1476 ms`.
- `tools/test_startup.py`: **25 passed, 0 failed** (was 17) — section 5 is new
  and unit-tests `fit_geometry_to_area()` with synthetic work areas, so it runs
  on Windows/Linux CI with no X server.
- `tools/test_ui_smoke.py`: **223 passed, 0 failed** — the pinned invariant
  flipped from "geometry lands on the finished UI" to "geometry lands on the
  hidden window, before any reveal".
- `tools/test_mega_smoke.py`: **20 passed, 0 failed**.

## Note for the next agent

The `agents/docs/module-map.md` line that said *"Do NOT move the geometry
assignment back before the splash"* was exactly backwards and is now rewritten.
If a future change wants a small splash window that grows, that change is a
regression: it reintroduces the visible resize.
