# 2026-09-11 — Fix: closing the window reopened the launcher (GPU-crash misfire)

## The bug (user report)
Closing Cubeon printed
`cubeon: client crashed mid-session (GPU driver?) - restarting with software
OpenGL (attempt 1)` and the window came back. It happened on every close,
because the crash-vs-close discriminator was invalid.

## Root cause
`_session_loop` decided "user close" vs "mid-session crash" by calling
`_kill_flet_client()` and checking whether it found a **live `flet` child
process**:
- live child → assumed user X-close (ghost window left behind) → park/exit
- no/zombie child → assumed crash → re-exec with software GL

But on flet 0.86 the client can never be alive at that point. `ft.run()` in
`flet/app.py` does `await fvp.wait()` and only returns **after the client has
exited and been reaped**. So `_kill_flet_client()` always returned `False`, and
every normal close was misread as a crash and relaunched.

I reproduced it under Xvfb: `xdotool windowclose` on the real app produced the
"client crashed mid-session" line and spawned a fresh flet client.

## The fix
Use the one signal that actually differs: the client process's **exit status**.
- `_capture_flet_client_exit(slot)` wraps `flet_desktop.open_flet_view_async`
  before `ft.run`, returning a thin proxy whose `.wait()` records
  `proc.returncode` as flet awaits it.
- `_classify_session_end(ui_painted, client_exit)` is now the pure decision:
  - `not ui_painted` → `pre_paint_crash` (retry with software GL, unchanged)
  - `ui_painted` + negative exit (`-11` SIGSEGV, …) → `mid_session_crash`
    (arm fallback + re-exec, unchanged)
  - anything else (`0`, other `>=0`, or `None`) → `clean_close` (park/exit)
- `_kill_flet_client()` is kept as a best-effort ghost cleanup only; its return
  is no longer used for classification.

Failure-safe direction: if the flet API moves and the slot stays `None`, every
end is treated as a clean close — the launcher never springs itself back open by
accident.

## Verification
- Mechanism probe (minimal flet app under Xvfb) confirmed exit codes:
  window close → `0`; `kill -SEGV` on the client → `-11`.
- End-to-end, real `main.py` under Xvfb with an isolated `$HOME`:
  - `xdotool windowclose` → launcher exits, **no** new flet child, **no**
    "client crashed" line, no `use_software_gl` marker written. ✅
  - `kill -SEGV` on the live client → "client crashed mid-session … attempt 1"
    and `use_software_gl` armed → recovery still works. ✅
- `tools/test_ui_smoke.py` **105/105** (added §4b, 8 new checks around the
  classifier). Full sweep green: test_friends 37, test_mod_bridge 119,
  test_friends_service 213, test_mod_matrix 68, test_capes 14, test_invites 127,
  test_modpacks 51, test_mod_store 21, test_net 19, test_production 13,
  test_gallery 38, test_versions_profile_key 11, test_launch_indicator 11,
  test_milestones 50 (known flake failed once, passed on rerun).

## Files
- `main.py`: `_classify_session_end`, `_capture_flet_client_exit`, rewired
  `_session_loop` branches, `_kill_flet_client` comment.
- `tools/test_ui_smoke.py`: §4b regression section.
- `agents/docs/module-map.md`: rewrote the "Mid-session GPU-crash auto-recovery"
  entry with the flet-reaping fact and the new discriminator.

## Note for the next agent
Anything that tries to inspect the flet client *after* `ft.run` returns is
doomed: flet has already reaped it. Intercept the process object or use a
marker — never poll `/proc` for a live child.
