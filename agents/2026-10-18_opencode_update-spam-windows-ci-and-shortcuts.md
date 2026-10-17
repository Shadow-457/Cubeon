# Update spam, a Windows CI gate that never ran, F11 + shortcuts, and crash forensics (2026-10-18)

**Model:** DeepSeek V4.1 Flash Free (OpenCode) · one session, five payloads, two
releases (v1.2.7 shipped; the crash forensics below is the next one).

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

## 5. The crash: what it actually was (and why it left *no trace*)

The report arrived as a KDE screenshot from a **friend's** machine (`saim`): the
**Crash Reporting System** showing *two* dialogs for

```
/home/saim/.flet/client/flet-desktop-light-0.86.5/flet/flet has encountered a
fatal error and was closed.
```

That is the **flet desktop client** — the Flutter/GTK window process, not our
Python — **dying to a signal**. Two dialogs = attempt 1 (hardware GL) and the
software-OpenGL retry both died, after which the recovery ladder gives up and
the launcher disappears without a word. The ladder itself was already right
(pre-paint death → in-process retry with `use_software_gl`; mid-session death →
re-exec bounded by `CUBEON_GPU_RESTARTS`), and is documented as such.

What was broken was that **this crash could not be diagnosed at all**:

* every crash message was a `print()` to **stdout**, and a user launching
  Cubeon from a desktop menu has no console — there was nothing to send us;
* `setup_logging()` was only reached from `main()`, the flet **session**
  callback. A **pre-paint** crash means `main()` never runs, so logging was
  never configured and `~/.cubeon_launcher/cubeon.log` stayed **EMPTY**. The
  screenshot was the only evidence in existence.

New `cubeon/incident.py` (total functions — the crash path must never raise,
and `describe_exit(None)` must never read as clean):

* `describe_exit(-11)` → `-11 (SIGSEGV - killed by signal)`;
* `crash_record/record_session_end` → **one greppable line per session end**
  (`flet session ended: kind=… client_exit=… ui_painted=… session=… desktop=…
  software_gl=… gpu_restarts=… flet=… client=… client_bin=… gallium=…`),
  loggable at INFO for a clean close so "the log stops here" ≠ "the user closed
  it";
* `ClientOutputTail` → the client's own last 25 non-ATK lines, consecutive
  repeats collapsed to one (a GL-frame-timeout storm used to be able to bury
  the earlier context);
* `client_binary` → the bundle actually being spawned, its stub size and
  whether the Flutter engine `.so`/`.dll` is present. A PARTIAL unpack of
  `~/.flet/client/flet-desktop-*` (flet unpacks once and trusts it forever)
  kills the client on every launch and looks identical to a driver crash in a
  report — but it is the one client-side fault that is ours to fix;
* `gallium_driver` → the Mesa library on disk, i.e. **the object that crashed**;
* `record_giving_up` at ERROR in both exhausted branches;
* `wayland_x11_fallback` → a **retry-only** second dice roll for the other
  documented Linux crash class (GTK/Wayland): `GDK_BACKEND=x11`, but only on
  Wayland, only when `DISPLAY` exists (no XWayland ⇒ forcing x11 would fail the
  start outright), and never over a user-chosen `GDK_BACKEND`.

`__main__` now calls `setup_logging()` **before** `_session_loop()`, which is
the actual one-line fix for the empty log.

## 6. Root cause found — it is Mesa, not Cubeon

The maintainer's own box turned out to have the same crash all along, with
**core dumps**: Arch, `mesa 1:26.1.6-1`, AMD Polaris/Ellesmere (RX 470–590).
`coredumpctl info` on a run whose `cubeon.log` just stops:

```
#0      libc.so.6                              (SEGV_ACCERR)
#1-#7   libgallium-26.1.6-arch1.1.so
#8-#9   libflutter_linux_gtk.so
#10-#18 libgtk-3.so.0 → g_signal_emit → gtk_container_propagate_draw
```

