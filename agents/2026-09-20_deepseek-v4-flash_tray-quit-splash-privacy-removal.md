# 2026-09-20 — tray Quit ghost window, startup splash, Privacy removal

Three user reports, all fixed in `main.py` unless noted.

**1. Tray Quit while the window is open left a "Working…" ghost window.**
`_tray_quit()` ran the rpc/friends cleanup first and killed the flet client
last. That cleanup can deadlock on native teardown; when it did, the 3s bail
timer's `os._exit(0)` fired with the client still mapped — the launcher was
gone but the disconnected engine spinner stayed on screen forever. Order
changed to: save geometry (needs the live page), `_kill_flet_client()`, then
the cleanup. Now the window is gone no matter how cleanup goes.

**2. Startup splash.** `main()` now mounts a small centered "Loading Cubeon"
card (360x200, non-resizable, icon + spinner) right after the theme is
applied and reveals it immediately, then swaps it for the real UI
(`page.controls.clear()` + append + `page.update()`) once the tree is built.
The saved window geometry moved into `_apply_real_geometry()`, called only in
`_reveal_window` — so the splash opens small and the finished UI opens at the
user's saved size. Seasonal ambience now uses the saved `_gw` instead of
`page.window.width` (which is the splash width during the build).

**3. Privacy removed completely.** Deleted `cubeon/crashreport.py`, the
Settings > Privacy section (`ui/settings_tab.py`, SECTIONS + pane), the
`crash_reports_cb` control/handler in `main.py`, and the crash-reporting
wiring in `cubeon/logging_setup.py` (`setup_logging` no longer takes
`crash_cfg`; excepthooks still log to the rotating file, but send nothing).
`tools/test_production.py`'s crashreport section was removed.

**Verified:** `py_compile` on every touched module; `test_ui_smoke.py` 148
(5 new checks: tray-quit call order, splash mount, splash→UI swap, geometry
applied on reveal, Privacy/crashreport gone), `test_production.py` 51,
`test_mega_smoke.py` 16, `app_driver.py fuzz` 0 errors / 0 None children,
plus `test_fuzz` 13, `test_launch_indicator` 11, `test_seasonal` 106,
`test_net` 21, `test_invites` 127, and the mod/content suites green.
`test_wedge_watchdog.py` has 1 pre-existing failure ("ladder terminates")
that also fails on a clean tree — not from this change. Durable facts added
to `agents/docs/module-map.md`.
