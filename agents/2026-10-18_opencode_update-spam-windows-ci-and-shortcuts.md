# Update spam, a Windows CI gate that never ran, F11 + shortcuts (2026-10-18)

**Model:** DeepSeek V4.1 Flash Free (OpenCode) · one session, four payloads.

## 1. "The new-release notification is spamming and not stopping"

User words: *"just spamming and not stopping like it's just coming up again and
again"*. Two independent defects on the SAME message:

* `main.py`'s `_offer_update` snackbar had **no memory at all** — an available
  update was announced on **every start**, forever. The only once-per-version
  gate in the tree was the OS toast's `osnotify_last_update`, and it **failed
  open**: `osnotify.update_available()` returns False whenever that toast kind
  is off or no notifier exists, so its marker was never written on those boxes.
* The check ran **twice per start**: one call with `cfg["update_token"]`
  (snackbar), a second without it that existed only to fire the OS toast. Two
  GETs, and on a private repo two different answers for the same release.

Fix: one check, one announcement, two channels. `cubeon/updater.py` gained
`should_announce(cfg, version)` — a total function (blank version announces
nothing; a non-dict/hostile config still answers True, since a missed notice
beats a repeated one) that **marks the version in the config in place**.
`main.py::_announce_update` is now the single callback: gate → save marker →
optional OS toast → snackbar. The marker is written *before* either notice goes
out, so a muted notifier or a closed window can never cost the notice and can
never turn into a nag.

## 2. `[skip ci]` and the red "Startup tests (Windows)" job

* The `[skip ci]` the maintainer asked about is the **release job's own
  version-bump commit** (`release: v1.2.6 [skip ci]`). It is deliberate and
  load-bearing: without it every release would trigger another release. That
  commit only rewrites the version literal, and the run that pushed it had
  already run the full suite + all three platform builds before publishing.
  Nothing to fix.
* The Windows startup job was **red on every single run since it was added**,
  for a reason that had nothing to do with the app: `tools/test_startup.py`
  refused every outbound connect to prove "no network on the UI thread", but on
  Windows `socket.socketpair()` is a real 127.0.0.1 TCP pair (CPython's
  fallback binds `_LOCALHOST` then `csock.connect((addr, port))`) and
  `ProactorEventLoop` builds its self-pipe with it. So `asyncio.run()` died
  **before `main()`** → `OSError: network disabled …`, `controls=0`, every run.
  `test_winwindow.py` §1 had the mirror problem: it asserts the OFF-Windows
  no-op ("returns immediately") but the file runs on `windows-latest`, where
  the module is the real thing (polls to the timeout, 4.44s).
  Fix: `_is_loopback()` lets `127.0.0.0/8` / `::1` through (plus
  `socket.create_connection`, the call urllib3 actually makes — so the
  invariant got *stronger*), and the winwindow timing assertion is branched on
  `os.name`. **The Windows job now genuinely builds the UI on Windows for the
  first time** — that is where a Windows-only startup crash will finally be
  visible.

## 3. Keyboard shortcuts + F11 fullscreen (asked in the same session)

Decision table in a new pure module `cubeon/shortcuts.py`; `main.py` only
dispatches. F1 help · F11 fullscreen · Esc closes the topmost thing (help
dialog → fullscreen → Account panel) · Ctrl/Cmd+1…9 jump tab (indexed off the
LIVE `top_nav_items`, so a build without the Chat tab numbers correctly) ·
Ctrl+, Settings · Ctrl+Enter the big button (refuses a disabled Play) · Ctrl+Q
quit. Fullscreen goes through `_force_window_bool("full_screen", …)` because
`full_screen=False` is flet's declared default and a bare write is DROPPED —
the same trap as `visible`/`maximized`. Non-obvious collisions fixed on the
way: fullscreen parks the resize hot-zones and makes `_save_geometry_now`
store nothing (a screen-sized rect must not become the restored window), and
native `enter/leave-full-screen` events are adopted without writing back.

**Caught myself breaking the fuzz suite:** appending "· Ctrl+3" to the top-nav
tooltips made `tools/test_fuzz.py` report "never reached: export_mrpack",
because `tools/_fuzz_common.ctrl_text` reads an icon-only nav button's TOOLTIP
as its label and `goto()` matches it exactly. Reverted to `tooltip=label` and
pinned it with a test. Lesson is in the module map.

## 4. Carried over from earlier in the session

* **Pack-install guard**: a modpack install writes the base version + loader
  first and its mods last, so a disk scan called it installed and the Play
  button offered PLAY on a half-written profile. `cubeon/modpacks.py` now
  keeps a refcounted in-flight registry keyed by mc_version (raised before the
  first write, released in `finally`); the button shows a disabled
  `INSTALLING…` (never a lying CANCEL), and the click path, prefetch, Instances
  manager and mod doctor all stand down while it holds.
* **28 + 50 + 20 = new checks** in `tools/test_pack_install_guard.py`,
  `tools/test_keyboard_shortcuts.py`, `tools/test_update_notice.py`.

## Verified
Full CI-equivalent suite (`tools/test_*.py`, minus the manual `test_visual_*`
and `test_wedge_watchdog.py`): **SUITE_DONE failed=0** (three separate runs —
one of them caught the tooltip regression above, which is why the fuzz suite
exists). Focused: `test_update_notice.py` 20/0, `test_keyboard_shortcuts.py`
50/0, `test_pack_install_guard.py` 28/0, `test_startup.py` 25/0,
`test_winwindow.py` 28/0, `test_osnotify.py` 69/0, `test_modpacks.py` 70/0,
`test_ui_smoke.py` 246/0. Windows paths could not be executed here (Linux box);
the Windows job is the gate for those, and it is now actually running.

## Open thread for the next agent 🔴
The maintainer also reported **crashes "on user and me too"** in the same
breath, and I could NOT pin one down: `~/.cubeon_launcher/cubeon.log` has no
`Unhandled error in main() handler` since the 2026-10-17 `cfg` ordering crash,
no `use_software_gl` marker exists on this box, and the repo has **no crash
reporting pipeline at all** (deliberately — `test_ui_smoke.py` asserts main.py
never mentions it). Ask for the actual traceback/console text before guessing.
Two things that ARE now true and worth knowing:
* there is a **crash→re-exec relaunch loop** (`main.py` ~8110: `use_software_gl`
  marker, `_MAX_CLIENT_RETRIES=2`, `_MAX_MIDSESSION_RESTARTS=2`). A relaunch
  re-runs `main()`, so it re-ran the update check too — meaning part of the
  "coming up again and again" may have been this loop echoing the notice. The
  once-per-version marker now silences the repeat regardless.
* a Windows-only startup crash was invisible to CI until this session; if the
  report is Windows, watch the `Startup tests (Windows)` job on the next push.