A Mesa driver fault during a GTK/Flutter paint — three layers below any Python
(`SEGV_ACCERR`, a bad write from inside the driver). The Mesa 26.1 series is a
known radeonsi/gallivm SIGSEGV regression train ("[radeonsi] SIGSEGV in gallivm
during software fallback", 26.1.4 relnotes; 26.1.8 closed the series), and
**`mesa 1:26.2.4-1` was already sitting in `extra`** on the crashing machine.

So the two things that follow, both shipped here:

1. the log now names the library (`gallium=libgallium-26.1.6-arch1.1.so`), so
   "is this the known Mesa bug?" is one grep of a user's `cubeon.log`;
2. the retry ladder escalates the driver. This is the important one: **llvmpipe
   shares the failing LLVM JIT (gallivm) path with radeonsi**, which is why the
   software-GL retry could never have saved it — and it explains the module
   map's old "crashes on hardware AND llvmpipe" note, written long before there
   was a backtrace. `driver_for_attempt()` now uses `llvmpipe` for retry 1 and
   **`softpipe`** (Mesa's reference C rasterizer, no JIT at all) for the final
   one, with the attempt count `max(_retries, CUBEON_GPU_RESTARTS)` so a
   re-exec'd mid-session restart escalates too. softpipe is slow, so it is
   last-resort only — and it cannot trip the wedge watchdog, whose GL-timeout
   rule requires a BURST (< 4 s apart) exactly to spare a merely slow client.

## 7. "Dialog is already opened" — the random user error

Report: *"The application encountered an error: Dialog is already opened — this
error just came upon a users, they are so random."*

Flet 0.86's `Page.show_dialog()` raises `RuntimeError("Dialog is already
opened")` for an instance already in `page._dialogs.controls`, and
`cubeon/dialogs.open_dialog()` — the single funnel all 25 call sites use —
passed it straight through. The exception escapes the handler that mounted the
dialog, so a **no-op** (the user is looking at that dialog already) reached them
as an application error banner. Hence "random": anything that can fire twice
does it.

The repo already knew: main.py had `_dialog_mounted` and ui/versions.py
`InstancesManager._is_mounted` as one-off guards — but the shared helper
underneath them was still exposed. The helper is now **idempotent**: membership
in the stack decides (NOT `.open` — flet removes a barrier-dismissed dialog from
the stack without clearing the flag), a mounted dialog is refreshed in place,
and a lost race is swallowed *only* for the known `already open` message so
other RuntimeErrors still surface. Suppression logs at INFO with the dialog
class, so a repeat tells us which dialog double-opens.

`tools/test_dialogs.py` (21 checks) drives a FakePage that reproduces flet's
real double-mount raise, and fails if any shipped module calls
`page.show_dialog()` directly (only `cubeon/dialogs.py` may).

## Verified
Full CI-equivalent suite (`tools/test_*.py`, minus the manual `test_visual_*`
and `test_wedge_watchdog.py`): **SUITE_DONE failed=0** (three separate runs —
one of them caught the tooltip regression above, which is why the fuzz suite
exists). Focused: `test_update_notice.py` 20/0, `test_keyboard_shortcuts.py`
50/0, `test_pack_install_guard.py` 28/0, `test_incident.py` 74/0,
`test_startup.py` 25/0,
`test_winwindow.py` 28/0, `test_osnotify.py` 69/0, `test_modpacks.py` 70/0,
`test_ui_smoke.py` 246/0. The crash record was also driven end-to-end against a
throwaway `HOME`: a clean close logs at INFO with no tail, a `-11` crash logs at
WARNING with the client's own output, and the give-up logs at ERROR — all three
lines landing in that `cubeon.log`. Windows paths could not be executed here
(Linux box); the Windows job is the gate for those, and it went green for the
first time on 1.2.7.

## Open thread for the next agent 🔴
The crash is now **diagnosed to the library** (Mesa 26.1.x `libgallium`, in a
radeonsi/gallivm regression; see §6) and the launcher now logs it — but the
crash itself is **not fixed by Cubeon** and cannot be: it happens three layers
below us. What is still open:

* **The user-side fix is the Mesa update** (`sudo pacman -Syu mesa` → 26.2.4 on
  an affected Arch box; the maintainer's own machine is exactly this case).
  Anything else is a workaround. Worth confirming after an update that the
  crash record stops appearing — and, if a user can't update, whether the new
  `softpipe` final attempt actually gets the window up.
* **The friend's machine (`saim`, client 0.86.5)** has not been re-checked since
  its screenshot. Ask for a `cubeon.log` from a build **>= 1.2.8** (the crash
  record only exists from this commit on) and grep it for `flet session ended:`
  / `giving up after`. That one line now carries the signal, `ui_painted`,
  whether software GL was already in force, the session/desktop, the flet
  **client** versions, the client bundle's integrity, and `gallium=<lib>` — which
  is the whole "is this the known Mesa bug" question. A DrKonqi **Details**
  backtrace is the other decisive artifact.

Two things that ARE now true and worth knowing:
* there is a **crash→re-exec relaunch loop** (`main.py` ~8110: `use_software_gl`
  marker, `_MAX_CLIENT_RETRIES=2`, `_MAX_MIDSESSION_RESTARTS=2`). A relaunch
  re-runs `main()`, so it re-ran the update check too — meaning part of the
  "coming up again and again" may have been this loop echoing the notice. The
  once-per-version marker now silences the repeat regardless.
* a Windows-only startup crash was invisible to CI until this session; if the
  report is Windows, watch the `Startup tests (Windows)` job on the next push
  (it went green for the first time on 1.2.7).
