# Play-button truth + seasonal off + tray-open guard (smoothness pass)

- **Agent:** Cline (GLM)
- **Date:** 2026-09-18
- **Task:** smoothness/performance pass; fix stuck "GAME RUNNING..." button;
  seasonal layer off by default; make tray Open/Quit bulletproof.

## What I did

All in `main.py` unless noted:
1. `on_exit()` (game process exit) now resets the play button to
   PLAY/DOWNLOAD — it previously NEVER did, so a closed game left the button
   on "GAME RUNNING..." until some unrelated repaint. This was the
   user-reported bug; the comment even claimed on_exit owned the reset.
2. `on_version_selected()` shows GAME RUNNING... when the selected version is
   the one actually running (was: offered a second launch of a live game).
3. New `_reconcile_running_button()`, called on Play-tab entry: if a running
   version is claimed but `watchdog.stale_session()` proves nothing alive,
   clears the claim and repaints. Covers launcher re-exec (GPU-crash
   recovery / tray reopen) that orphans `state["running_version"]`.
4. `set_button_mode()` repaints just `play_button`
   (`thread_safe_ui.refresh`) instead of `page.update()` — the mode only
   mutates 3 controls inside that subtree.
5. `_tray_activate()` ignores tray clicks while a window session is live
   (`_tray_runtime["controller_page"]` is set); previously every click
   re-exec'd a fresh launcher even under an open window.
6. `cubeon/config.py`: `seasonal_theme`/`season_pet` defaults → False
   (user request); Settings fallbacks in main.py matched. Existing saved
   configs are untouched.

Docs: `docs/performance/smoothness-audit.md` (issue-by-issue) and
`docs/performance/performance-notes.md` (changed/not-changed/measurements).
Known deferred work (tab-module page.update() scoping) is listed there.

## How I verified

- Full suite green AFTER the changes: mega_smoke 16, ui_smoke 148,
  seasonal 106, friends_service 370, friends 95, invites 127, modpacks 64,
  mod_store 27, net 21, production 58, mod_bridge 126, mod_matrix 68,
  capes 19, p2p_relay/session/transport PASS, version_integrity 39,
  server_integrity 59, mod_compile clean.
- Measured: `import main` 0.29s, `import launcher_core` 0.22s, seasonal
  boot <1ms — startup is flet-client-bound, not import-bound; left alone.

## Notes for the next agent

- `_tray_runtime["controller_page"]` doubles as "is a window live" — keep it
  in sync if you touch session teardown, the tray guard depends on it.
- `set_button_mode` is now scoped: anything that wants a broader repaint must
  call `page.update()` itself (callers do).
- If you add a place that sets `state["running_version"]`, you must also
  clear it on exit AND make sure `_reconcile_running_button` can prove it
  dead, or the button will stick again.
- Round 2 ("more bulletproof"): the game-running truth is now defended by
  THREE independent mechanisms — click-time watchdog re-verify in
  `on_play_click`, the `running-liveness` daemon thread (5 s poll while a
  claim is live; keep its `threading.enumerate()` dedupe if you rename it),
  and an exception-proof fallback in `on_exit`. Don't remove any one of them:
  each covers a different failure mode (stale claim, dead watcher thread,
  exception mid-exit-handler).
- `test_ui_smoke.py` showed one transient 146/2 timing flake (animator ticker
  tests sleep on real time); 5 consecutive clean runs after. If you see a
  1-2 test flake there, re-run before debugging.

## Question for the next agent

The version picker rebuilds its list on every filter keystroke
(`_rebuild_pick_list`). It's bounded today, but if the online version list
ever grows into the thousands, a debounce + row recycling would be the next
smoothness win. Worth measuring before touching.
