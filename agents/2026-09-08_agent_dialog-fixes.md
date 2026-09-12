# 2026-09-08 — dialog API fix (popups that never close), account-scrim fix, Legacy persistence, client-mod off-switch

## What was broken (all reported as "popup doesn't close / closing sidebar does shit")

1. **Dialogs never closed.** Flet 0.86.5 has NO `Page.open()`/`Page.close()`
   (removed; the API is now `Page.show_dialog()` / `Page.pop_dialog()`, with
   dialogs living in a managed stack at `page._dialogs.controls`). Every
   dialog helper in main.py, ui/server_tab.py, ui/modpacks_tab.py and
   cubeon/inspector.py did `if hasattr(page, "open") ... else <pre-0.28
   legacy branch>` — and since `open` doesn't exist, ALL of them fell into
   the legacy branch (`page.dialog = dlg` sets a meaningless attribute on
   0.86; `page.overlay.append(dlg)` adds a control that renders as an
   overlay child, not a modal). Result: the Legacy dialog, version picker,
   rename/delete dialogs and the onboarding dialog either misrendered or
   opened and could never be programmatically closed; every SnackBar toast
   in the app never appeared at all.
2. **The Account panel's scrim never went away.** `_close_account_panel`
   faded the scrim to opacity 0, then a 0.25s timer set `visible = False`
   and called `thread_safe_ui.final_update(page)` — which only repaints
   when a THROTTLED update is pending. Nothing was pending, so the
   `visible=False` patch never shipped: an invisible full-window
   click-catcher stayed on top forever. That's the "closing it just causes
   the app to do shit" — every click after closing the panel hit the ghost
   scrim.
3. **Legacy toggle didn't persist** (reset every launch) and its docstring
   was after the `return`, dead.

## What was done

- New shared module **`cubeon/dialogs.py`**: `open_dialog(page, dlg)` /
  `close_dialog(page, dlg)` / `show_snack(page, msg, action=...)`, handling
  0.86 (show_dialog/pop_dialog + flag-flip for a buried dialog) with
  old-Flet fallbacks. main.py's `_open_dialog`/`_close_dialog`/`_show_snack`
  and the ui/*.py copies now all delegate to it. Removed ~9 broken
  `page.open(SnackBar)` sites in main.py, 4 in ui/, 3 in inspector.py.
- Scrim retire now uses `thread_safe_ui.refresh(account_scrim)`.
- Legacy opt-in persists as `cfg["legacy_versions"]`; the button label
  initializes from it.
- Escape closes the Account panel (via the existing keyboard hook; F12
  inspector kept).
- **New option: disable the Cubeon Client mod.** `cfg["client_mod_enabled"]`
  (default True) + a Settings → "Game versions" checkbox.
  `cubeon/launch.py` now treats `not cfg.get("client_mod_enabled")` the
  same as a public build: no jar install AND `remove_installed()` sweeps
  any stale copy a previous run left (a leftover would still load).

## How verified

- tools/test_ui_smoke.py: FakePage now mirrors the REAL 0.86 dialog API
  (`show_dialog`/`pop_dialog`/`_dialogs` stack) — the old fake exposed
  open()/close() and so masked the entire bug class. New §9 exercises
  open→close, buried-dialog close, snackbar mount, and asserts no raw
  `page.open(`/`page.close(` remains in main.py or ui/. Plus checks that
  the client-mod switch exists in Settings/config/launch. **60 passed.**
- Full battery green: fuzz 12, production 13, mod_store 21, modpacks 51,
  capes 14, friends_service 187, friends 37, mod_bridge 119, mod_matrix 68,
  net 19, invites 127.
- Live launch: window builds, session connects, no Python-side errors in
  cubeon.log (the "Timed out waiting for OpenGL frame" line is this
  headless box's GL, pre-existing).

## Gotchas for the next agent

- **Flet 0.86 dialog contract**: `show_dialog()` raises if the dialog is
  already in the stack; `pop_dialog()` closes the TOP open one. To close a
  specific buried dialog, set `dlg.open = False` + `dlg.update()`. The
  managed stack is `page._dialogs.controls` — dialogs are NOT in
  `page.overlay` anymore.
- FakePage in test_ui_smoke now REJECTS the removed API by construction
  (it has both, but the app is asserted to never call open/close raw).
- `_show_snack`'s Text color: `ft.Text(color=None)` is fine (theme default)
  — pass `text_color=ON_ACCENT` from main.py only.

## Question for the next agent
The mod-side (CubeonClientScreen) has no "disable" concept — the launcher
simply stops shipping the jar. Is that sufficient UX, or should the mod's
pause-screen button also be hideable per-profile from the launcher side
(e.g. via a bridge flag)? Left as-is for now.
