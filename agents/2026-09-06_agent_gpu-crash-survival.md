# GPU-crash survival + exit-hang fix (the "it keeps crashing" session)

## What the user hit
"it keeps crashing and it doesn't show in tray when it runs sometimes"

Two causes, both now handled:

1. **The crash is a Mesa driver bug, not our code.** The flet client
   SIGSEGVs inside `libgallium-26.1.6` during first-frame render. Same
   stack every time: `gtk_container_propagate_draw -> libflutter_linux_gtk
   -> libgallium`. Happens on AMD Polaris (RX 580) + Mesa 26.1 on Arch.
   It is FLAKY (~50% of launches) and happens on BOTH hardware GL and
   llvmpipe (`LIBGL_ALWAYS_SOFTWARE=1` — llvmpipe lives in the same
   broken .so). Predates today's work (Sep 1 coredump exists).

2. **Tray missing sometimes** = launcher died to #1 before `main()`
   finished (tray starts at the END of main).

## The fix (main.py `__main__` block)
- **Retry loop** around `ft.run` (max 2 retries). `ui_painted_ok` marker
  (written by `_reveal_window`) distinguishes "user closed a working
  window" (stop, clean up flags) from "client died pre-paint" (arm
  `use_software_gl`, relaunch). Because llvmpipe crashes are flaky, a
  second try usually gets through.
- **Session-end cleanup runs after `ft.run` returns**, watchdogged at 3s.
  This is the ONLY reliable end-of-session signal: Flet 0.86 delivers no
  window events to Python on real X-close. `_on_window_event`'s close
  branch was dead code for the X button — that's why Discord presence
  lingered after quit. Cleanup is registered via module-level
  `_session_end` dict (must be module-level: the test harness imports
  `main` as a module).
- **`os._exit(0)` after the loop**: pystray/GLib/pango native threads can
  wedge interpreter shutdown (observed: main thread futex_wait hang,
  process immortal after window close). Cleanup has already run by then.

## Hard-won don'ts (each cost 20+ min today)
- **`window.prevent_close` = unclosable window** on Flet 0.86/Linux. The
  client swallows the X click, no event reaches Python. Verified on live
  KDE/X11. Never set it.
- **`window.center()` in the reveal task** = same gallium crash vector
  (GTK resize mid-first-frame). First-run centering is now computed from
  `xrandr` numbers and set as plain left/top BEFORE any paint.
- **`page.on_window_event` doesn't exist** in 0.86 — assigning it silently
  does nothing. It's `page.window.on_event` (enum `e.type`, string it
  with `.split(".")[-1]`).
- **pid-file scraping for the client**: flet writes `/tmp/<random20>` with
  NO .pid extension; don't glob `*.pid`. (We dropped process-watching
  entirely — `ft.run` returning IS the death signal.)
- **pystray menu events via dbusmenu `Event`** don't reliably reach the
  MenuItem callback on the appindicator backend — can't use dbus to
  simulate tray Quit in tests.
- **`setsid nohup ... & disown` in a bash tool call**: the tool's 120s
  timeout KILLS the whole process group on some paths, leaving zombie
  flet clients that break later window-matching tests. Check for orphans
  before blaming the app.

## System-level note for the user's machine
The REAL fix is updating/downgrading Mesa (or waiting for a fixed
libgallium). Our retry loop makes the launcher usable despite the driver,
but each crashed attempt still writes a coredump. If crashes persist
beyond first paint (attempt 1 dies mid-session), we'll need the
`--no-enable-impeller` engine switch, which requires argv injection into
the flet client — not possible via env vars, would need a wrapper script.

## Verification trail
- smoke 41/41 after every change
- live: client SIGSEGV → auto-retry with software GL → UI painted →
  window stayed up; X-close → process exits, `use_software_gl` +
  `ui_painted_ok` markers reset, no orphan flet clients, tray icon gone
