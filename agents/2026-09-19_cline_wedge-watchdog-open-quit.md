# 2026-09-19 — wedged flet client: why "Restart" closed Cubeon and never reopened it

## The report

"When i click restart cubeon on seasonal update area in settings cubeon does
closes but never opens and i am not able to open cubeon with the background
process." Plus frozen client windows that outlived the launcher.

## What it actually was

Not one bug — a chain, all traced live on this machine (Mesa 26.1 / AMD
Polaris):

1. The flet desktop client can **WEDGE**, not just crash: window mapped, not one
   OpenGL frame, ~180% CPU, **`ft.run` never returns**.
2. Everything that recovers a session lives AFTER `ft.run` returns — the session
   classification, the software-GL retry ladder, tray Open/Quit handling and the
   Settings "Restart to apply" request. A wedge disables all of them at once.
3. So: restart re-execs into the same wedge → "closes but never opens"; the tray
   icon's Open/Quit events are dead letters; the client keeps its frozen window.
4. On retry exhaustion `main.py` prints "giving up" and `return`s — exiting the
   process and taking the tray with it, which is the "can't open it from the
   background process" half.

## The trap I fell into (worth remembering)

The wedge watchdog I wrote in the previous pass **could never fire**:

- It demanded **≥3** GL-frame-timeout lines with the newest ≤**8 s** old. The
  measured signature of a real wedge is a **burst of exactly TWO** lines ~0.15 s
  apart, then silence forever. (rt2.log ghost 29728: 2 lines, then alive for
  34+ minutes.)
- Worse, the test that "verified" it was **vacuous**: the fake client logged to
  **stdout** while `_filtered_open_flet_view_async` piped only **stderr**. A
  gc-level probe of the live `_wedge_state` dict showed `armed` set and
  `timeouts` stuck at **0** forever — the kill path never ran, and a green test
  said otherwise.

Two lessons, both now in `agents/docs/module-map.md`:
**never re-filter a single fd for evidence a child can log to either**, and
**a test whose fake doesn't reproduce the measured stream/cadence proves
nothing**.

## What I changed

- `main.py`: watchdog trigger retuned to the measurement (`_WEDGE_TIMEOUTS = 2`,
  `_WEDGE_RECENT = 25.0`); capture merges the client's stdout+stderr into one
  pipe and forwards filtered lines to stderr with an explicit flush.
- `main.py`: orphan sweep in `_kill_flet_client()` (kills `flet` clients whose
  launcher is gone; two-factor so a second live instance is safe).
- `cubeon/launch.py`: `CUBEON_GPU_RESTARTS` stripped from the game's env.
- `tools/test_wedge_watchdog.py` (NEW, in mega_smoke's SUITES): deterministic
  fake with the measured signature (stderr, burst of two, then alive+silent so
  any progress proves a kill); asserts kill → retry 1 → retry 2 → giving up →
  no leftover process → capture still stream-agnostic.

## How I verified it

- Deterministic: watchdog fired at client age **12.2 s / 12.0 s / 12.0 s**, ladder
  ran `attempt 1` → `attempt 2` → `giving up`, **0 clients left behind**.
- Live with the REAL client (this machine reproduces the failure): clients were
  killed/crashed as expected, the watchdog produced **no false-positive kills**,
  and the runs left **no ghost client**.
- Suites: `test_wedge_watchdog` 9/9, ui_smoke 148/148, launch_fixes 58/58,
  mega_smoke 16/16, seasonal 106/106.

## Open question for the next agent

On retry exhaustion the launcher still **exits** (tray icon gone). Parking in
the tray instead (only when a live icon exists) would keep Open/Quit usable even
with a persistently broken driver — deliberately NOT done here because it is a
behavior change and wasn't confirmed. If the user still reports "can't reopen
it" under a permanently broken GPU stack, that is the next move.

Also still open (unchanged, see module-map): the relay transport
(`RelaySession`) has the same immediate-stop shape the FIN fix addressed in the
direct path.
