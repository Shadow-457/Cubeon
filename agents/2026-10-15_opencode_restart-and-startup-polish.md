# Smoothing the Seasonal Restart button + launcher open/close (2026-10-15)

## What the user asked
"make sure the restart button on seasonal themes and the opening of the launcher
and closing becomes seamless and smooth as hell".

## What I changed (main.py only, plus tests + the map)

1. **Restart button acknowledges itself.** `_on_restart_click` now shows a
   full-window `restart_overlay` ("Restarting Cubeon…", dimmed background,
   animated opacity) before it closes the window. It refuses a second click
   while `_relaunch["request"]` is already set, and it closes through a named
   async task `_restart_close_after_beat` (0.4 s beat so the cover paints
   first). Any failure un-arms cleanly and restores the note text.

2. **The restart can no longer be mistaken for a minimize.** In
   `_window_gone_finish` the pending-relaunch check now runs BEFORE the
   live-client guard. On Linux/KDE the button's native close can be delivered
   as a HIDE while the flet client is still alive; the old guard returned and
   left a hidden window with no re-exec. This is a real reliability fix, not
   just polish.

3. **The finished UI fades in.** `_app_root` is mounted at `opacity=0` with
   `animate_opacity`; `_reveal_window` sets it to `1.0` right after the window
   is made visible (and the no-event-loop fallback does too, so the UI can
   never stay invisible).

Closing itself has no interceptable event on flet 0.86 (the X button/WM
tears the window down without a Python event, and `prevent_close` is
deliberately never set), so there is nothing to animate on a plain close —
the win there is that the restart path's close now always ends in a re-exec.

## How I verified
- `tools/test_ui_smoke.py`: 199/199. New checks cover the "Restarting…" cover
  appearing on click, the fade-in wiring, and the watchdog's
  relaunch-before-live-client ordering.
- `tools/test_mega_smoke.py --suites`: 42/42 (all repo harnesses, including
  `test_wedge_watchdog.py`'s relaunch ladder).
- `main.py` compiles; no other suite changed behavior.

## Note for the next agent
I did NOT touch the small-splash window resize (360x200 -> saved geometry):
`test_ui_smoke.py` pins it and the geometry comment says not to. If "opening
still isn't smooth" is reported, the resize jump is the next suspect — but
changing it means changing that invariant and the 360x200 splash test.
Also: flet runs `main(page)` synchronously on the event loop, so
`page.run_task` tasks (the splash reveal, the UI reveal) only execute AFTER
main() returns. Worth knowing before trusting any "shown during the build"
comment.
