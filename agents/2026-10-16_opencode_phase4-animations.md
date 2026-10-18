# Phase 4: the launcher moves (tab bar, Settings rail, the Account sheet)

**Asked for (2026-10-16)**: *"what abt animaitons add those first"* — animate the
top tab switcher (the bar, the green bar under it, the icon), the Settings
sidebar, and open the profile sidebar "like a stretched sheet of paper"; also
show the current skin and cape in Profile.

## What moves now

| Thing | Before | After |
|---|---|---|
| Top tab switch | instant cut (`duration=0`) | 170ms content fade |
| Active tab underline | green/transparent swap | **width** grows 0→24 (the bar visibly grows out from under the icon) |
| Active tab icon | colour swap | colour + a 0.92→1.0 lift (`animate_scale`) |
| Settings section swap | pane `visible` toggled between frames | pane fades in and slides a hair from the left |
| Settings rail row | rebuilt on every click (7 fresh trees) | built once, mutated in place — so the tint can actually fade |
| Account panel | slide in from the right | slide **+ paper unfurl**: `scale_y` 0.04→1 anchored top-right, rounded free edge, one soft shadow |

Everything shares a named curve constant next to the code (`NAV_ANIM`,
`TAB_FADE_MS`, `RAIL_ANIM`, `PANE_ANIM`) so the three parts of each gesture
can't drift apart.

## The one real gotcha (worth remembering)

**A Flet property written in the same frame animates from the value the client
already holds.** So "dip, then settle" animations need two updates: refresh the
dipped value, then write the target ~20–30ms later on a `threading.Timer` —
which means going through `thread_safe_ui`, since the timer fires on its own
thread. Both new animations (`_open_account_panel`'s unroll, `_select_section`'s
fade) work this way, and both guard against the reverse action landing inside
that gap (close-while-opening, second click while settling).

Related: **an animation needs a control the client already knows about.**
`_rebuild_rail` used to clear and re-append every rail row per click, so the
tint could only ever render already-active. It now builds once and mutates.

## Wearing (skin + cape in the Account panel)

`refresh_wearing()` runs when the panel opens: captions and the
no-custom fallbacks are set synchronously, and the two PNG composites go out to
a daemon thread (`ux-wearing-preview`) and come back as base64 `src`. That
base64 step is not optional — `ft.Image.src` resolves a relative string against
`assets_dir` and can't load a path under `~/.cubeon_launcher` (the same trap
`ui/skin_tab.py` documents).

## Verified

- `tools/test_ui_smoke.py`: **223 passed, 0 failed** (it builds the real UI
  headless and clicks through every tab, so the new animation code paths run).
- `tools/test_mega_smoke.py`: **20 passed, 0 failed** — including the runtime
  section that opens every nav tab and asserts no handler raised, and the
  control-flow checks (no duplicate defs, no mutable defaults).
- Kept the pins that matter: `_open_account_panel` / `_close_account_panel`
  still repaint ONLY their two overlays via `thread_safe_ui.refresh` — no
  `page.update()` (ui_smoke §10 pins that), and `switch_tab`'s tail is still a
  scoped diff.

## NOT verified / still open

- **No human has watched these animations.** This box builds the UI headless; a
  FakePage cannot show that the paper unfurl *looks* right, only that it runs.
  Worth a real `python main.py` eyeball.
- **Settings → Cubeon Web link is NOT in this commit.** There is no website URL
  anywhere in the repo (`cubeon.run.place` does not even resolve), so guessing
  one would ship a dead link. Asked the user for it; it is a small follow-up.
- The 30ms/20ms timer gaps are tuned by reasoning, not measurement. If a fast
  click sequence ever looks like it "sticks", that gap is the first thing to
  look at.
