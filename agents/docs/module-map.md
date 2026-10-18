# Cubeon module map — read this before reading any source

## This repo moved, and Cubeon is now a Ylet product (2026-10-18) — INVARIANT
The company folder was reorganised the same day this map was last edited:

    ~/Ylet_Productions/
      docs/ legal/ brand/ site/      ← the company hub, one level up
      products/cubeon/               ← THIS repo (was Products/Cubeon)
      products/icono/ products/spruce/ products/launch-video/
      tools/spruce-catalog/

Durable consequences — do not re-derive these:
- **Every absolute path containing `Products/` is dead**, including
  `/home/fuckarch/Ylet_Productions/Products/Cubeon`. `Products/` no longer
  exists. Anything pinned to it (IDE workspace, a script, a shell history) must
  be reopened. `git`, Python imports and the test suite all work fine from the
  new path.
- `.venv-build/` was **already broken before the move** — its `pyvenv.cfg`
  still names `/home/fuckarch/Downloads/Cubeon/.venv-build`. Recreate it; never
  trust it.
- **Do not `git init` `~/Ylet_Productions/`.** `products/*` and the company
  folders are separate repos; a root repo would swallow them.
- The company hub (brand docs, the `legal/` pack, the living project map) is at
  `~/Ylet_Productions/` — `docs/PROJECTS.md` is the equivalent of this file for
  the company as a whole.
- **Branding:** all 15 `web/*.html` footers now read "A Ylet product" with a
  link to `www.ylet.online`, and `web/privacy.html` now says *"Cubeon is
  operated by Ylet"* where it used to say *"run by Hamza … a small fan project
  rather than a company"*. The formal documents
  (`legal/TERMS.md`, `legal/PRIVACY.md`, `legal/TRADEMARK.md` and the dated
  operator notice) are **unsigned and unpublished**. Do not publish them, and
  deliberately **do not bump the pages' "Policies last updated" date** until
  they are signed — the date moves with the signature, not ahead of it.
- **House style: no em dashes.** Every `.md`/`.html` prose file in the company
  folder was cleaned on 2026-10-18 by
  `~/Ylet_Productions/tools/strip-em-dashes.py` (489 dashes, 47 files). Cubeon's
  `docs/` and `AGENTS.md` are included; `agents/` is not, except the
  byte-identical `agents/docs/bugs-and-flaws.md` that must keep matching
  `docs/decisions/bugs-and-flaws.md`. Code and `products/spruce/data/` are
  deliberately untouched. See `docs/BRAND.md` section 5.
- The legal pack is also rendered to PDF by
  `~/Ylet_Productions/tools/md2pdf.py` (WeasyPrint). **Edit the Markdown, never
  the PDF.** The operator named in it is **Hamza Shahbaz**, trading as Ylet.

## Windows: the window is shown by the OS, not just by flet (2026-10-16) — INVARIANT
- User report, AGAIN, on the shipped 1.1.2 build: "Cubeon.exe is in Task
  Manager but no window ever appears." The reveal is a MESSAGE to the desktop
  client, which is started hidden (`view=FLET_APP_HIDDEN` -> flet_desktop sets
  `FLET_HIDE_WINDOW_ON_START=true` for the client process). Flet only calls
  `windowManager.show()` when `visible` DIFFERS from the client's OWN cached
  window state, so a `visible: true` patch can be skipped even though the
  native window is hidden; if the client never processes the message at all
  (wedged UI thread), the launcher lives on invisibly and writes nothing to
  cubeon.log - a launcher with no window can't report anything.
- Every reveal path therefore sends THREE things, and none of them may be
  dropped:
  1. `_show_window()` - `page.window.visible = False` then `= True` (a bare
     `= True` is dropped by flet before it is ever sent: `Prop.__set__`
     ignores a write equal to the declared default, and `visible` defaults to
     True).
  2. `_reveal_to_front()` -> `page.window.to_front()`, bounded by
     `asyncio.wait_for(..., 5)`. This is a METHOD call, and the client's
     implementation calls `windowManager.show()` with NO isVisible() guard -
     the one reveal flet cannot skip. Scheduled with `page.run_task`, never
     awaited inline (a wedged client never answers).
  3. `_backstop_window_visible()` - Windows only, daemon thread ->
     `cubeon/winwindow.py::ensure_client_window_visible()`, which finds OUR
     flet client's top-level window (psutil, two-factor: name ~ "flet" AND
     (our child OR our assets dir in its cmdline) - never another instance's
     window, never Minecraft's java) and `ShowWindow()`s it, then logs the
     outcome at INFO/WARNING. It POLLS for up to 10s, so it must never run on
     flet's event loop; it is a no-op off Windows and never raises. This is
     the only reveal that survives a client that processes nothing, and its
     log line is the evidence the next bug report needs.
- Guard: `tools/test_ui_smoke.py` pins all three (source order + a recording
  window asserting `visible=False -> True -> window.update -> to_front`, plus
  that the backstop arms exactly ONE thread per session and is inert off
  Windows) and `tools/test_winwindow.py` covers the winwindow policy loop with
  an injected user32 stand-in (28 checks; registered in
  `tools/test_mega_smoke.py` SUITES, and picked up by CI's `tools/test_*.py`
  loop). Do not "simplify" any of the three away - each covers a failure the
  others cannot.
- What is NOT verified from this box (Linux, and Wine doesn't honour the
  hidden start): that user32 `ShowWindow` really un-hides the client window on
  real Windows. The module logs its outcome precisely because of that.
- Known upstream context (researched 2026-10-16): flet's Windows runner only
  started honouring `FLET_HIDE_WINDOW_ON_START` in **0.85.3** (flet-dev/flet
  #6526 / PR #6527; before that the window flashed on first frame). Cubeon
  ships flet 0.86.5, so the hidden start IS honoured on Windows - which is why
  every reveal had to become load-bearing there.

## Windows: the custom window frame is opt-in, and the Prop rule is why (2026-10-17)
- User report with a VM screenshot: on Windows the launcher carried TWO headers -
  the OS title bar (icon + "Cubeon" + min/max/close) stacked above Cubeon's own
  branded top bar. Nothing was broken; the native bar is just outside the design
  system and duplicates the brand. Answer: a FRAMELESS window whose existing top
  bar BECOMES the title bar.
- **It is a prototype, not the default.** Flag: config key
  `custom_window_chrome` (cubeon/config.py) or the env override
  `CUBEON_CUSTOM_CHROME=1/0` (the env WINS, and works in both directions). It is
  WINDOWS ONLY by design - the Linux/GTK window path is the fragile one and gains
  nothing. Policy in `cubeon/winchrome.py` (Flet-free: enablement, the 8 resize
  hot-zones, the maximize state machine), widgets in `ui/window_chrome.py`, wiring
  in `main.py` (one `page.window.frameless = True` on the HIDDEN window, before
  `_apply_real_geometry`; `ft.WindowDragArea(content=top_bar)` for move +
  double-click-maximize; a `ft.Stack` over the shell carrying the hot-zones).
- **The flet Prop rule that drives every window write** (verified in this build's
  source, `flet/controls/value_types.py` + `flet/controls/object_patch.py`):
  `Prop.__set__` DROPS a write equal to the value already stored, AND the patch
  pass emits ONE `replace` per dirty field carrying the field's CURRENT value -
  so an intermediate write never reaches the wire, but a repeated value sends
  nothing at all. Hence `main.py::_force_window_bool` writes `not value` then
  `value` for minimize/maximize: the second `minimized = True` would otherwise be
  dropped and the button would go dead. It is also why `visible=False` then `True`
  works but a bare `visible=True` does not (see the reveal invariant above).
- Restore-from-taskbar resets the client's own `_minimized` cache (flet re-reads
  the native state on every window event), which is what lets the minimize button
  work more than once. A window that STARTS maximized gets NO event (the maximize
  happens before `page.window.on_event` is wired), so main.py adopts
  `page.window.maximized` when it builds the buttons - a stale False would leave
  Restore dead.
- Guards: `tools/test_winchrome.py` (31 checks, policy + hot-zone geometry +
  event->state mapping) and `tools/test_ui_smoke.py` section 13b (source order,
  plus the widgets built FOR REAL off Windows). `tools/test_mega_smoke.py` layer 5
  stubs the policy to TRUE and builds the whole frameless UI headlessly - the only
  place the Windows-only branch is exercised in CI.
- What is NOT verified from this box: whether `setAsFrameless` keeps a native
  resize border on real Windows (hence the hot-zones), and whether the hidden-start
  reveal still works under a frameless window. That is exactly what the flag is for.

## Keyboard shortcuts + F11 fullscreen (2026-10-18) — INVARIANTS
- **The decision table lives in `cubeon/shortcuts.py` (pure, Flet-free) and
  `main.py` only dispatches.** `resolve(key, ctrl=, alt=, shift=, meta=)`
  returns an action id or `None`; `main.py::_on_key` (the single
  `page.on_keyboard_event` handler, installed at the very end of `main()`)
  maps ids to actions. Do NOT re-implement key matching in main.py — the table
  is what `tools/test_keyboard_shortcuts.py` drives, and `CATALOGUE` is what
  the F1 dialog renders (`_show_shortcuts`), so the on-screen help and the
  real behaviour cannot drift.
- Bindings: **F1** help · **F11** fullscreen · **Esc** close topmost (help
  dialog → fullscreen → Account panel) · **Ctrl/Cmd+1…9** jump to the Nth
  top-bar tab (indexed off the LIVE `top_nav_items`, so a build without the
  Chat tab numbers correctly) · **Ctrl+,** Settings · **Ctrl+Enter** the big
  button (Play/Cancel/Quit) · **Ctrl+Q** quit. F12 (inspector, CUBEON_INSPECT
  gate) stays in main.py, deliberately not in the user-facing table.
- Modifier payloads have been spelled both `ctrl` and `control` across flet
  releases, and the key label is `key` (0.86+) with `data` as the older
  fallback — `_on_key` reads both. **Ctrl or Cmd both count as the command
  modifier** (Cmd+Q works on the macOS build), and **Alt combos are never
  claimed** (Alt belongs to menus/the OS).
- **Ctrl+Enter must check `play_button.disabled` before firing
  `_main_action_click()`** — the mouse path is blocked by `disabled`, and a
  keyboard shortcut must never be a way around a disabled Play (incomplete
  install, "launching...", a live game).
- **Fullscreen goes through `_force_window_bool("full_screen", ...)`, never a
  bare write.** `full_screen=False` is flet's declared default and
  `Prop.__set__` drops a write equal to the stored/default value, so a bare
  `page.window.full_screen = False` would leave the window STUCK fullscreen
  (§"the custom window frame" has the full rule).
- Fullscreen is a SEPARATE claim from maximized (`_fullscreen["active"]` vs
  `_chrome_state["maximized"]`) but they share two consequences:
  `_sync_resize_edges()` hides the hot-zones for either (nothing to resize),
  and `_save_geometry_now()` treats fullscreen as maximized so the
  screen-sized rect is never persisted as the window's restored geometry.
  Native `enter-full-screen` / `leave-full-screen` window events are ADOPTED
  (`_adopt_fullscreen_state`, no write-back — that would ping-pong) because
  the WM or a client-side Escape can change fullscreen without us.
- Discovery: **F1** (the list rendered from `CATALOGUE`). Do NOT append shortcut
  hints to tooltips. An icon-only top-nav button has no visible Text, so
  `tools/_fuzz_common.py::ctrl_text` returns its TOOLTIP as the button's label
  and `goto()` matches it EXACTLY — a `"Modpacks  ·  Ctrl+3"` tooltip silently
  broke the directed fuzz scenarios (`test_fuzz.py` reported "never reached:
  export_mrpack"). The Settings icon's tooltip is pinned to exactly `"Settings"`
  by tools/test_ui_smoke.py + tools/ux_capture.py for the same reason.
  Regression: `tools/test_keyboard_shortcuts.py` (50 checks).

## A pack install claims its instance while it writes (2026-10-18) — INVARIANT
- **`cubeon/modpacks.py` keeps a process-local in-flight registry**
  (`_ACTIVE_INSTALLS`, refcounted per mc_version) raised by
  `_install_from_zip` (the wrapper around `_install_from_zip_body`) BEFORE the
  first byte lands and released in its `finally`. Read via
  `active_pack_installs()` / `pack_install_for(mc_version)`;
  `add_pack_install_listener(cb)` fires on both edges (main.py wires
  `_sync_play_button`).
- Why: a pack install writes the base Minecraft version + loader FIRST, then
  downloads the mods into the `(mc_version, loader)` profile, and only writes
  `_modpack.json` at the end. For that whole window any disk scan calls the
  instance complete, so the 2026-10-18 report was "it isn't fully installed,
  still it says the Play button while it's installing mods — that breaks
  stuff". The claim is keyed by **mc_version** (the base version's folder is
  being (re)written for every loader, so every instance on that version is
  unsafe to launch).
- Guards that read it, and must keep doing so: `set_button_mode`'s claim
  block (`mode = "installing"` — a DISABLED `INSTALLING...`, never a lying
  CANCEL: the Modpacks/Import bar owns that install and its cancel),
  `_sync_play_button`, `on_play_click`, `_begin_install_and_launch` (the Java
  dialog calls it directly), `_play_instance` (Instances manager),
  `prefetch_version._work` (two mll installers on one version folder race on
  the same jars), and `_proactive_mod_repair` (the doctor would race the
  downloads and can prune jars whose files are still in flight; it skips
  WITHOUT marking the profile done so the repair runs after).
- Any NEW installer path that writes an instance's version folder or its
  profile must raise this claim too — a UI flag set only by the Modpacks tab
  was exactly the bug (Import reached the same installer).
  Regression: `tools/test_pack_install_guard.py` (28 checks).

## The Windows startup job: runs the suites, ON Windows (2026-10-18)
- `Startup tests (Windows)` runs `tools/test_startup.py` + `tools/test_winwindow.py`
  on `windows-latest`. Both were written on Linux and had a Linux-shaped
  assumption baked in, so the job was RED on every run and proved nothing:
    * **`test_startup.py` must allow LOOPBACK connects.** It refuses outbound
      connections to prove "no blocking NETWORK call on the UI thread", but on
      Windows `socket.socketpair()` is a real 127.0.0.1 TCP pair (CPython's
      fallback implementation: bind to `_LOCALHOST`, `csock.connect((addr,
      port))`) and asyncio's `ProactorEventLoop._make_self_pipe` builds its
      self-pipe with it. Patching `socket.socket.connect` unconditionally killed
      `asyncio.run()` itself → "OSError: network disabled ..." before `main()`
      ran → `controls=0`, every single run. `_is_loopback()` now lets 127.0.0.0/8
      and ::1 through (`_real_connect` passthrough) and still RECORDS +
      REFUSES any real host — plus `socket.create_connection`, which is the call
      urllib3 actually makes, so the invariant is stronger than before, not
      weaker.
    * **`test_winwindow.py` §1 describes the OFF-Windows branch** ("returns
      immediately, it does not poll out its timeout") but the file ALSO runs on
      Windows, where `ensure_client_window_visible` is the real thing: with no
      flet client it polls to the timeout and answers False (4.44s on CI).
      The timing assertion is now branched on `os.name`; on Windows it asserts
      it really probed.
- Consequence: the Windows job now genuinely builds the UI on Windows for the
  first time. If `main()` crashes on Windows, THIS is where it shows up — check
  this job before assuming a user's "launcher crashes on Windows" report is
  unreproducible.

## Flet client crash forensics: cubeon/incident.py (2026-10-18) — INVARIANT
- **What a user's "crash" actually is on Linux.** The 2026-10-18 report arrived
  as a KDE screenshot: `~/.flet/client/flet-desktop-light-0.86.5/flet/flet has
  encountered a fatal error and was closed`, TWICE. That binary is the FLET
  CLIENT dying to a signal; two dialogs = attempt 1 (hardware GL) and the
  software-GL retry both died, after which the ladder gives up and the
  launcher vanishes silently. The ladder in `main.py __main__` is deliberate -
  pre-paint death → in-process retry with `use_software_gl` (safe: the engine
  never initialized), mid-session death → re-exec, `CUBEON_GPU_RESTARTS` caps
  both (see the Mesa/GPU-recovery sections above).
- **Root cause CONFIRMED (2026-10-18): Mesa 26.1.x — not Cubeon.** The crash
  is not exotic: the maintainer's own box (Arch, `mesa 1:26.1.6-1`, AMD
  Polaris/Ellesmere: RX 470/480/570/580/590) has a pile of flet-client core
  dumps, and `coredumpctl info` on the run whose `cubeon.log` simply stops
  reads:
  ```
  #0      libc.so.6                              (SEGV_ACCERR)
  #1-#7   libgallium-26.1.6-arch1.1.so
  #8-#9   libflutter_linux_gtk.so
  #10-#18 libgtk-3.so.0 → g_signal_emit → gtk_container_propagate_draw
  ```
  A Mesa driver fault during a GTK/Flutter paint — three layers below any
  Python. The 26.1 series is a known radeonsi/gallivm SIGSEGV regression
  train ("[radeonsi] SIGSEGV in gallivm during software fallback", 26.1.4
  relnotes; 26.1.8 closed the series and 26.2 carries the fixes), and
  `mesa 1:26.2.4-1` was already in `extra` on the crashing box: **the real
  fix is the Mesa update.** The crash record now prints `gallium=<lib>`, so
  `gallium=libgallium-26.1.6-…` answers "is this the known Mesa bug?" in one
  grep of a user's log.
- **The retry ladder therefore uses TWO rasterizers.** The crash is in the
  LLVM JIT path that llvmpipe SHARES with radeonsi, which is why the
  software-GL retry could never be expected to save the session (it never
  did — that is where the old "both hw AND llvmpipe" observation came from,
  recorded here long before anyone had a backtrace for it).
  `incident.driver_for_attempt()`: retry 1 → `GALLIUM_DRIVER=llvmpipe`,
  retry 2 (the last one) → `softpipe`, Mesa's reference C rasterizer with NO
  JIT — a genuinely different code path. softpipe is slow, hence final
  attempt only, and it is safe from the wedge watchdog by design: that
  detector requires its GL-frame-timeout lines in a BURST (< 4 s apart)
  precisely so a merely SLOW client is never killed.
- **Never hardcode the retry driver in main.py.** The attempt count is
  `max(_retries, CUBEON_GPU_RESTARTS)` — a re-exec'd mid-session restart is a
  FRESH process (`_retries == 0`) and must still escalate to softpipe on its
  second try. Regression: `tools/test_incident.py`.
- **The gap that made it undiagnosable, now closed:**
    * EVERY crash message was a `print()` to stdout. A user launching Cubeon
      from a desktop menu has no console, so there was nothing to send us.
    * `setup_logging()` was reached ONLY from `main()` - the flet SESSION
      callback. A PRE-PAINT crash means `main()` never runs, so logging was
      never configured and `cubeon.log` stayed EMPTY. `__main__` now calls it
      before `_session_loop()` (idempotent; `main()`'s later call is a no-op).
    * `_session_loop` calls `incident.record_session_end(kind, exit_code,
      ui_painted, tail)` for EVERY session end - INFO for a clean close (so
      "the log just stops here" is distinguishable from "the user closed it"),
      WARNING for a crash - and `incident.record_giving_up(...)` at ERROR in
      both exhausted branches. Support greps `flet session ended:` and
      `giving up after`.
    * `ClientOutputTail` keeps the last 25 non-ATK lines of the client's own
      stdout+stderr (the filter loop in `__main__` already streams it): that is
      where a Mesa/GTK/wayland library name or an engine assertion shows up.
      Consecutive repeats collapse to one line so an OpenGL-frame-timeout storm
      cannot push the earlier context out.
    * `client_binary()` names WHICH client bundle is being spawned, its stub
      size and whether the Flutter engine library is present. A PARTIAL unpack
      of `~/.flet/client/flet-desktop-*` (flet unpacks once, then trusts it
      forever) dies on every launch and looks identical to a driver crash in a
      report; it is also the one client-side fault that is ours to fix, so it
      has to be distinguishable by evidence rather than by a size guess.
- **`incident.wayland_x11_fallback(env)` is applied ONLY on a retry**, i.e.
  after the first attempt already crashed. The GTK/Wayland path is the other
  documented way the client dies, and "run it under XWayland" is the standard
  workaround. It returns `{}` unless the session is Wayland, `DISPLAY` exists
  (without XWayland, forcing x11 would fail the start outright), and the user
  has NOT set `GDK_BACKEND` themselves. Never apply it to a first attempt -
  native Wayland stays native for everyone it currently works for.
- **These helpers must be TOTAL** - never raise, and never report a signal
  death as clean: they run on the one path where the launcher is already
  dying, and they are the only evidence a crash report can contain.
  `describe_exit(None)` is "unobserved" and must never read as `clean`.
  Regression: `tools/test_incident.py` (74 checks, including the main.py
  wiring).

## Version management lives in ui/versions.py + cubeon/instances.py (2026-10-15)
- The Play tab's "manage my versions" surface was extracted out of `main()`'s
  4,000-line closure into two modules:
  - `cubeon/instances.py` — **pure data** (no Flet): `detect_loader`,
    `describe`/`list_installed` (id, base version, loader, nickname, mod count,
    folder, last-played), `instance_size_bytes`, `format_size`,
    `mark_played`/`last_played`/`relative_time`. Single source of truth for
    "what loader / how many mods / how big / when did I last play it". The size
    walk is the only expensive call — never do it on the event loop; the
    Instances manager runs it on a worker.
  - `ui/versions.py` — `VersionPicker` (Game-version button + dialog, rows
    grouped Installed/Available, loader/snapshot/release-date tags, "Latest
    release" shortcut), `InstanceCards` ("Jump back in" row), `InstancesManager`
    (per-install Play/Rename/Delete dialog). Pure view: callbacks + descriptor
    dicts in, no config/network/game-dir access.
- INVARIANTS (guarded by tools/test_version_ui.py + test_instances.py):
  - The picker filters its OWN `self._entries` snapshot and **never touches
    `version_dropdown`** (the live dropdown is main.py's alone).
  - Instance cards are built once and only restyled/refresh their imageless chip
    row — a rebuilt `ft.Image` re-sends its base64 payload (see
    test_version_art_cache.py). Cards stay width=210 with a one-default-str
    `on_click` (`lambda e, k=vid: on_select(k)`); that shape is how
    test_version_art_cache finds them.
  - `main.py` keeps the `ft.Dropdown` as the source of truth; `refresh_version_list`
    feeds the picker richer entry dicts and mirrors the plain option text.
  - `on_rename_instance`/`on_delete_instance` take an optional `vid=` so the
    manager can target any instance (not just the selected one).
- Last-played is a tiny `CUBEON_HOME/instance_play.json` sidecar written at
  launch (`instance_info.mark_played`) — deliberately NOT config.json, which is
  the most-written file in the launcher.

## Crash text must never promise a fix (2026-10-15) — INVARIANT
- User report: "when the game crashes cubeon says game crashed, cubeon doctor
  fixed it, run it again - but it isn't actually fixed." The culprit was
  `main.py::_explain_exit`'s KnotClient/KnotServer branch, which returned
  *"Crashed: this version's config was incomplete... Cubeon repaired it. Press
  Play again."*
- **That claim was false by construction.** The client.json repair
  (`launch._sanitize_client_json` + `launch._restore_emptied_arguments`) runs in
  `build_launch_command` BEFORE every spawn, so by the time a KnotClient crash
  is shown the repair had already run and did not help. The message sent users
  into an infinite relaunch loop on a broken install.
- The branch now says: *"Crashed: Fabric couldn't start - this version's files
  look incomplete. If pressing Play again still crashes, reinstall this version
  from the Play tab."* No "repaired"/"fixed" wording. Guard:
  `tools/test_ui_smoke.py` §4 ("does not claim a fix that never happened" +
  "names the real recovery step").
- Rule for any future crash/status text: only claim a fix when THIS code path
  actually performed and verified one. Repairs that run pre-spawn must not be
  advertised as fixes for a crash that already happened.

## Crash text: a Java blame needs a Java-SPECIFIC line (2026-10-18) — INVARIANT
- User report: *"it says crashed: no java found bla bla… minecraft crashes with
  this error even if java fine bcz it ran minecraft in first place."* The game
  had started a JVM, so "Java not found" was provably false.
- `main.py::_explain_exit`'s Java branch read
  `if "cannot run program" in low or "no such file or directory" in low and "java" in low:`
  — `and` binds tighter than `or`, so it was `A or (B and C)`: **any**
  `Cannot run program` line blamed Java. And `B and C` is true on essentially
  every launch, because the launch command itself (JVM path
  `/usr/lib/jvm/java-21-openjdk/...`) is part of the output the launcher reads —
  so the word "java" is always present, and any stray
  `No such file or directory` (mod config, shader include, missing native, a mod
  shelling out to `xdg-open`) was reported as a missing JDK, discarding the real
  error line.
- **Rule:** match Java evidence per **LINE**, never against the whole log. The
  JVM path in the launch command must not count as evidence. Accepted evidence:
  `Cannot run program "java"`/`"javaw"`, `Could not create the Java Virtual
  Machine`, or `No such file or directory` on a line that also names Java.
- A rejected JVM option (`Unrecognized option` + the JVM's own
  `Could not create the Java Virtual Machine`) gets its own message pointing at
  the JVM arguments, not at installing Java.
- Otherwise fall through to the real error line; when there is genuinely
  nothing, say so and point at Fix problems — never guess "check that Java
  matches". Regression: `tools/test_ui_smoke.py` §4 (the JVM-path + unrelated
  missing-file log shape, plus the genuine java/javaw/bad-option cases).

## Windows: EVERY child spawn must hide its console (2026-10-15) — INVARIANT
- User report: "it opens random cmd when starting or closing or doing
  anything - cmd opens and closes." Cubeon.exe is a --windowed app, but every
  child process spawned without CREATE_NO_WINDOW + STARTF_USESHOWWINDOW(SW_HIDE)
  got its own console window on Windows: the `java -version` probes (one PER
  candidate Java per Play click), mll's FABRIC installer jar (its quilt module
  hides the window; fabric missed it upstream), `tzutil`, the local server,
  the relaunch fallback and the flet.exe client.
- `cubeon/winproc.py` is the ONLY way to spawn: `hidden(**extra)` returns the
  subprocess kwargs (OR-ing a caller's creationflags, so server.py's
  CREATE_NEW_PROCESS_GROUP survives) and `patch_mll()` swaps a hiding shim
  into minecraft_launcher_lib.fabric's subprocess module (idempotent, no-op
  off Windows). The game itself already had CREATE_NO_WINDOW in launch.py.
- Rules: any NEW subprocess call reachable on Windows must pass `**hidden()`
  (or go through patch_mll's shim). `startupinfo=None` in a probe is the bug
  signature - do not write it again. mll modules other than fabric already
  use SUBPROCESS_STARTUP_INFO upstream.
- Guard: tools/test_ui_smoke.py "Windows must never flash a console window"
  (helper exists, probe fixed, patch_mll called, jre/seasonal/server/main all
  wired). winproc's own semantics are covered in the 2026-10-15 note.

## Managed Java verifies by RUNNING; first launch runs the FULL doctor (2026-10-15)
- User reports: (a) "make the java install much safer", (b) "fps mods doesn't
  install correctly - fresh install + Java, first launch gave an error, only
  the Mods tab's Fix problems fixed it".
- (a) `cubeon/jre.py::_probe_version` runs the binary and reads its major.
  `install_jre` probes the STAGED binary before anything moves into place and
  the INSTALLED binary after the move; either failure removes the runtime and
  raises a user-worded JreError. This closes the truncated-extract hole (a
  sha256-valid download can still unpack short - bin/java present,
  lib/modules missing - which ate a real JDK 25 on the dev box). The swap
  moves the old runtime to `<major>.old` and only deletes it after the new
  one is in place, so a failed swap can never leave NO runtime.
- (b) `cubeon/launch.py::launch_game` runs the FULL online doctor once per
  (mc_version, loader) before the first spawn: the pre-spawn offline pass
  skips the dependency + loader/version checks, which is exactly what a fresh
  profile needs. The marker lives in local_cache namespace
  "first_launch_doctor" (30-day max_age); the pre-spawn offline doctor still
  runs EVERY launch. Do not "optimise" the first-launch pass away - it is the
  fix for the user's exact complaint.
- Guards: tools/test_launch_fixes.py §14 probe/marker blocks (113 checks) and
  the "first launch" block pinning online-once-then-offline.

## FPS boost lives in the PLAY menu; OFF RESTORES vanilla (2026-10-15) — INVARIANT
- The user request: the Settings "Max FPS mode" toggle "doesn't do much if the
  install is already installed", and the boost "nerfs shadows and textures".
  Both true: the old OFF just stopped FUTURE launches from re-applying, so the
  fast values stayed baked in options.txt forever; and the boost's keys
  (graphicsPreset fast, ao:false, entityShadows:false, particles:2 …) ARE the
  look - that is where its FPS comes from. It cannot be "3x FPS with zero
  visual change" - the honest contract is ON = fast, OFF = vanilla look
  restored.
- `cubeon/config.py`: the key is now `fps_boost_enabled` (default True);
  `load_config` MIGRATES `max_fps_enabled` so a user's choice carries over.
- The toggle is a `ft.Switch` in the PLAY card under "Mod loader"
  (`fps_boost_switch` in main.py, defined BEFORE `play_tab = ft.Column(` —
  it is referenced in that literal; defining it after was an
  UnboundLocalError caught by test_ui_smoke). The Settings row is GONE.
- `cubeon/game_options.py`: `restore_vanilla_look()` rewrites the SAME keys to
  Minecraft's own defaults (graphicsPreset "fancy", particles 0, ao true,
  entityShadows true, entityDistanceScaling 1.0, biomeBlendRadius 2,
  syncChunkWrites true, smoothLighting true) - only keys the file already has.
  `apply_max_fps()` is unchanged (do NOT weaken it; it is the "3x fps" the
  user wants). `cubeon/launch.py` calls restore when the boost is off, so an
  install that ran boosted actually looks vanilla again on the next launch.
- renderDistance / simulationDistance / mipmap / clouds: **changed 2026-10-18**.
  They are no longer left alone - FPS boost (ON by default) now lowers them
  (renderDistance 6, simulationDistance 5, mipmapLevels 2, renderClouds
  "fast") and `restore_vanilla_look()` puts them back (12 / 12 / 4 / "true").
  Reason: a side-by-side run against FastClient on the same box showed the
  frame-rate gap WAS those keys - the GPU sat idle (0-76% busy) while both
  games were Java-bound, and renderDistance 8 meshes ~70% more chunks than 6.
  FastClient's own options.txt sets the same speed-only keys AND distance 6.
  Leaves/water quality are still never touched (no measurable cost).
- Guards: tools/test_perf_mods.py §11 (restore values incl. the distance
  levers, idempotence, round trip, no invented keys), tools/test_ui_smoke.py
  "FPS boost lives in the PLAY menu" block (Settings row gone,
  switch-before-play_tab ordering, launch.py restore call, config migration).

### Do NOT ship a `sodium-options.json` as "the FPS boost config" (audited 2026-10-18)
- Sodium's compiled-in defaults **are already the performance choice**: every
  culling toggle on, `animate_only_visible_textures` on, `pixel_filtering_mode
  NEAREST` (the fast one), `quad_splitting_mode SAFE`, advanced staging buffers
  on, `cpu_render_ahead_limit 3`, memory tracing off. A brand-new install writes
  exactly that file, so shipping a copy changes nothing for anyone on stock
  settings. (Verified by `javap` on `SodiumOptions$QualitySettings` /
  `$PerformanceSettings` / `$AdvancedSettings` / `$DebugSettings` in
  `sodium-fabric-0.8.12+mc26.1.2.jar` — the defaults live in the no-arg
  constructors, and GSON also calls those, so a partial file's missing keys keep
  the default rather than zeroing.)
- `chunk_builder_threads` is the one key that usually differs, and it is
  **machine-specific**: `0` means Auto and `ChunkBuilder.getThreadCount()`
  resolves it to `clamp(max(cores/3, cores-6), 1, 10)`; any non-zero value is
  `min(value, cores)`. It is not a "more is better" slider (Sodium's own
  tooltip: more threads can hurt frame times). Hardcoding it is wrong in both
  directions — a 12-core box carrying `2` runs a third of the 6 Sodium would
  pick (real user case, 2026-10-18).
- So the module-map rule (2026-10-18): FPS boost never ships or creates a
  `sodium-options.json`. It does REPAIR one that already exists — see the next
  bullet — and if a Sodium-side toggle is ever wanted beyond that, the levers
  that actually cost frames are in **Sodium Extra**
  (`sodium-extra-options.json`: particles, biome/sky colours, block+portal
  animations, toasts), not in Sodium's own config.
- **`perf_mods.apply_max_fps_sodium()` rewrites an existing file every boosted
  launch (2026-10-18, user-requested).** `cubeon/launch.py` calls it directly
  under the same `fps_boost_enabled` check as the options.txt rewrite. It puts
  the performance keys that are ALREADY in `<MINECRAFT_DIR>/config/
  sodium-options.json` back to the defaults listed above
  (`SODIUM_MAX_FPS_OPTIONS`): hidden_fluid_culling true, improved_fluid_shaping
  false, chunk_builder_threads **0 (Auto — never a hardcoded thread count, see
  the rest-of-the-file audit above)**, chunk_build_defer_mode ALWAYS,
  animate_only_visible_textures / use_entity_culling / use_fog_occlusion /
  use_block_face_culling / use_no_error_g_l_context true, quad_splitting_mode
  SAFE, use_advanced_staging_buffers true, cpu_render_ahead_limit 3,
  terrain_sorting_enabled true, enable_memory_tracing false. Why it exists: a
  file left behind by an older Cubeon/Sodium, or by an "FPS guide" that told the
  player to switch fog occlusion off, sat there forever and kept the renderer
  doing work it did not have to. Deliberately NOT touched, because they are taste
  rather than frame cost: `pixel_filtering_mode` (NEAREST is the default, LINEAR
  is a look), `use_closest_point_entity_sort` (correct translucent sorting),
  `notifications.*`.
  - Missing file → nothing is created (Sodium's compiled defaults are these very
    values, so the outcome is identical, and writing a file whose schema we only
    know for the generations we have audited would be the risky half of the
    trade). Keys are matched per section, so a 0.4.x (1.20) config only gets the
    names both generations share — it is never given `chunk_build_defer_mode` or
    `quad_splitting_mode`. Atomic, idempotent, never raises.
  - There is no FPS-boost-OFF counterpart: unlike options.txt there is nothing
    "vanilla" to write back, so OFF simply stops enforcing it.
  - Guard: `tools/test_perf_mods.py` §12 (drift repair, taste preserved, unknown
    sections preserved, legacy schema, 0/1-vs-boolean, missing/corrupt file, and
    the launch-path wiring).

## The in-game mod is CHAT-ONLY (2026-10-14) — INVARIANT
- User request: "remove the whole friends stuff from the Cubeon client, the
  connection and stuff, but add a chat area with friends where we can chat and
  show same chat as the launcher."
- `CubeonClientScreen` is now a chat screen only: a friends picker (rows with
  presence, double-click-to-open idiom), a read-only prose transcript (incoming
  WHITE / outgoing AQUA, newest at the bottom, 24-label pool) and a composer
  (EditBox + Send, `CHAT_INPUT_MAX` 1000). No tabs, no requests, no account
  view, no Play/Invite/Join, no session banner, no worldgate, no Sync, no
  whitelist, no remove/add. The conversation is THE SAME store as the launcher's
  Chat tab: both read `FriendsService` (mod via `/chat`+`/dm` on the localhost
  bridge, launcher in-process), so they stay in sync live.
- `Bridge.java` lost: the `Session` record, `parseSession`,
  `parseRequests`, `SyncReport` + the `/sync` poll stream, the `/status` poll
  (with `statusMisses`), and the actions `invite/join/addFriend/acceptRequest/
  declineRequest/removeFriend/setWhitelisted/startSync/downloadMods/closeSync/
  askToJoin/cancelSession/setWorldGate/sendJoinPassword/retrySession`.
  `Snapshot` shrank to
  `(launcherUp, connected, available, you, youUid, friends, problem, modStamp,
  youMinecraftUsername)` — `requestsIn/requestsOut` and the session are GONE.
  `sendChat` (`POST /dm`) is the mod's only action. SelfTest dropped
  `sessionParsing` (121 checks now, was 164).
- Kept: the corner icon + both menu mixins (no `canInvite` parameter any more),
  toast notices (`[Cubeon]` chat HUD + screen status line), `[Cubeon]`
  tab-list tag, `WorldPlayers`, the stale-jar tripwire, `/players` stream.
  `BadgeNames` is untouched.
- Chat reopen-dupe rule still applies in-game: the mod's `refreshChat()`
  merge/cursor logic is unchanged — do not "simplify" it.
- Both jars were REBUILT and verified this date (1.20-1.21 gradle+loom; 26 via
  javac — which required re-downloading Temurin JDK 25 into `~/jdks` (the old
  unpack was truncated) and fetching the 26.1.2 client jar into
  `~/.cubeon_minecraft/versions/26.1.2/`, plus adding `jspecify` and
  `fastutil` to `LIB_PREFIXES` in tools/build_mod_jars.py so javac can read
  Mojang's annotated classes).
- NOT verified in-game (no GUI session): the picker/transcript layout and
  Send need one real launch to confirm visually.
- **A worker-file write guard false-positives on Bridge.java** (the local API
  token loader contains the JSON key "token"; `/worldgate` used to contain a
  "password" key). If the guard fires again, edit via an approved shell script,
  never by re-encoding content to dodge the scan.

## The in-game MOD MENU + module framework are GONE (2026-10-05) — INVARIANT
- User request: remove the in-game Cubeon Client's "mods area and functionality".
  Deleted the whole module framework and its UI from the Java mod:
  `modules/` (`Module`, `Modules`, `ModuleConfig`, `ModuleCategory`, `HudText`,
  `HudState`, `GameOptions`, `OptionsAccessor`), `ModuleMenuScreen.java`,
  `MenuPaint.java`, `MenuPainter.java`, `keys/MenuKey.java`,
  `mixin/PlayerTickMixin.java`, and per-overlay `MenuPaintImpl.java`,
  `mixin/HudMixin.java`, `mixin/MenuPaintMixin.java`.
- Kept: the Friends screen (`CubeonClientScreen`, `CornerIcon`, the pause-menu
  Friends icon), the launcher bridge, and the `[Cubeon]` tab-list tag.
- `cubeon-client.mixins.json` now registers only `PauseScreenMixin`,
  `PlayerTabOverlayMixin`, `TitleScreenMixin`. The PauseScreen mixin no longer
  adds a "Mods" button. `CubeonClient` no longer loads `cubeon-modules.json`.
- Build lists updated in lockstep: `tools/build_mod_jars.py`
  (`REQUIRED_ENTRIES`, and `lwjgl-glfw` dropped from `LIB_PREFIXES`),
  `tools/test_mod_compile.py` (`MOD_SOURCES`), `tools/test_mod_bridge.py`
  (`SOURCES`), `mod/tools/SelfTest.java` (module sections removed),
  `mod/build.gradle` (glfw `compileOnly` removed).
- **The 1.20-1.21 jar was rebuilt** (`tools/build_mod_jars.py 1.20-1.21`) so the
  removal actually reaches Minecraft. **The 26 jar was NOT rebuilt** on
  2026-10-05 (its javac path failed and the Gradle fallback stalled) - a 26.x
  player still gets the old mod menu until it is. Rebuild it on a box with the
  bracket's JDK 25 and network.
- The old sections below ("The mod menu PAINTS itself", "Mod menu + module
  framework") describe the REMOVED code. Kept for history only; do not
  resurrect it without the user asking.

## Windows seasonal colours + installer + close-to-background (2026-10-05) — INVARIANTS
- **Seasonal PALETTE never showed on Windows (weather/pet did).** Root cause:
  `cubeon/color_templates.py` loads every palette with a DYNAMIC
  `importlib.import_module("templates.color_<key>")`, and the Windows builders
  relied on `--collect-submodules templates`, which collects NOTHING on the
  Windows build interpreter (WinPython runs isolated `_pth`, repo off sys.path)
  because collect_submodules runs while the spec is written, before Analysis
  adds `pathex`. The palette import failed, `cubeon/__init__` swallowed it
  (a `print` that is a no-op in a `--windowed` exe), and it fell back to green.
  **Fix: every Windows builder names each palette with `--hidden-import
  templates.color_*` + `--paths ROOT`** (`TEMPLATE_HIDDEN_IMPORTS` in
  `packaging/build_windows.py`, mirrored in `build_windows_single.py` and
  `build_public_windows.py`). Guard: `tools/test_mega_smoke.py` §3f-bis. Adding
  a palette = add it in `color_templates.py` AND those tuples. Do NOT go back to
  `--collect-submodules templates` for Windows.
- **Installer updates no longer wipe the folder.** `packaging/Cubeon.nsi` did
  `RMDir /r "$INSTDIR"` then `File /r`, i.e. delete+rewrite every file (double
  I/O + double AV scan) — the reported slow "deleting" step. Now it copies over
  the top with `SetOverwrite ifdiff` (unchanged big files are skipped) and clears
  only the small stale-prone `_internal\templates` path. Added `OldInstDir`
  tracking, `/SD IDOK` on the running-app prompt (silent installs), an uninstall
  guard (only deletes a folder containing our uninstaller+exe), and richer
  Programs-and-Features keys (`EstimatedSize` computed in
  `build_windows_installer.py`, `InstallLocation`, `QuietUninstallString`,
  `URLInfoAbout`).
- **Close-to-background: `page.on_disconnect` NEVER fires — do not build on
  it.** flet's `Session.disconnect()` has zero callers in 0.86.x AND 1.0.3, so
  no session ever dispatches it; when the desktop client dies,
  `session.close()` dispatches **`page.on_close`** instead. `main()` therefore
  wires ONE handler to `page.on_close` and `page.on_disconnect` through a
  `setattr` loop (harmless if one never arrives). On the window level,
  KDE/Windows deliver `WindowEventType.HIDE`, not `close`, on a real X-button
  close, so `hide` must be treated as terminal too. Guards:
  `tools/test_ui_smoke.py` (wiring + watchdog) and
  `tools/test_wedge_watchdog.py`.
- **The actual "still running in the background" bug was a SELF-DEADLOCK in
  Discord RPC, not a missing event.** `cubeon/discord_rpc.py` `close()` held a
  non-reentrant `threading.Lock` while `clear()` → `_memoize_and_send()`
  re-took it: flet's event loop froze inside `_on_window_event`, `ft.run()`
  never returned, the client stayed a zombie, and the process lived on with no
  window (identical on Windows). **`self._lock` must stay a `RLock`, and
  `close()` must also `self._stop.set()`** or the retry loop keeps its thread
  alive. Guard: `tools/test_ui_smoke.py` "real `DiscordPresence.close()`
  no-deadlock".
- **Every activity carries the website button (2026-10-18).** `SITE_BUTTONS`
  (label "Cubeon website", `https://cubeon.ylet.online`) is the DEFAULT of
  `DiscordPresence.set_activity()`, so all three call sites in main.py get it
  without passing anything; a caller wanting a bare card passes `buttons=[]`.
  The URL is the SITE, not `updater.DOWNLOAD_URL`'s `/download` page — the
  button says "website" and the launcher already contains the download — and
  `tools/test_ui_smoke.py` pins both to one host so they cannot drift.
- **Nothing may block the flet event loop from a window/page event.**
  `_on_window_event` only saves geometry, `_kill_flet_client()`, and arms the
  watchdog — RPC clear/close and `friends_service.stop` moved to the bounded
  session-end path (`_do_session_end_cleanup`, daemon thread, `join(2.0)`).
- **The watchdog owns the process once the window is gone:**
  `_arm_window_gone_exit(reason, delay)` → `_window_gone_finish()` (delay 1.0
  for close, 2.0 for hide) → honors `_relaunch["request"]` via
  `_relaunch_fresh_process()` (Settings > Seasonal "Restart to apply" must
  survive a close) → `_terminate_flet_clients()` → `os._exit(0)`.
  `_session_loop` sets `_window_gone["ft_returned"] = True` the instant
  `ft.run()` returns and resets it + any stale timer before the next session,
  so the watchdog never fires after a clean return or a legitimate relaunch.
  `_terminate_flet_clients()` iterates `_live_flet_clients()` (two-factor
  match, skips zombies) and must never raise. Gated on `ui_painted_ok` so a
  pre-paint GPU crash still goes through the software-GL retry ladder. Do not
  remove the hard-exit without a Windows test.
- **Linux ships the PINNED flet 0.86.x** (`requirements.txt` pins
  `flet>=0.86,<0.87`); the system python3.14 has drifted to flet 1.0.3 — never
  build with it. Build with
  `PATH=$PWD/.venv-build/bin:$PATH bash packaging/build_appimage.sh` then
  `… python packaging/build_linux_installers.py` (the venv lives at
  `.venv-build` in this checkout; the older notes say `$HOME/cubeon-venv`,
  which is simply not present any more — check, don't trust the path). ORDER:
  `build_appimage.sh` does `mv dist/Cubeon/*` (clobbers the Windows onedir), so
  build the Windows installer FIRST.
- **Verifying a Linux build without a GPU, and without trusting the source
  tree: `bash tools/verify_linux_artifacts.sh`** (run it BEFORE uploading). It
  checks the artifacts themselves — jar counts, no stale keyhud jars, the
  bundled flet client, the deb control's version, and the frozen bytecode
  marker — and exits non-zero on failure. The marker constant inside it must be
  **bumped every release** to a string that landed in *that* cycle, or the
  staleness check silently stops meaning anything (a negative control with a
  bogus marker is the way to confirm it still fails).
  `xvfb-run -a -s "-screen 0 1280x800x24" ./dist/Cubeon-x86_64.AppImage`
  then gets the app as far as creating `~/.cubeon_launcher`, its identity and
  `cubeon.log`, before it dies on `Timed out waiting for OpenGL frame … (have
  1x1)` — that is the headless box having no GPU, **not** a packaging fault, and
  it is the same reason CI skips `test_wedge_watchdog.py`. `LIBGL_ALWAYS_SOFTWARE=1`
  + `GALLIUM_DRIVER=llvmpipe` does NOT rescue it. The useful signal is the log
  line `cubeon.updater: update check: up to date (vX.Y.Z)`, which proves the
  FROZEN `APP_VERSION`; do not read "no window" as "bad build".
- **The app's own modules are inside the executable's archive**, not files on
  disk: `find … -name 'osnotify*'` finds NOTHING in a correct onedir build, while
  `grep -a osnotify dist/AppDir/usr/bin/Cubeon` finds it (the module name is in
  the CArchive TOC). Check data like `assets/jars/*` on disk, code by grepping
  the executable.
- **To read the frozen CODE (the only proof the build is not stale)**: the PYZ
  member is `PYZ.pyz` (NOT `PYZ-00.pyz` — opening that name errors out), so
  `printf 'O PYZ.pyz\nx cubeon.csl\nout\nQ\n' | pyi-archive_viewer
  dist/AppDir/usr/bin/Cubeon` then `marshal.loads(open("out","rb").read())` and
  walk `co_consts`. Data files prove the ASSETS are current; this proves the
  CODE is. A stale build ships old code silently.
- **A clean substitute for reading the frozen version**: `ar p <deb>
  control.tar.gz | tar -xzO control` (member is `control`, NOT `./control`;
  `dpkg-deb` is often absent — the build script avoids it on purpose so Arch
  works). Expect `Version:` = `cubeon/updater.py`'s `APP_VERSION`. Once the deb
  is rebuilt its sha256 CHANGES even though its size barely moves, so re-hash
  after every build before uploading.
- **Release v1.0.0 was clobbered 2026-10-06 with builds containing all of the
  above**: `Cubeon-Windows-x64-Setup.exe`, `Cubeon-x86_64.AppImage`,
  `Cubeon-Linux-x86_64-Setup.sh`, and `cubeon_1.0.0_amd64.deb` (built as
  `cubeon_1.0.3_amd64.deb`, uploaded under the name the worker expects — see
  `worker/cubeon-downloads.js`). Every asset was sha256-verified against
  `gh api …/releases/tags/v1.0.0`. The close fix was then re-verified on the
  shipped AppImage (exit in 1.0 s, zero survivors).
- **Release v1.0.0 was CLOBBERED AGAIN 2026-10-15 and v1.1.2 was created**
  (both carry the 1.1.2 builds; the stale 1.0.0/1.0.4 debs were deleted from
  v1.0.0). v1.0.0 asset names must stay exactly
  `Cubeon-Windows-x64-Setup.exe`, `Cubeon-Windows-x64.zip`,
  `Cubeon-x86_64.AppImage`, `cubeon_1.0.0_amd64.deb`,
  `Cubeon-Linux-x86_64-Setup.sh` - the deb is uploaded under the 1.0.0 name
  whatever it was built as, because `worker/cubeon-downloads.js` /linuxdeb
  matches by prefix+suffix. **The Windows NSIS step must run under the LINUX
  python3, never wine's python** (from inside wine, host wine is not on PATH,
  so `build_windows_installer.py` cannot find wine; the script execs wine
  itself and must run with the Linux python3).
  `build_windows_installer.py` prefers native makensis (CI has no wine) and
  probes the electron-builder and wine-prefix makensis.exe copies under wine
  otherwise.
- **All 217 commits are authored as Shadow-457** (3 author name variants, all
  emails map to the same GitHub account; 3 commits carry a Codebuff
  co-author trailer, kept deliberately). New commits need an explicit author
  + committer identity because this environment injects a different
  `user.name` by default (see the 2026-10-14 note).

Last updated: 2026-10-13 (site = `web/` on Vercel at cubeon.vercel.app: landing /
download / help + legal pages sharing web/assets/site.css + site.js; the landing
page was rebuilt onto the full design system on this date — see the site bullets
further down. The download count is ONE shared Abacus total read by site.js; the
old API-function/CI-JSON plumbing is gone and a test keeps it gone. Same day:
Settings → Import reworked to per-instance "Import to" + search with duplicate
detection, and the "launcher reopens after close" family fixed — exit-0 always
clean + wedge burst-gap; scan now skips non-Minecraft jars/zips; version lists
show friendly "X.Y.Z (Loader)" labels sorted newest-first; the site's
"Free launcher · Windows & Linux" eyebrow removed; see those bullets.) Also
2026-10-13: a vanilla install can GAIN a loader (the Play-tab toggle now arms
a pending install instead of dead-ending — see the Play-button state-machine
bullet), mods can never be imported to a vanilla target (see the import
bullet), and playful error pages were added (403/429/500/502/503). If a
fact here contradicts the code, the code wins — but fix this file too. Durable
facts belong HERE, not in diary notes.

## A mixin must name a method its OWN target DECLARES (2026-09-27) — INVARIANT
- **Mixin resolves `@Inject(method=...)` against the methods the TARGET CLASS
  ITSELF declares. An inherited method is not found.** With `require = 0` that
  is a **silent no-op**, not a failure — the mixin loads, the game runs, and
  the feature simply never happens.
- This cost a whole build cycle: `MenuPaintMixin` was written as
  `@Mixin(ModuleMenuScreen.class)` injecting `render`, but `ModuleMenuScreen`
  only INHERITS `render` from `Screen`. The menu never painted — no panel, no
  text, just empty invisible buttons — while every test stayed green.
- **Fix, and the pattern for any inherited method:** target the class that
  DECLARES it and guard on the instance type —
  `@Mixin(Screen.class)` + `if (!((Object) this instanceof ModuleMenuScreen)) return;`
  Per bracket, because `render` is `Screen.render(GuiGraphics,…)` on 1.20-1.21
  and `Screen.extractRenderState(GuiGraphicsExtractor,…)` on 26.x.
- **Guard:** `tools/test_mod_compile.py` now parses every mixin in
  `MOD_SOURCES`, resolves its `@Mixin` target (including unqualified names and
  simple names — a mixin in `…client.mixin` imports its target from
  `…client`), and asserts each injected method is declared in that source.
  Verified it FAILS on the original bug and PASSES on the fix. The `@Mixin`
  regex is line-anchored so a javadoc explaining the bug is not mistaken for the
  annotation — that was a false positive the guard itself had first.
- Every other mixin here is fine *by construction*: their targets declare
  what they inject — `Gui.render`, `LocalPlayer.tick`, `PauseScreen.init`,
  `TitleScreen.init`, `PlayerTabOverlay.getNameForDisplay`,
  `Player.getDisplayName`. Check that list before adding another.


## The mod menu PAINTS itself — never use vanilla widgets for it (2026-09-27) — INVARIANT
- **A lesson paid for once: the first mod menu was built from vanilla
  `Button`/`EditBox` widgets and the user rejected it outright** — grey bevelled
  buttons, a ragged grid, reads as a Minecraft options screen. "Avoid custom
  drawing so one jar serves both brackets" is the WRONG reason to make
  something look bad. The menu now paints its panel, tabs and cards itself.
- **How it still ships one jar:** `MenuPaint` is a two-method interface
  (`fill`, `text`) with one tiny implementation per bracket (`MenuPaintImpl` in
  each `java-overlay-*`). That is the ONLY per-bracket part of the menu. All
  layout, colours, rounded corners and hover live in the shared `MenuPainter`,
  which builds every shape from plain rectangles.
- **`MenuPaintMixin` (per bracket, same FQN) is the paint hook** — 1.20-1.21
  injects `Screen.render(GuiGraphics, ...)`, 26.x injects
  `Screen.extractRenderState(GuiGraphicsExtractor, ...)`. Unavoidable: the two
  signatures are unrelated.
- **Opaque colours only.** 26.x's extractor has no alpha `fill`, so a
  translucent panel would render right on one bracket and as a solid block on
  the other. The palette is deliberately all-opaque so both look the same.
- **Clicks are still vanilla widgets** — invisible Buttons over each painted
  element — because `mouseClicked`'s signature changed in 26.x and widgets are
  the cross-era way to get input. The buttons draw NOTHING; `drawOverlay`
  paints over them.
- **Never hard-code the column count.** It is derived from the panel width;
  the first version fixed two 150px columns and left the toggles floating
  outside their cards. `MenuPainter.clip()` truncates card text with an
  ellipsis instead of letting it run past the card edge.


## Mod menu + module framework (2026-09-27) — INVARIANT
- **The mod menu is `ModuleMenuScreen`, opened by the "Mods" button that
  `PauseScreenMixin` drops in next to the Friends icon.** No keybind: that
  needs `fabric-key-binding-api` and this mod ships **no Fabric API modules**
  (loader only). A keybind is a one-line change IF the user accepts the dep.
- **The whole framework is Minecraft-FREE and unit-tested on a bare JDK**:
  `modules/Module`, `ModuleConfig`, `ModuleCategory`, `HudText` import nothing
  from Minecraft. That is the point — it is what makes the config format, the
  clamping and the category filtering testable at all. Guards:
  `tools/test_mod_bridge.py` (SelfTest moduleFramework/hudTextLines, 164
  checks) and `tools/test_mod_compile.py` (compiles it all).
- **A module that throws in `apply()` reports itself OFF, not on** — a toggle
  that lies is worse than no toggle. Pinned in SelfTest.
- **Option modules go through `Options` ACCESSORS (`gamma()`, `fov()`,
  `bobView()`), never the public fields.** 26.x turned the fields into
  accessors; the field spelling compiles on 1.20-1.21 and fails 26. All three
  were javap'd in both real jars. This is the single most important rule for
  adding a module.
- **`player.input` is NOT cross-era** — 1.20.1 has a public
  `input.forwardImpulse` field, 26.x has `ClientInput.hasForwardImpulse()`.
  Auto-sprint therefore reads `options.keyUp.isDown()`. Do not "fix" it to use
  the input. The real 26 build caught this; the stub would not have.
- **Only the HUD DRAW is per-bracket** (`HudMixin`, same FQN in both
  `java-overlay-*` dirs, exactly as `CornerIcon` does): 1.20-1.21 injects
  `Gui.render(GuiGraphics, float)`, 26.x injects
  `Gui.extractRenderState(GuiGraphicsExtractor, DeltaTracker)`. Everything
  deciding *what* to draw is shared in `HudState`/`HudText`.
  `_check_mixin_wiring` now accepts overlay mixins and asserts a per-bracket
  one exists in BOTH overlays.
- Config lives at `<game>/config/cubeon-modules.json` via
  `FabricLoader.getConfigDir()`; writes are atomic (tmp file + move).
- **Not verified in-game.** The menu has never been opened, and HUD drawing is
  the one part that cannot be compile-checked against the stub. Both jars
  build, but a real launch is the proof.

## Tab-list `[Cubeon]` tag (2026-09-27) — INVARIANT
## Tab-list `[Cubeon]` tag (2026-09-27) — INVARIANT
- **Cubeon players are tagged in the TAB LIST only** — `TabListTag.decorate()`
  prepends a green `[Cubeon]` to each row. The nametag above a head is
  deliberately NOT tagged (see the badge-removal invariant below): the tab list
  is your own screen and nobody else's, so this is private; a floating nametag
  is on display to the whole server, which is why that one went. Guard in
  `tools/test_mod_compile.py::_check_mixin_wiring` asserts the nametag mixin
  stays unregistered.
- **The injection target is `PlayerTabOverlay.getNameForDisplay(PlayerInfo)`**
  and that choice is load-bearing. The tab list *renderer* is the most-reshaped
  thing between eras — 1.20-1.21 has `render(GuiGraphics,…)`, 26.x has
  `extractRenderState(GuiGraphicsExtractor,…)` — but `getNameForDisplay` is
  byte-identical in both (verified with `javap` against the real 1.20.1 and
  26.1.2 jars). One injection, both brackets. **If you retarget it, re-`javap`
  both jars first**; don't assume. The guard fails loudly if the method name
  changes.
- **Exact green, via `TextColor.fromRgb(0x83C13D)`**, not
  `ChatFormatting.GREEN` (a different colour, and all the old nametag badge
  could use on 1.20-1.21). `Style.withColor(TextColor)` and
  `TextColor.fromRgb(int)` are identical in both eras.
- **Only names the launcher can vouch for.** Reuses `BadgeNames` — you, your
  friends' Minecraft usernames, and the `/players` roster. A stranger running
  Cubeon is NOT tagged; the client cannot ask "is this an arbitrary name a
  Cubeon account". The name set is rebuilt only when `Bridge.revision()` /
  `playersRevision()` move (this runs per-row per-frame).
- **`_check_mixin_wiring()` in tools/test_mod_compile.py** is the guard for
  the three moving parts (mixin config ↔ `MOD_SOURCES` ↔
  `build_mod_jars.REQUIRED_ENTRIES`). An unregistered mixin silently does
  nothing in-game; a stale `REQUIRED_ENTRIES` entry fails a real build over a
  class that no longer exists. Verified it actually fails when broken.
- Requires `net/minecraft/client/gui/components/PlayerTabOverlay` and
- **`GameProfile`'s name accessor is resolved REFLECTIVELY**
  (`TabListTag.nameOf`), and this is the one sanctioned exception to the "only
  touch API that has not moved" rule. authlib 7 turned `GameProfile` into a
  **record**, renaming `getName()` -> `name()`. The rename lands *inside* the
  1.20-1.21 bracket's own range (1.20.1 ships authlib 6.0.54, 1.21.11 ships
  7.0.61), so a per-bracket overlay cannot save it — `brackets.json`'s
  "compile against the oldest" assumes the oldest's members still exist in the
  newest, which is **false** for `getName`. Caught by the real 26 build, not
  the stub. The 26 bracket is unaffected (7.0.63/10.0.77 are both records).

## Nametag badge REMOVED from the in-game mod (2026-09-27) — INVARIANT
  `net/minecraft/client/multiplayer/PlayerInfo` in the compile stub.

## Nametag badge REMOVED from the in-game mod (2026-09-27) — INVARIANT
- **The `[#]Shadow` nametag badge no longer exists.** It was drawn by a mixin
  on `Player.getDisplayName()` (per-visible-player-per-frame). Removed because
  it stamped the launcher onto other people's names in a game they did not
  choose to join. `Nametag.java` and `mixin/PlayerNameMixin.java` are deleted,
  `PlayerNameMixin` is out of `cubeon-client.mixins.json`, and the `badge()`
  method is gone from BOTH `CornerIcon` overlays (1.20-1.21 and 26).
- **`BadgeNames.java` is KEPT** (with its SelfTest coverage) even though nothing
  in the mod calls it now. It encodes a hard-won rule — a relay *handle* is not
  a Minecraft *username*, and matching on handles badged nobody. Reachable for
  any future non-name-marking use. Don't delete it as "dead code."
- **Two build lists must be kept in sync** or the mod silently stops
  building/shipping: `tools/test_mod_compile.py` `MOD_SOURCES` and
  `tools/build_mod_jars.py` `REQUIRED_ENTRIES`. Both referenced the deleted
  mixin; a stale entry there is a build failure, not a warning.
- `net/minecraft/.../Player` stays as a stub class in `test_mod_compile.py`'s
  API surface, but nothing references it now — a future mixin that needs it
  must justify its target surface there.

## Managed Java runtimes (2026-09-27) — INVARIANT
## Managed Java runtimes (2026-09-27) — INVARIANT
- **The launcher OFFERS to download Java; it never downloads unasked.**
  `cubeon/jre.py` fetches a Temurin **JRE** (not JDK — Minecraft never
  compiles) from the Adoptium API into `~/.cubeon_launcher/runtimes/<major>/`.
  `main.on_play_click` calls `jre.java_status(mc_version, cfg["java_path"])`
  and shows `_prompt_for_java` only when the machine has no Java new enough
  AND the version is not already installed. "Not now" (or dismissing the
  dialog) cancels the whole install — it must not fall through and install
  Minecraft anyway. Guard: tools/test_launch_fixes.py §14.
- **A managed runtime is a LAST resort, never a replacement.** They are
  appended to the candidate list in `launch.find_java_for_version` AFTER
  Settings → PATH → JAVA_HOME → the mll scan, so installing one can never
  change what a user who already has Java is running. §14 asserts that
  ordering by source position — do not "optimise" it into an earlier slot.
- **The Temurin archive nests the JRE one level deep**
  (`jdk-17.0.20.1+1-jre/bin/java`). `install_jre` MUST promote that inner
  home to `runtimes/<major>/`, because `managed_java()` looks for exactly
  `runtimes/<major>/bin/java`. This failed on the first real end-to-end run
  ("Java 17 did not install correctly" with a working JVM on disk) — the
  unpack was fine, the move was wrong. Don't "simplify" the staging back to
  moving the extraction root.
- **Atomic + verified:** sha256 from Adoptium is checked before unpacking;
  extraction goes to `<major>.part`, the home to `<major>.part.home`, and
  only then `os.replace` into place. Every failure path removes both temp
  dirs, so a crashed install can never leave something `managed_java()`
  reports as usable. Zip/tar members are checked for path escape (ZipSlip).
- **`SUPPORTED_MAJORS = (8, 16, 17, 21, 25)`** is deliberately exactly the set
  `required_java_major()` can return, so a version can never demand a Java
  the launcher cannot supply. §14 asserts that correspondence.

## Tray / background mode REMOVED (2026-09-27) — INVARIANT
- **There is no system tray and no background mode any more.** `cubeon/tray.py`
  is deleted, the `close_to_tray` setting is gone from `cubeon/config.py`, and
  `pystray` is no longer a dependency. A closed window now ENDS the process:
  `_session_loop` returns on `clean_close` instead of parking, and there is no
  reopen/park bookkeeping. Reason: on Flet 0.86/GTK the X button destroys the
  window/session and delivers no "close" event, so "background mode" could
  only ever mean a headless parked process. Guard: tools/test_ui_smoke.py
  "the tray is gone from the launcher entirely" (asserts `TrayController`,
  `_stop_tray_best_effort`, `_tray_runtime` and `pystray` are all absent from
  main.py). Do not reintroduce it without the user's say-so.
- **`_tray_runtime` is now `_session_runtime`** (same shape minus the tray
  keys): it still holds the process-scoped friends service/client and the
  gamepad watcher's `controller_*` slots, which outlive a single window
  session. Anything reading `app._tray_runtime` must be updated.
- **`CUBEON_TRAY_REOPEN` is now `CUBEON_RELAUNCH`**, set by
  `_relaunch_fresh_process()`; main() pops it to suppress the
  "orphaned Minecraft session" prompt after a deliberate relaunch.
- **`_reclaim_session_signals()` no longer sets an event.** It only counts
  presses in `_session_signal_hits`: the first ^C is swallowed so the bounded
  teardown finishes, the second is `os._exit(0)`. The reclaim itself is still
  load-bearing — flet never removes its own handler, so without it a ^C during
  `_ct.join` raises `RuntimeError('Event loop is closed')` from inside the
  handler (guard: tools/test_ui_smoke.py §4d).
- **`window.prevent_close` is still never set.** It makes the window
  unclosable on this Flet build. Since the tray is gone there is no reason to
  even consider it.

## Cancel outgoing requests / reopen dupes / geometry / no-source-leak (2026-09-23, 2nd pass) — INVARIANTS
- **Cancel pending outgoing requests**: one DECLINE frame serves both
  directions — worker `onDecline` MUST delete
  `(requester=? AND target=?) OR (requester=? AND target=?)` (receiver
  declining + requester cancelling). The Chat tab's outgoing row carries a
  "Cancel" pill wired to `service.decline`. Guard: tools/test_friends.py
  parity checks. **DEPLOYED 2026-09-24** (`npx wrangler deploy -c
  wrangler-friends.toml`, version 6514cc53-6a5c-4167-acac-9a2b63e4e58f) and
  verified live with a two-identity probe: add → cancel → both rosters clean
  → reconnect → still clean. Before that deploy the production Worker still
  ran the one-directional DELETE, which is why a cancelled request came back
  on the next launch. The client half is durable too:
  `FriendsClient.decline_request` drops the name from the cached roster and
  rewrites `friends_cache.json` (guard: tools/test_friends.py "durable
  cancel" block).
- **Chat reopen dupe**: `_hydrate_chat_store` MUST keep each message's `id`
  and `envelope` and skip entries already in the ring (id → envelope →
  (dir,text,ts) key, seeded from the room BEFORE the loaded rows, because
  `__init__` hydrates and callers may hydrate again). Dropping those fields
  was why every restart re-played history into the ring forever.
  Guards: tools/test_friends_service.py "S10" block (5 checks).
- **Window geometry**: the save tuple needs BOTH flet spellings
  (`resized`/`resize`/`move`/`moved`); `_reveal_window` re-asserts a saved
  left/top (and size) after the first frame, because the late native write
  that stomps centering also stomps a restore → "always top-left". Guards:
  tools/test_ui_smoke §4c geometry checks.
- **Shipped artifacts must contain NO readable source**: never `--add-data`
  `templates/` (palettes ship as bytecode via `--collect-submodules
  templates`; `apply_template()` imports them as modules, never by path) and
  never `mod/` (only `mod/brackets.json`). Windows/macOS/AppImage/deb all
  inherit this from their build scripts + Cubeon.spec.


## Post-session signals + friends-hub harness (2026-09-24) — INVARIANTS
- **flet leaves its SIGINT/SIGTERM handler installed forever.** After `ft.run`
  returns, `exit_gracefully` pokes a CLOSED asyncio loop, so any ^C raises
  `RuntimeError('Event loop is closed')` *from inside the signal handler* at
  whatever main-thread frame happens to be running (observed live 2026-09-24:
  it escaped `_ct.join(timeout=3.0)` as a `cubeon.fatal` CRITICAL right after
  "quit from tray"). `_reclaim_session_signals()` MUST run immediately after
  every `_run_flet_once()` return: first press sets the tray quit event
  (graceful exit through the normal loop), a second press is an immediate
  `os._exit(0)`. The parked wait therefore polls at 0.5s
  (`_reopen.wait(timeout=0.5)`) - the handler only SETS the event, so a long
  tick makes ^C feel dead; Tray Open still wakes instantly. The in-`ft.run`
  race is caught by its exact message. Guards: tools/test_ui_smoke §4d
  (source ordering + a real SIGINT/SIGTERM fired at the test process).
- **`worker/test-friends-rooms.mjs` is the RUNNABLE Hub harness**: it wires the
  real `Hub` to an in-memory `node:sqlite` and executes request/decline/CANCEL
  semantics (17 checks on that path), not just the source-parity greps in
  tools/test_friends.py. Run `node worker/test-friends-rooms.mjs`. It tracks
  the 8-digit uid format (`0000000X`) - if the worker's UID_WIDTH ever moves,
  this file must too or it fails at the first metadata assertion.

## Windows icon asset (2026-09-24) — INVARIANT
- **`assets/icon.ico` is GENERATED, never hand-drawn.** The source of truth is
  the transparent `assets/icon_512.png` (all PNG variants are already alpha
  clean: corners `(0,0,0,0)`). The checked-in `.ico` had been an OLDER,
  desaturated render baked onto an **opaque white plate** (every corner
  `(255,255,255,255)`, zero transparent pixels) — so every Windows surface
  (exe, Start Menu/Desktop shortcuts, taskbar, the Flet window icon) showed a
  white square around a washed-out cube while Linux/web showed the correct
  vivid transparent art. Rebuild it with:
  ```python
  from PIL import Image
  Image.open('assets/icon_512.png').convert('RGBA').save(
      'assets/icon.ico', format='ICO',
      sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
  ```
  and assert every layer's corner alpha is 0. Only the Windows artifacts embed
  the `.ico` (AppImage/deb/desktop entry use `icon_256.png`, already correct),
  so an icon change needs a Windows rebuild, not a Linux one.
- Every Windows build path passes `--icon=assets/icon.ico` (build_windows*.py)
  and `icon='assets/icon.ico'` in Cubeon.spec EXE — keep that wiring when the
  icon is regenerated, or Windows silently falls back to PyInstaller art.

## Loader installs must pass a VERIFIED Java (2026-09-24) — INVARIANTS
- **A mod-loader install EXECUTES a downloaded installer jar with Java**
  (mll 8.0: `if java is None: java = "java"`, then
  `subprocess.run([java, "-jar", installer, ...])`). Cubeon ships **no JRE**, so
  any call that omits `java=` dies on a keyless Windows box as
  `FileNotFoundError: [WinError 2] The system cannot find the file specified`
  printed raw under the download button (the 2026-09-24 Fabric report).
- `mod_loaders.install_mod_loader()` must therefore call
  **`mod_loaders.loader_java(mc_version, loader_id)` first** and pass `java=`
  (plus a pinned `loader_version=`) to `loader.install(...)`. `loader_java`
  reuses `launch.find_java_for_version()` — Settings path → system java →
  **JAVA_HOME** → every JVM, lowest sufficient major — and verifies the file
  exists **AND is new enough**: `find_java_for_version()`'s deliberate
  bare-`"java"` fallback (so a too-old Java surfaces Minecraft's own error at
  LAUNCH) is exactly what must never reach an installer. No Java ⇒ a readable
  "install Java N+ / set it in Settings" error BEFORE any download starts.
  Guard: tools/test_launch_fixes §8b (fake mll-8 loader; asserts java passes
  through and nothing runs without Java).
- **Java sources are 4, and a JDK FOLDER counts as a java path** (2026-09-26).
  The banner "Java N+ wasn't found" reached users who plainly had a JDK,
  because resolution read only Settings `java_path` → PATH → mll's scan.
  `JAVA_HOME` is now read by `launch._java_home_binaries()` (unquoted, both
  `java`/`java.exe`; a `JAVA_HOME` that isn't a dir is ignored) and
  `launch._normalize_java_path()` resolves a **directory** argument to its
  `bin/java`, so pasting the JDK folder into Settings works. Guards:
  tools/test_launch_fixes §8d/§8e.
- **There is EXACTLY ONE User-Agent string: `paths.user_agent(project)`.** (2026-09-26)
  Modrinth requires a uniquely-identifying UA (a library-only agent gets you
  blocked) and recommends contact info so they can reach us *before* blocking;
  their tiers are `name` → `user/name/ver` → `user/name/ver (contact)`. We emit
  the Best shape, e.g. `Cubeon/1.0.1 (modrinth; https://github.com/Shadow-457/Cubeon)`.
  It used to be a hardcoded literal in 8 places and had already drifted 3 ways,
  one pointing at a non-existent `github.com/cubeon`. Use
  `paths.modrinth_headers()` for api.modrinth.com AND cdn.modrinth.com (the
  mod-art downloaders share it), and `paths.user_agent(<subsystem>)` for
  everything else (Paper, CurseForge, Minekube, Mojang). **Never** hardcode a
  second one. Guard: tools/test_net.py §UA (asserts the shape, the real
  version, and greps all 9 modules for inline `User-Agent` literals).
- **`APP_VERSION` must stay a literal in `updater.py` — do not "tidy" it.**
  `packaging/build_windows_installer.py` regex-greps
  `APP_VERSION\s*=\s*"([^"]+)"` straight out of `cubeon/updater.py`'s SOURCE, so
  re-exporting it from `paths` (or reformatting the assignment) silently breaks
  the Windows installer. `paths.app_version()` therefore imports it lazily
  inside the function, because `paths` is the lowest layer and must not depend
  on a module that does network work — and that also keeps `requests` off the
  startup path.
- **`loader_java` must REJECT a too-old Java, not just a missing one.** Existence
  is not sufficient: an installer jar is EXECUTED, so a Java 8 on PATH (found
  via the deliberate fallback) used to sail through the old `os.path.isfile()`
  check and die on a raw `UnsupportedClassVersionError` instead of the
  actionable banner — i.e. the same banner, on a different code path. It now
  probes `java_major_version()` and appends "Only Java N was found, which is
  too old for <mc>." An **unprobeable** binary (major `None`) is still
  accepted, as before. Guard: tools/test_launch_fixes §8c.
- **The N in that message is the SELECTED MC version's requirement, not the
  user's Java** — `required_java_major()`: ≥26.1→25, ≥1.20.5→21, ≥1.18→17,
  ≥1.17→16, else 8. So one build legitimately shows "Java 17+" on 1.20.1 and
  "Java 21+" on 1.21.x. Not a detection bug; don't go hunting for it.
  Guard: tools/test_launch_fixes §8c last check.

## CurseForge modpacks in the Modpacks tab (2026-09-24) — INVARIANTS
- **Keyless CF access can RESOLVE a project but never LIST/SEARCH one.** Every
  alternative was probed live and is dead: curseforge.com (search page, RSS
  feed, sitemap) = Cloudflare 403; `api.curseforge.com/v1/mods/search` = 403
  without a key; api.cfwidget.com has no list/search endpoint; FTB API = 404;
  ATLauncher = 403; Prism's featured-instances feed = 404. **NEW CurseForge
  packs are therefore only reachable with a key** (free, from
  console.curseforge.com). Don't re-litigate this — it's measured, not assumed.
- **The key must be settable from the UI**: `modpacks.set_curseforge_api_key()`
  + `check_curseforge_api_key()` (both re-exported by `launcher_core`) back the
  "Add free CurseForge key" dialog in `ui/modpacks_tab.py`. Validation runs a
  REAL one-call search first so a wrong key is reported instead of silently
  degrading. `search_modpacks_curseforge()`'s cache key MUST keep its `keyed`
  flag — pasting/removing a key swaps providers, and without it the tab serves
  the other provider's cached page for up to a day.
- **cfwidget payload shapes**: `downloads` is `{"monthly":N,"total":N}` (read
  `["total"]` or every row shows 0), art is `thumbnail`, author is
  `members[0].username`, MC versions live in the grouped `versions{...}` map
  (loader tags like "Forge" appear there too and must be filtered). The curated
  fallback catalogue is `CURATED_CF_PROJECTS` — project IDs, not slugs, because
  slugs get renamed and 404 silently (that rotted the list from 12 to 7 live
  entries). Guard: tools/test_modpacks_cf_keyless.py.

## Chat dupes + latency / restart button / Windows packaging (2026-09-23) — INVARIANTS
- **Chat dupe rule**: a red "Couldn't send" bubble STAYS in `_pending`
  (`failed:True`); a late echo REPLACES it in place instead of appending.
  Dropping failed entries (the old code) re-appended the real line → one
  message rendered twice. Guard: `tools/test_chat_optimistic.py` (12 checks,
  registered in test_mega_smoke SUITES).
- **Chat cadence is adaptive**: `_poll_interval()` = 0.25s while `_pending`
  or within `_CONFIRM_WINDOW_S` after a send, 0.5s with a conversation open,
  else 1.5s. A tick is ~2ms in-process work - do NOT "optimize" back to a
  fixed slow poll; the old fixed 1.5s is why confirmations felt laggy.
- **Restart-to-apply / tray stop**: every execv-bound path (Settings >
  Restart, GPU-crash recovery, tray Open) must stop the tray through
  `_stop_tray_best_effort()` — NEVER a raw `_ctrl.stop()`: pystray/GLib
  teardown hangs (futex_wait on KDE) and used to sit between the Restart
  click and the execv, i.e. window closes, nothing relaunches. Guard:
  tools/test_ui_smoke §4c (also clicks the real button and asserts the
  relaunch request + window close).
## Windows packaging / Installer UI / Version 1.0.1 (2026-09-24) — INVARIANTS
- **Windows icon**: EVERY Windows build path passes `--icon=assets/icon.ico`
  (build_windows*.py and `icon='assets/icon.ico'` in Cubeon.spec EXE).
- **Installer UI (MUI2)**: `packaging/Cubeon.nsi` uses Modern UI 2 with branded
  wizard & header bitmaps (`packaging/graphics/wizard.bmp` and `header.bmp`),
  `ShowInstDetails hide`, `ShowUnInstDetails hide`, friendly non-technical copy,
  and Start Menu + Desktop shortcut registration.
- **Flet Image Fit**: Flet 0.86 uses `ft.BoxFit` (e.g. `ft.BoxFit.COVER`), NOT
  `ft.ImageFit`. Any image fit must use `ft.BoxFit`.
- **Release Version**: `cubeon/updater.py` APP_VERSION is `1.0.1`, reflected on
  `web/index.html` and `web/download.html`.


## Chat face avatars (2026-09-22) — HOW-TO
- `cubeon/faces.get_face_b64(name)` is THE way to show any Cubeon player's
  head (skins Worker `/faces/<name>.png`, disk-cached in `cache/faces/`,
  negative-cached 10 min for non-Cubeon 404s, background download, never
  blocks). Pair it with a `bool(get_face_b64(...))` token inside the
  repaint sig so late-landing faces paint on the next poll.
- Self-avatar fallback chain everywhere: uploaded pfp → face URL
  (`skins.get_skin_face_url` = Cubeon endpoint since 2026-09-22, was
  crafatar which 404s for offline accounts) → color chip.


## AuthMe tuner (2026-09-22) — INVARIANT
- `cubeon/server.py::_tune_authme_config` section tracking MUST be an indent
  stack, not a single "current section": AuthMe 6.x (ConfigMe) writes
  sections at indent 4, legacy AuthMe at 2. The old `indent <= 2` check made
  the tuner a silent no-op on modern configs (guard script in
  agents/2026-09-22_cline_authme-tunnel-reglimit.md).
- `AUTHME_TUNING` includes `restrictions.maxRegPerIp: 0` (unlimited): every
  player through the Minekube tunnel shares one apparent IP, so the stock
  per-IP registration cap (default 1) makes the first registrant block
  everyone. Do not "restore" a per-IP registration cap on tunneled servers.


## Wedged flet client / open-quit truth (2026-09-19) — INVARIANT
- The flet desktop client's bad case is NOT always a crash. It can WEDGE: window
  mapped, not one OpenGL frame, ~180% CPU, and `ft.run` never returning
  (measured live on Mesa 26.1 / AMD Polaris). Everything that recovers a session
  lives AFTER `ft.run` returns, so a wedged client makes tray Open/Quit, the
  software-GL retry ladder and Settings > "Restart to apply" ALL unreachable —
  the frozen window stays forever and the launcher can never be reopened.
- Detection is the client's own evidence: GLib writes
  `** (flet:N): WARNING **: <time>: Timed out waiting for OpenGL frame ...`
  **on stderr**. `_filtered_open_flet_view_async` merges the streams
  (`stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT`) and
  forwards filtered lines to `sys.__stderr__` with an explicit flush. DO NOT go
  back to filtering only stderr: a fake/alternative client logging to stdout
  silently defeats the counter (that exact mistake made a "verified" test
  vacuous on 2026-09-19).
- Measured signature of a real wedge: exactly TWO GL-frame-timeout lines ~0.15s
  apart, then silence forever while alive (rt2.log pid 29728 was a 34-minute
  ghost). Hence `_WEDGE_TIMEOUTS = 2`, `_WEDGE_RECENT = 25.0`, with
  `_WEDGE_GRACE = 12s` / `_WEDGE_WINDOW = 60s`. A threshold of 3 was
  unreachable dead code — do not raise it back without new measurements.
  **The burst GAP matters as much as the count** (2026-10-13): each timeout
  line means 10s of no frame, so a merely SLOW client also emits several —
  but spaced ~10s apart. Only a client producing NOTHING emits them seconds
  apart. `_WEDGE_BURST_GAP = 4.0` requires the two newest stamps to be that
  close; without it, two slow frames in the first minute killed a healthy
  session and the recovery ladder immediately REOPENED Cubeon (the
  "it reopens after I close it" bug). Stamps live in `_wedge_state["stamps"]`.
- The watchdog only KILLS the client (SIGTERM, SIGKILL after 3s). It never tears
  down the session itself: `ft.run` is once-per-process. The kill makes `ft.run`
  return and the EXISTING classified ladder does the rest (pre-paint ->
  software-GL retry; painted-but-dead -> re-exec).
- Residual gap (accepted, never observed): a client that wedges WITHOUT logging
  any line is not detected.
- Guards: `tools/test_wedge_watchdog.py` (deterministic fake with the measured
  signature; asserts kill + retry + termination + no ghost), registered in
  `tools/test_mega_smoke.py`'s SUITES.
- `_kill_flet_client()` also sweeps ORPHANED clients at session start (a `flet`
  process whose args carry our assets dir and whose parent is no longer a live
  launcher = ghost from a dead run). Two-factor on purpose, so a second live
  Cubeon instance is never touched.

## P2P stream teardown (2026-09-19) — INVARIANT
- A received `_FIN` must NOT close the local TCP socket immediately: bytes can
  still be queued in `_tcp_in_queue`, and closing there truncates the tail
  (measured: a 120000-byte transfer cut at 118535). `_handle_frame` sets
  `_remote_eof`; `_tcp_delivery_loop` drains, then stops the session with
  "Minecraft TCP connection closed". The FIN we send waits until
  `_unacked` is empty so it can't overtake a retransmission.
  `tools/test_p2p_transport.py::fin_drain_check` is the deterministic guard.
- `RelaySession` (WebSocket relay) still stops immediately on local close with
  `_in_queue` possibly non-empty — same shape, deliberately unchanged
  (documented in docs/bugfix-2026-09-18-ci-red-suite.md).

## Version scan (2026-09-19) — INVARIANT
- `versions.get_installed_versions()` pass 2 dedupes by FOLDER only. Deduping
  on the json's declared `id` made the list depend on `os.listdir()` order and
  silently dropped half-installed folders whose template manifest still named
  another version (they showed as neither installed nor incomplete).
  Guard: `tools/test_version_integrity.py`'s forced-order check.
- **Version lists show friendly labels, never raw ids (2026-10-13).**
  `get_installed_versions()` sets `display_name` via
  `versions.suggest_friendly_name(real_id, folder)` in BOTH passes (pass 1
  used to surface the raw id, so "fabric-loader-0.19.5-26.1.2" appeared as a
  second, separate game next to "26.1.2"). `suggest_friendly_name` routes
  through `extract_mc_version`, so the label is the GAME version with a
  loader tag: "26.1.2 (Fabric)", "1.20.1 (Forge)" — never "0.19.5 (Fabric)".
  The list is sorted newest-first (complete installs, then incomplete, then
  un-decodable custom ids) so vanilla + Fabric of the same version sit
  together. The Play-tab dropdown, its pick dialog, the online list's
  installed rows, and the Import-to picker all read `display_name` — do NOT
  reintroduce `v["id"]` as display text anywhere. `version_labels` nicknames
  still win over `display_name` (rename feature).

## CI / release storage (2026-09-19) — INVARIANT
- One run's artifacts (~510 MB) are bigger than the whole free Actions storage
  quota (~500 MB). **Artifact** upload steps (`actions/upload-artifact`) are
  **tag-only** (`if: startsWith(github.ref, 'refs/tags/v')`),
  `retention-days: 7`, and `continue-on-error: true` (publishing must never
  mark a good build red). This rule is about `upload-artifact` only — see the
  2026-10-17 section below for *release assets*.
- The REAL publishing channel is GitHub release ASSETS: release assets are
  exempt from the Actions storage quota (which stayed exhausted even 23h after
  purging 19 GB of artifacts), so binaries ship as release assets. The build
  jobs carry `permissions: contents: write`; the workflow root is
  `contents: read`. Tag builds FAIL if the release upload fails — intentional.

## Auto-release per push (2026-10-17) — supersedes "publish-on-push" (2026-10-15)
- **Before announcing a Windows build publicly, run
  `docs/WINDOWS_SMOKE_TEST.md`.** CI proves the installer BUILDS and runs the
  two offline startup harnesses, NOT the real app: the `Startup tests (Windows)`
  job has no flet client, no user32 window and no socket access beyond what the
  suites allow. (It was ALSO red for a pure harness reason until 2026-10-18 —
  see "The Windows startup job" below — so before that fix the job had never
  actually built the UI on Windows at all.) Step 3 of that doc is the
  update-nag check, and step 4 is the opt-in custom frame, which is default-OFF
  precisely because it has never been verified on real Windows.
- **One release per push to main/master**, with its own version: a push no
  longer refreshes the latest release in place. `tools/release_version.py` owns
  the policy — read its docstring before touching the version scheme. Per push:
  the `release` job decides the version, `stamp`s it into the tree, commits the
  bump back (`release: vX.Y.Z [skip ci]`, so the tag's source matches the tag),
  pushes the tag as the version lock, and opens a **DRAFT** release with
  `--generate-notes`. The three build jobs (`needs: release`) check out
  `ref: ${{ needs.release.outputs.tag }}`, re-stamp, build, and
  `gh release upload --clobber` to the draft. `publish` (needs all three)
  asserts every asset is present, then `gh release edit --draft=false`
  (`--latest` only when it is ahead of the already-public releases, so
  re-publishing an older build can't drag `/releases/latest` backwards).
- **Why the tag must equal APP_VERSION (shake this and every user is nagged
  forever):** `cubeon/updater.py` only accepts a `vX.Y.Z` tag newer than the
  APP_VERSION compiled into the running build, so a release tagged ahead of its
  own binary offers "update available" that never clears. Same literal feeds
  `packaging/build_deb.py` (deb version) and `build_windows_installer.py`
  (exe Properties), both by regex on the SOURCE. `stamp` is therefore the only
  supported way to set the version, it rewrites the site's display text too
  (`web/index.html` `vX.Y.Z`, `web/download.html` `Version X.Y.Z` — the site's
  *links* are version-agnostic, the worker resolves assets by name), and it
  RAISES if the literal can't be found: a silent no-op ships exactly that
  nag-forever build.
- **Version maths:** `next` = APP_VERSION if its tag doesn't exist yet (that is
  how a new series is declared — APP_VERSION was seeded to 1.2.0 for this),
  else patch+1 of the highest of (APP_VERSION, all `v*` tags), compared
  NUMERICALLY per segment (1.2.10 > 1.2.9). A source version BEHIND the newest
  tag steps forwards, never back. A human `v*` tag push skips the maths: the tag
  IS the version.
- **Never publish a half-built release:** `/releases/latest` feeds the in-app
  updater AND `worker/cubeon-downloads.js`, so a release must be invisible until
  all six assets are up (`publish` verifies their names first, including
  `cubeon_*_amd64.deb` by shape, since its name carries the version).
  `gh release upload --clobber` DELETES before it re-uploads, so a re-run of an
  already-published release is put back into draft first.
- **Re-run idempotency:** a re-run has the same `GITHUB_SHA` but the tag points
  at the bump commit, so the job looks for a tag pointing at our commit OR at a
  child whose subject is `release: vX.Y.Z [skip ci]` — and reuses it instead of
  minting the next version. `concurrency: release-${{ github.ref }}`
  (`cancel-in-progress: false`) serialises runs; the tag push is the atomic lock
  that makes two concurrent runs pick different versions rather than clash.
- **Deliberately NOT gated on `test`/`test-windows`:** `test_fuzz.py` and
  `test_install_cancel.py` are load-flaky on CI, and a flaky red test silently
  dropping a release is worse than shipping one (the run is red either way). Add
  `needs: [test, test-windows]` to `release` if that trade ever flips.
- The Linux AppImage IS built on every push now (the maintainer asked for
  complete auto-releases); `actions/upload-artifact` steps stay TAG-ONLY (quota,
  section above) — that `if:` keys off `github.ref`, the TRIGGERING ref, so
  checking out the tag does not accidentally enable them on branch runs.
- **Drafts and the API (2026-10-17, first real run):** `GET
  /repos/{o}/{r}/releases/tags/{tag}` returns **404 for a DRAFT** — only
  published releases come back. gh's own subcommands (`release view/edit/upload`)
  list-and-match instead, so they DO see drafts; look a release up with
  `gh release view <tag>`, never that endpoint (doing it the other way killed the
  first run: the re-run path decided "no release yet" and tried to re-create it).
  `gh release list --json tagName,isDraft` also includes drafts, which is what the
  publish step filters on; `/releases/latest` (what the updater and the download
  worker read) excludes them, which is the whole reason the flow is draft-first.
- **Hermetic git tests need an identity (2026-10-17, first real run):**
  `tools/test_release_pipeline.py` ran its first `git commit` in the inherited
  environment — fine on a dev machine (global git config), exit 128 on a runner
  that has none, which failed the whole suite before a single assertion ran.
  Every git call now passes the sandbox env (`HOME` + `GIT_AUTHOR_*`/
  `GIT_COMMITTER_*`); any future test that inits a repo must do the same.
- **`gh` needs to know the repo; a job without a checkout must be told**
  (2026-10-17, first real run): `gh` finds the repository from the nearest git
  remote, so in a job with no `actions/checkout` every call dies with
  `failed to run git: fatal: not a git repository` — which is exactly how the
  `publish` job failed *after* verifying all six assets, leaving a complete but
  unpublished draft (the safe failure: `/releases/latest` still pointed at the
  previous version). The workflow now pins `GH_REPO: ${{ github.repository }}`
  once at the top level, so no job depends on a checkout to know where it is.
- **`gh release view` has no `isLatest` field** (2026-10-17, second real run):
  it is a `release list` field. Asking for it makes gh reject the whole call, so
  the publish step published `v1.2.1` and *then* failed the job on its closing
  summary line. For "what is Latest now", read
  `gh api repos/{o}/{r}/releases/latest --jq .tag_name` — the same endpoint the
  updater and the download worker use.
- **Do not write the skip-ci token in a commit message** (2026-10-17,
  self-inflicted): GitHub skips the workflow when the message contains it
  *anywhere*, so the commit that merely DESCRIBED the release job's skip-ci
  trailer skipped its own run. Describe it as a "skip-ci trailer" instead.
- Regression: `tools/test_release_pipeline.py` extracts these `run:` scripts
  from the workflow and exercises them offline against a throwaway repo + a `gh`
  stub (tag reservation, re-run reuse, re-draft, incomplete-asset refusal,
  latest-only-forwards). `tools/test_release_version.py` pins the policy.
  **The stub models gh's failure modes on purpose** (drafts 404 on
  `releases/tags/`, unknown `--json` fields are rejected, and the publish
  scenario asserts the step's exit code) — a permissive stub let two real
  failures through on 2026-10-17. Keep it that way: when a stub is easier to
  satisfy than the tool, the test stops being a test.
- **Windows installer gotcha:** `choco install nsis` does NOT refresh PATH
  inside the running job, so `build_windows_installer.py`'s
  `shutil.which("makensis")` failed every build ("NSIS not found") and the job
  went red after the ZIP was already built. The `Install NSIS` step now
  appends `C:\Program Files*\NSIS` to `$GITHUB_PATH`. The portable ZIP also
  publishes BEFORE the installer step, so the exe still ships if NSIS breaks.
- **`Cubeon.spec` is a gitignored PyInstaller byproduct** (regenerated by
  `--name Cubeon main.py`), so a fresh CI checkout has none.
  `tools/test_mega_smoke.py` only asserts on it when it exists; it used to
  `open()` it unguarded and crashed the whole suite on CI with
  `FileNotFoundError`.

## Play-button state machine (2026-09-18) — INVARIANT
- The play button's mode is computed by `set_button_mode()` in `main.py`,
  which repaints ONLY the button subtree (`thread_safe_ui.refresh(play_button)`)
  — never a whole page.update(). If a call site needs a broader repaint, it
  must call `page.update()` itself.
- `state["running_version"]` is the single source of truth for "a game is
  live". Writers: `do_install_and_launch` sets it after spawn; `on_exit()`
  clears it AND resets the button (the old code never reset it — the button
  stuck on GAME RUNNING... forever). `on_version_selected()` re-paints
  "running" when the selected version is the live one, and
  `_reconcile_running_button()` (Play-tab entry) clears a claim the watchdog
  proves dead — needed because re-exec paths lose the in-process on_exit
  watcher. Any new writer must do the same or the button sticks again.
- Defense in depth (2026-09-18 round 2): `on_play_click()` re-verifies a
  running claim against the watchdog before launching (refuses a double
  launch of the same version; overlapping launches of DIFFERENT versions
  remain allowed), and a `running-liveness` daemon thread (one per process)
  self-heals a claim whose game died without on_exit firing. All three
  mechanisms must stay in sync with any change to the claim's lifecycle.
- **The "running" comparison MUST be guarded by `version_id` (2026-10-15,
  live bug).** In `on_version_selected`, `version_id = version_dropdown.value`
  is `None` when nothing is installed ("No versions installed yet"), and
  `state["running_version"]` is also `None` when no game is live — so a bare
  `if state.get("running_version") == version_id:` matched `None == None` and
  painted **QUIT GAME on an empty launcher**. It fires the instant the user
  changes the mod loader, because `on_loader_toggle_change` re-runs the
  selection path. Correct form:
  `if version_id and state.get("running_version") == version_id:`. The
  same `else` branch must not promise a phantom DOWNLOAD either — with
  `version_id` falsy it paints the neutral PLAY (there is nothing to
  download). Regression: tools/test_ui_smoke §"no phantom QUIT GAME".
- **Adding a loader to an ALREADY-INSTALLED vanilla version (2026-10-13) —
  INVARIANT.** `state["pending_loader_install"] = {"version_id", "loader"}`
  is the arm that lets a vanilla install gain Fabric/Quilt/Forge. The toggle
  handler (`on_loader_toggle_change`) sets it when the chosen loader isn't on
  disk yet, and Play switches to button mode `"install_loader"` (cyan,
  `INSTALL <LOADER> & PLAY`). It must be respected by
  `lock_loader_to_installed`, which would otherwise snap the switcher back to
  the on-disk truth (vanilla) and undo the pick. Cleared in three places
  only: (1) `on_version_selected` when the selected version differs from the
  armed one; (2) `do_install_and_launch` right after the loader install, and
  only when the armed version matches the launching one; (3) switching the
  toggle to vanilla/an already-installed loader. `on_play_click` treats a
  matching pending arm as `needs_install` so the Java check still runs (the
  loader installer needs Java even though the base version is present).
  Regression: tools/test_ui_smoke §4c drives the real closures.

## Instance install cancellation (2026-09-22) — INVARIANT
- The Play-tab progress row carries a `progress_cancel_btn` ("Cancel",
  tooltip "Stop this install"), visible only while an install is
  cancellable. `on_cancel_install()` only SETS a flag; the installing worker
  does the abort and cleanup, so the button can never strand state.
- One `threading.Event` per version id (`_install_cancels` / `_cancel_event`),
  shared by `prefetch_version` and the Play-click `do_install_and_launch` —
  otherwise a cancel during a prefetch would just make the Play worker wait
  forever on `_install_lock`. The prefetch's callbacks (`_note_status` /
  `_note_progress` / `_note_max`) both publish into `main._prefetch_view` and
  call `_guard`, which raises when the flag is set. `do_install_and_launch`
  re-checks the flag AFTER acquiring the lock (a cancel can land while it
  waits behind the prefetch).
- **A Play click waiting on the prefetch lock PAINTS THE PREFETCH** (2026-10-16,
  "when installing an instance it prepares for a long time"). Selecting a
  version starts an invisible prefetch of the whole thing; the click then
  blocked on `_install_lock` behind a frozen "Preparing" for however long that
  invisible download had left. The click now acquires the lock in 0.25 s slices
  (`while not lock.acquire(timeout=...)`) and calls `_adopt_prefetch(version_id)`
  each slice, which repaints the progress row from `_prefetch_view` (status,
  max/value, fed into the same `EtaEstimator`). `_prefetch_view` entries are
  never deleted — harmless, because a free lock means the loop body never runs.
  Regression: tools/test_install_prepare.py §1-2, tools/test_ui_smoke.
- The abort mechanism is raising `_InstallCancelled` from the mll progress
  callbacks (`setStatus` is called before each download, so queued tasks bail
  instantly and the executor's `shutdown(wait=True)` drains fast).
  `versions.install_version` re-wraps ANY callback exception as a generic
  RuntimeError, so "cancelled vs failed" is decided from the event, never the
  exception type.
- Cancellation is DISARMED before the launch phase (`cancellable["on"] =
  False`, `state["installing_version"] = None`, button hidden). Launching is
  deliberately not cancellable — `status_cb` is also passed into
  `launch_game`.
- A fresh install cancelled before completion has its whole version folder
  removed (`core.delete_version`, only when `was_installed` was False) so it
  can't resurface as a puzzling "(incomplete)" entry; a reinstall of a
  pre-existing version is left alone (install_version already dropped only
  the jars it clobbered). A `finally` always hides the button and clears
  `state["installing_version"]`.
- `state["installing_version"]` = the launch id with a cancellable install in
  flight (not necessarily the current dropdown selection).
- **`versions._seed_version_json` — the OTHER half of "it prepares for a long
  time" (2026-10-16).** mll's `install_minecraft_version()` answers a missing
  `versions/<id>/<id>.json` with a bare, un-timed `requests.get()` of Mojang's
  ~4 MB `version_manifest_v2.json` — no status, no progress, no timeout, no
  retry — before its first callback, i.e. a silent "Preparing" (or an outright
  hang) on the first install of every version. `install_version` now seeds that
  one small file itself from `_manifest_entry()` (Cubeon's cached/mirrored/
  stale-serving manifest), reporting "Fetching the version files" plus real
  progress, then hands mll a json that is already on disk. Strictly
  best-effort: no manifest entry, a bad checksum or no network falls back to
  mll's own lookup — but a CANCEL is re-raised (it is a choice, not a failure
  to swallow), checked through the install's own `_InstallCancelBridge`.
  Regression: tools/test_install_prepare.py, tools/test_install_cancel.py §2.

## Install downloads: retries, resume, and ONE pass per version (2026-10-17) — INVARIANTS
- **mll's downloader is ALWAYS replaced for an install**, not only for a
  cancellable one: every `versions.install_version` call enters
  `_PatchedMllDownloads`, which swaps `_make_resilient_download_file()` into
  every mll module that holds a `download_file` of its own (`mll.install`,
  `mll.runtime`, `mll._helper`, and the loaders that imported it directly —
  fabric/forge/quilt/mrpack; enumerated by `_mll_modules()`, duck-typed so the
  SimpleNamespace fakes in tests are patched the same way). Why: mll's own has
  no timeout, no retry, no resume and no checksum, and reports a bad status by
  RETURNING False — which every caller ignores, so a 429 from the asset CDN or
  a proxy dropping a connection mid-jar "completed" the install with a hole in
  it and nothing in the UI to say which file (the 2026-10-17 "download on
  instances isn't working" report). The replacement: (15s connect, 60s read)
  timeouts, 3 attempts with 1.5s/3s backoff honouring `Retry-After` (capped at
  30s), `Range` resume from the bytes already on disk, sha1 verify with a full
  re-fetch on mismatch, and a hard `_MllDownloadError` naming the file on a
  permanent 4xx. Assets and libraries resume; the version folder's own jars are
  still dropped on failure/cancel by `_drop_attempt_jars` (a truncated client
  jar must never look launchable). Regression: tools/test_install_download.py,
  tools/test_install_cancel.py.
- **One wide pooled session, not mll's per-phase 10.** mll installs assets
  across ~32 threads while handing them `requests`' default pool of 10, so
  most threads built and discarded a TCP+TLS connection per file — of ~4000.
  Our downloader ignores the `session` argument and uses
  `versions._install_session()` (pool 32). This must never go through
  `net.DOWNLOAD_GATE` (4) — that would serialise mll's own install.
- **`install_minecraft_version` is memoised per version id for one install.**
  A loader install calls it for the base version and then again for the loader
  profile whose json `inheritsFrom` the base — and mll's inheritsFrom branch
  re-installs the base INSIDE that call, so the base was walked two or three
  times per Fabric/Forge install. The loader profile's own libraries still
  install (that is real work); a repeat of a version already finished in THIS
  install is skipped. The memo lives on the `_PatchedMllDownloads` instance, so
  it never leaks across installs.
- **`versions._VERIFIED_FILES` (path → size+mtime_ns)** skips re-hashing files
  this process already hashed and found correct. Size+mtime is the same
  evidence the instance list trusts between launches, and a rewritten file
  changes its mtime, so a stale entry can never vouch for new bytes. This is
  what turns the second/third pass of a loader install into `stat()` instead of
  re-reading ~1 GB of assets.
- **`explicit_java=True` skips mll's own Java runtime**
  (`install_jvm_runtime`: a whole second JDK, tens of MB, hundreds of files).
  Callers pass it only when they know the launch hands mll its own
  `executablePath` — the signal is `config.launch_java_path()` (i.e.
  `cfg["java_path"]`), used by main.py's two install sites,
  `mod_loaders.install_mod_loader` (vanilla branch) and `modpacks`.
  **Do NOT skip it unconditionally**: `mll.command` falls back to the runtime
  directory when no `executablePath` is given
  (`minecraft_launcher_lib/command.py`, `get_executable_path`) and to the
  literal `"java"` after that, so on a machine with no system Java and no
  configured path that runtime is the only Java there is. Cubeon's own managed
  (Adoptium) JRE is NOT one of `launch.find_java_for_version`'s candidates, and
  `jre.java_status` answering "not ok" only prompts for Adoptium — it does not
  set `cfg["java_path"]`.
- **Progress repaints are throttled to 10 fps** in `do_install_and_launch`
  (`_paint_progress`, control-level `thread_safe_ui.refresh` of the progress
  row + bar, `force=True` at each phase end). Progress arrives once per FILE
  (~4000 per install) and that many marshalled repaints is what made the
  window stop answering input for the whole download; the launch phase's full
  `page.update()` covers the tail.
- **Java resolution is warmed off the UI thread at startup**
  (`_warm_java_check`). `jre.java_status` → `launch.find_java_for_version` →
  `mll.java_utils` probes every JVM it finds with `java -version` — measured
  1.46 s cold / 0.23 s warm on 2026-10-17 — and `on_play_click` ran that on the
  UI thread before it could even paint "Preparing".

## Friends: connect at startup, and reconnect like a blip (2026-10-17) — INVARIANTS
- The launcher connects at startup as soon as an identity EXISTS, including one
  `ensure_identity()` has just minted. It used to connect only when an identity
  predated the launch (`had_identity`), on the theory that a brand-new identity
  connects when the Chat tab first opens — so a first-run player who only ever
  plays the game (in-game chat is the other way in) stayed "not connected to
  Cubeon" for their whole first session with a perfectly good connection (the
  2026-10-17 report). `FriendsClient.connect()` restarts rather than doubling
  up (it stops a running loop first), so the Chat tab's own connect is still
  safe. tools/_fuzz_common.install_safe_stubs stubs `FriendsClient.connect`,
  so headless harnesses open no socket.
- A reconnect after a connection that WAS up resets the backoff ladder
  (`_opened_this_round`, set in `_on_open`), so a blip retries in 1 s instead
  of 30 s. The ladder is for a server that never opened the socket at all.

## Tray/session lifecycle (2026-09-18) — INVARIANT
- `_tray_runtime["controller_page"]` tracks the current session page and is
  cleared by session-end cleanup. `_tray_activate()` records Open requests
  unconditionally: Flet 0.86 can leave the page/window looking live after a
  native close, and the session loop consumes the request only after `ft.run`
  ends, so gating on that stale page reference made tray Open unusable.
- Seasonal layer defaults OFF (`seasonal_theme`/`season_pet` are False in
  `cubeon/config.py`); `CUBEON_SEASON=<season>` still pins for tests and
  screenshots.
- **Tray Quit order is load-bearing (2026-09-20)**: `_tray_quit()` must call
  `_kill_flet_client()` (and save geometry) BEFORE the rpc/friends cleanup.
  The cleanup can deadlock on native teardown; when it did, the 3s bail timer
  fired `os._exit(0)` with the flet client still mapped, leaving the reported
  "Quit leaves the window open, spinning Working…". Killing the client first
  means the window is gone no matter how the cleanup goes. Guard:
  `tools/test_ui_smoke.py` asserts the call order.
- **Startup splash + window geometry (rewritten 2026-10-16)**: `main()` mounts
  the "Loading Cubeon" `_splash` card right after the theme is applied and
  reveals it immediately, then swaps it for `_app_root`
  (`page.controls.clear()` + append + `page.update()`) once the full tree is
  built. `_apply_real_geometry()` (saved size/position + glass mode) runs
  BEFORE `await _reveal_splash()`, i.e. on the still-HIDDEN window, and
  `cfg = core.load_config()` moved up with it (it is a plain disk read). There
  is no small-splash-then-grow any more: the splash is a card in the window
  the app keeps.
  **Do NOT move the geometry back to only-`_reveal_window`, and never resize a
  VISIBLE flet window.** Resizing a visible window makes the desktop client
  wait for an OpenGL frame at the new size; on some Mesa/GTK setups that wait
  times out — `Timed out waiting for OpenGL frame of size 1900x1170 (have
  1872x1170)` — and the client dies before the finished UI paints, so the
  launcher flashed and closed. It hit hardest on the SECOND launch, because
  the saved geometry is only restored then (user report 2026-10-16: "when i
  size it too much it doesnt open on second launch"). Guarded by
  `tools/test_startup.py` ("the saved geometry lands on the window BEFORE it
  is ever shown") and `tools/test_ui_smoke.py`.
- **Window geometry must fit the WORK AREA, not the screen (2026-10-16)**:
  `_work_area()` reads `_NET_WORKAREA` (`xprop -root -notype _NET_WORKAREA`;
  KDE reserves 48 px on this 1920 screen, so the area is 1872x1200) and
  `SystemParametersInfoW(SPI_GETWORKAREA)` on Windows. The module-level, pure
  `fit_geometry_to_area()` (unit-tested in `tools/test_startup.py` §5) clamps
  the saved width/height to it and pulls a saved position back inside. A
  window bigger than the work area can never be granted, so the client waits
  forever for a frame at the size it asked for and dies with the SAME timeout
  as above — that is the "size it too much" half of the bug. `min_width`/
  `min_height` are additionally capped at the size actually requested (the WM
  would otherwise force the larger one). The corrected size is saved back, so
  a wedged install self-heals on the next start.
- **Showing the window needs a REAL change (2026-10-15)**: the app is started
  hidden (`ft.run(..., view=FLET_APP_HIDDEN)`) and revealed via `_show_window()`
  in `main()`, which writes `page.window.visible = False` and then `= True`.
  That pair is load-bearing, not noise: Flet declares `Window.visible` with a
  default of `True` and `Prop.__set__` DROPS any write equal to the declared
  default - no store, no dirty flag, nothing sent - so a bare
  `page.window.visible = True` emits nothing and the client is never told to
  show. Linux/GTK and Wine do not honour the hidden start (the window mapped
  anyway), which is exactly why this only showed up on real Windows:
  `Cubeon.exe` in Task Manager, no window at all. The False->True pair emits
  `visible: true` and is a no-op where the window is already visible.
  `wait_until_ready_to_show()` is also bounded (5 s `asyncio.wait_for`) so a
  client that never answers cannot keep the window hidden forever.
  `tools/test_ui_smoke.py` asserts the pair plus the `_show_window()` call.
- **Seasonal Restart button + open/close polish (2026-10-15):**
  - `_on_restart_click` (main.py) raises a full-window `restart_overlay`
    (`page.overlay`, `left/top/right/bottom=0`, `animate_opacity` — the same
    proven pattern as `account_scrim`) the instant the button is clicked, and
    only THEN, after a 0.4 s beat, closes the window through a named async
    task `_restart_close_after_beat` (the name matters: `test_ui_smoke.py`'s
    "schedules the window close" check matches `"close"` in the task name). A
    second click while the request is set is ignored.
  - **A pending relaunch OUTRANKS the live-client guard in
    `_window_gone_finish`.** The button's native close can arrive as a HIDE
    with the flet client still alive (Linux/KDE); the old
    `if _live_flet_clients(): return` then read a deliberate restart as a
    minimize and stranded the user with a hidden window and no re-exec
    ("restart closes but never reopens"). The `_relaunching` check must stay
    ABOVE `_live_flet_clients(`; `test_ui_smoke.py` asserts that order.
  - **Open fade**: `_app_root` is mounted at `opacity=0` with
    `animate_opacity`; `_reveal_window` sets `_app_root.opacity = 1.0` right
    after `page.window.visible = True` (the no-loop fallback sets it too), so
    the splash -> UI hand-off fades instead of hard-cutting. Never remove
    either opacity-1 write or a reveal failure leaves the UI invisible.

## Minecraft screenshot gallery (2026-09-19) — INVARIANT
- Screenshots live in Cubeon's private game folder at
  `MINECRAFT_DIR/screenshots` (`~/.cubeon_minecraft/screenshots` by default),
  not the user's shared `~/.minecraft`. `cubeon/screenshot_gallery.py` is the
  single boundary for listing, bounded preview decoding, safe clipboard file
  hand-off, safe deletion, and opening that folder. The Images pane inside
  Cosmetics uses this boundary; it is selected from the Cosmetics subtab row,
  never from the top-level nav. Never pass arbitrary paths into Flet images or
  delete callbacks.
- **Gallery perf (2026-09-21)**: both hot paths are cached in the store
  module. (a) `list_screenshots()` is memoized against the screenshots
  DIR's mtime+inode (`_dir_signature`, correct because only the game + the
  delete action change the folder and nothing edits a file in place) —
  re-opening the Images pane scans once, then every open is O(1) instead of
  `Image.verify()`-ing (full file read) every PNG. (b) `image_base64()`
  renders are disk-cached in `paths.CACHE_DIR/screenshot_renders` keyed by
  source mtime + size bucket (tmp+replace write) — first pass decodes each
  screenshot once, later opens re-encode a small PNG (~0.1 ms vs ~80 ms).
  `delete_screenshot()` drops the file's cached renders (dir mtime bump
  invalidates the list). The UI (`ui/screenshot_gallery.py`) caps cache-miss
  decodes at 3 concurrent threads via `_DECODE_POOL` so the first open with
  N shots doesn't fire N full decodes at once.
- **GOTCHA (learned the hard way 2026-09-21): `paths.py` computes
  `CUBEON_HOME` from `Path.home()` and IGNORES any `CUBEON_HOME` env var —
  only `CUBEON_GAME_DIR` is env-honored.** A probe script setting
  `CUBEON_HOME=/tmp/...` silently wrote 41 "Probe" skins into the REAL
  `~/.cubeon_launcher/skins`, and running `tools/test_ui_smoke.py` un-sandboxed
  CLOBBERED the real `capes.json` (it `open(capes.json,"w")`s directly and
  never restores). To sandbox launcher-adjacent work: redirect `HOME` AND set
  `PYTHONUSERBASE=<real home>/.local` (flet lives in the user site, which
  follows HOME), or patch module attrs post-import like
  `test_screenshot_gallery.py` does. NEVER rely on `CUBEON_HOME` env.

## Relay username metadata (2026-09-17, plan step 2)
- `cubeon/friends.py` exposes `minecraft_username(value)` -> the value when it
  matches `[A-Za-z0-9_]{3,16}` (case-preserving, NO reserved-name check) else
  `''`. `FriendsClient.set_minecraft_username()` is nonblocking (bg thread)
  and replays the username on every hello.
- The worker's `names` table carries a nullable `minecraft_username` TEXT
  column (PRAGMA-guarded ALTER, no unique index — duplicate usernames are
  legal and rows stay distinct by handle/UID). T_METADATA updates write ONLY
  that column; fan-out reaches friends AND pending-request counterparts.
- `FriendsClient.roster["peer_metadata"]` is keyed by CANONICAL handle with
  `{uid, minecraft_username}` (fields absent when unknown) and is persisted
  through `atomicio.write_json` — the roster cache write was a direct
  `open(path,"w")` before, which violated the atomic-JSON invariant.
- Identity-bearing worker frames now carry `<prefix>_uid` +
  `<prefix>_minecraft_username` (from/to/peer), and roster requests/groups add
  `*_details` arrays; the legacy string arrays are unchanged.

## Social identity fixes (2026-09-17) — INVARIANT
- **S4 identity cache gapfill**: `_remember_event` now calls `_remember_metadata`
  with `fill_missing_only=True` for "from"/"to"/"peer" prefixes. The client's
  `peer_metadata` cache (authoritative, updated by T_METADATA events before
  dispatch) is mirrored unconditionally; raw friend/request detail rows only
  fill missing UID/username fields and never overwrite a value a live event
  already delivered. `_chat_seeded` dict tracks `{gen, t, attempts}` per
  conversation; `_connect_gen` bumped on reconnect marks all cached entries
  `"retry"` so gaps backfill after disconnect.
- **S6/S7 chat history retry**: `chat_payload` no longer early-returns for
  `after >= 0` without seeding. If the conversation isn't successfully seeded
  (`_chat_seeded[canon] == "done"`), a history request is triggered with
  exponential backoff via `_HISTORY_REQ_TIMEOUT` (10s). Failed/timeout
  requests increment `attempts` and are retried on the next poll. Successful
  relay replies mark the conversation `"done"` to prevent re-requesting.
- **S8 history dedupe by relay ID/envelope**: `_chat_append` returns bool
  (appended vs deduped). Deduplication uses the relay's message ID (`mid`)
  when present, otherwise a fingerprint of the sealed envelope (ciphertext) —
  NEVER the plaintext, which may legitimately repeat. `_on_dm`, `_file_own_echo`,
  and `_on_history` all pass `mid` and `envelope` so the atomic dedupe under
  `_chat_lock` covers live DMs, echoes, and backfilled history uniformly.
- **S15 sync frame pubkey TTL**: `_sync_frame` now calls `_peer_pubkey(peer)`
  instead of reading the raw cache. `_peer_pubkey` enforces `_PUBKEY_TTL_S`
  (900s), re-fetches rotated keys on expiry, and clears the cache on reconnect
  (`_on_state`). Sync frames seal with the fresh key or fall back to plaintext
  with the "open" report so the UI is never silently in the clear.
- **S13 offline invite failure**: Worker's offline reply carries a relay-allocated
  room the host never learned. `_on_call_end` now matches this case when:
  `reason == "offline"`, host is in `ringing_out` with `room == None`, and
  `peer == p.get("to")`. It assigns the relay's room to the session before
  teardown so the host is notified and the session cleans up immediately.
  Peer hangups (no `reason:"offline"`) with unknown rooms do NOT match.

## Seasonal look (2026-09-17) — INVARIANT: a palette is bound at import
- `cubeon/seasonal.py` resolves WHICH palette this launch wears, at startup,
  from the timezone (CUBEON_TZ > TZ > /etc/localtime > /etc/timezone > Windows
  `tzutil /g`) + today's date. It never touches the network. The hook lives in
  `cubeon/__init__.py` and runs BEFORE main.py binds any `from cubeon.theme
  import ...` token — because a template patches theme tokens once at import
  (see color_templates.py), a palette change is a relaunch, never a repaint.
  Don't try to make it live-switch; the Settings > Seasonal pane + the greeting
  card in main.py explain the restart instead.
- Precedence (first wins): `--color` CLI pin (marks source="pinned",
  seasonal=False) > `CUBEON_SEASON` env (pin/off/auto — auto ignores config,
  for deterministic screenshots) > `cfg["seasonal_theme"]=False` >
  `cfg["season_override"]` > timezone detection > northern-temperate default.
- Seasons are METEOROLOGICAL (Mar/Jun/Sep/Dec 1). Southern hemisphere via the
  `SOUTH_ZONES` table in `cubeon/seasonal_geo.py` (generated by
  `tools/make_seasonal_geo.py` from /usr/share/zoneinfo + iso-codes — rerun it,
  don't hand-edit the table). Tropics get wet/dry labels (spring/summer
  palettes) instead of fake autumn.
- The four palettes are ordinary templates (`templates/color_{autumn,spring,
  winter,summer}.py`, aliases --color8..11) with WCAG-AA contrast asserted by
  `tools/test_seasonal.py` (101 checks; run it for any palette change).
- Live season changes: picking a season in Settings re-skins the runtime half
  IN PLACE via `update_badge` / `update_pet` / `reflow_ambience`
  (ui/seasonal_ui.py, wired in main.py's `_season_controls_sync` and
  `_season_runtime_apply`) — badge chip, pet sprite, and weather all visibly
  swap without a rebuild; only the PALETTE waits for relaunch. `reflow_ambience`
  RETURNS a new bounds tuple — bounds are immutable tuples, so it can't be
  updated in place; callers must store the returned value in `_season_rt`.
- JVM FLAGS (cubeon/launch.py CLIENT_JVM_FLAGS): Aikar-derived client G1 set,
  applied to EVERY launch as `-Xmx{ram}M -Xms{ram}M` + flags. Deliberately
  EXCLUDES AlwaysPreTouch (kills low-RAM machines / doubles launch time) and
  G1HeapRegionSize > 16M. Constraint: Java 8–25 compatible. Two values are
  deliberately softer than the server set because a weak client CPU shares its
  cores between GC and the render thread: `MaxGCPauseMillis=200` (not 40 — a
  40ms goal makes G1 shrink young gen and run young GCs far more often) and
  `G1HeapWastePercent=5`. `-Dorg.lwjgl.util.NoChecks=true` skips LWJGL's
  per-call pointer validation. (2026-10-05)
  GOTCHA: `-XX:G1RSetUpdatingIntervalTime` is REJECTED by Java 21 (and newer) —
  it made the JVM refuse to start. Validate flag changes against a real
  `java` before shipping:
    java <flags> -cp <dir-with-T.class> T
  The heap slider is hardware-bounded already (max = detected RAM,
  recommended = half) so -Xmx can't exceed physical RAM.
- SEASON BADGE IS NOT MOUNTED (user request): `season_badge` is still built and
  synced by _season_controls_sync, but the top-bar Row no longer contains it.
  The Settings > Seasonal pane is the entry point. Don't re-add the chip to
  the bar, and don't delete the widget (its sync calls would break).
- CONTENT DIR LAYOUT: MINECRAFT_DIR is `~/.cubeon_minecraft` (Cubeon's own
  private game folder, NOT ~/.minecraft). `CUBEON_GAME_DIR` env wins over the
  default and is THE sandbox hook for content tests (set it before importing
  cubeon.paths — dirs are computed at import). Game staging folders:
  resourcepacks/, shaderpacks/ inside it; stores: global_mods/,
  global_content/ (siblings the sync never wipes).
- PER-INSTANCE CONTENT (commit ec581b9): packs/shaders use the mods model —
  global store + (version,loader) profile of links + launch-time staging
  (launch.py calls content.sync_content_to_game(mc_version, loader)).
  Signature gotcha: `list_content(type, mc_version, version_id=None,
  loader=None)` — the THIRD positional is version_id; always pass loader as a
  kwarg or you silently get [] (cost me two probe rounds).
- `.cubeon-staged.json` state files live INSIDE the staging folders — any
  test counting game-folder entries must filter dotfiles.
- Regression guard: tools/test_content_instance.py (registered in mega_smoke
  SUITES). If "packs don't change between instances" is reported again, run
  it first — it reproduces the whole bug headlessly in ~2s.
- VERSION INSTALL INTEGRITY (commit 60b3c40): mll's downloader has no
  resume/checksums. `versions.install_version` now verifies size+sha1
  post-install, removes partial jars on any failure, and
  `get_installed_versions` runs `_client_jar_problem` over EVERY entry
  (size vs manifest, zip magic) — a truncated jar shows "(incomplete)",
  never "installed". Regression guard: tools/test_version_integrity.py
  (fake mll injection via `V.mll = _Fake`). Loader profiles may have no own
  jar, but their `inheritsFrom` chain must resolve to a valid terminal base
  with cycle/depth guards. Jar selection uses folder/metadata ID, never an
  arbitrary jar. Failed-install cleanup preserves unchanged preexisting jars;
  size-only snapshots cannot distinguish same-size concurrent rewrites.
- AUTO-DELETE OF UNFINISHED INSTALLS (2026-10-18, `auto_delete_incomplete`,
  ON by default, Settings > Game versions): the startup pass
  `versions.cleanup_unfinished_installs()` removes version folders whose
  download never completed. DELETING IS NOT THE SAME DECISION AS DISPLAYING —
  the bar is deliberately HIGHER than `get_installed_versions`'s
  "incomplete", which must keep SHOWING broken installs. Only three states
  are ever deleted: the client jar is missing, truncated (size != manifest),
  or not a zip (bad magic). NEVER deleted: a jar that is merely unreadable
  (`OSError` — permissions, or held open by a RUNNING game, routine on
  Windows), broken/missing metadata (hand-made or foreign folder), a loader
  profile (`inheritsFrom` — its base is a separate install), and anything a
  sha1 mismatch alone would catch (too slow at startup). A jar written within
  `_CLEANUP_GRACE_SECONDS` (600) is skipped: a download may be in flight
  right now (a second Cubeon instance, a manual copy); `skip=` ids are the
  caller's own in-use escape hatch. `install_version` already removes its own
  partial files on failure, so what this sweeps is what a HARD kill (crash,
  power cut, full disk) stranded. Runs BEFORE the first version scan in
  main.py so a stranded install never appears in the Play list. Regression
  guard: tools/test_auto_cleanup.py (incl. the "predicate stays a subset of
  the scan's incomplete" property).
- PRECEDENCE GOTCHA: `CUBEON_SEASON` env outranks `season_override` config
  BY DESIGN. A user with the var set sees their picker pick ignored. The UI
  surfaces this via `seasonal.env_pin()` (red note in the Seasonal pane +
  snackbar on change). If "my pick reverts" is reported again: check their
  env first, then whether save actually landed on disk (config.json
  `season_override`), then the handler.
- CRITICAL DEPLOYMENT FACT: the user does NOT run this source tree. Their
  desktop entry (~/.local/share/applications/cubeon.desktop) launches
  ~/.local/opt/Cubeon/cubeon — an INSTALLED PyInstaller build. Source-tree
  work is invisible to them until rebuild + reinstall:
  `pyinstaller Cubeon.spec --noconfirm` (~4 min; dist/Cubeon is a single-file
  exe; the spec already bundles assets/ + templates/, so new pets/palettes
  ride along), then `cp dist/Cubeon ~/.local/opt/Cubeon/cubeon`.
  The pre-Sep-17 install is backed up at ~/.local/opt/Cubeon/cubeon.bak-aug31.
  On 2026-09-17 a "my changes do nothing" report was EXACTLY this: a
  month-old installed binary. Check which copy the user runs FIRST.
- Runtime half (`ui/seasonal_ui.py`): badge + pet GIF + optional ambient
  particles, all driven by ONE shared `SeasonalAnimator` thread started in
  main.py's layout section and stopped in the session-end cleanup
  (`season_animator.stop()`). Pet/ambience toggles are live (cfg keys
  `season_pet`, `season_ambience`); the palette is not.
- The pet WANDERS, not hops: `build_perch()` returns `(lane, pet_dict)`; the
  top bar mounts the clipped lane Stack (PERCH_W px) and `add_pet(pet_dict)`
  drives a rest→walk→turn state machine (fixed amble, jittered rests, idle
  hops, scale_x mirror on turn). The bar mounts the LANE; the sprite dict's
  `["ctrl"]` is what visibility/click code touches. `add_pet` still accepts a
  bare control (legacy in-place hop) but nothing in main.py uses that now.
  GOTCHA: `SeasonalAnimator._frame()` acquires the animator's non-reentrant
  lock itself — never call it while holding `anim._lock` (deadlock; the test
  suite calls `_wander`/`_frame` bare).
- Restart-to-apply: module-level `_relaunch["request"]` (threading.Event) in
  main.py. The button saves cfg, sets it, closes the window; the __main__
  session loop checks it right after ft.run returns (ghost client already
  reaped by `_kill_flet_client()`) and execv's a fresh launcher BEFORE any
  crash classification/parking. Do NOT execv from inside main() — it would
  orphan the flet client as a ghost window (see Flet 0.86 hard rules).
- The once-per-season-per-year greeting card (`main.py`, gated by
  `cfg["season_seen"] == "<year>-<season>"`, non-modal, only for onboarded
  users) must stay wrapped in try/except: a missed hello must never break
  startup.

## Atomic JSON writes + hardening (2026-09-14) — INVARIANT
- Every persisted JSON state file (config.json, skins.json, skin_net.json,
  auth_key.json, ...) MUST be written via `cubeon/atomicio.write_json()`
  (unique temp file in the target dir + fsync + `os.replace()`), or an
  equivalent tmp+replace. A direct `open(path, "w")` is a crash-corruption
  bug: most load_* readers fall back to defaults on JSONDecodeError, silently
  wiping user settings. `save_config`, `_save_skins_meta`,
  `_save_publish_state` were the last three direct writers, fixed together.
- `cubeon/mods.py` `_safe_jar_filename()` sanitizes every user-picked jar
  basename before it becomes a file in a profile dir (also `add_mod_file`).
- `toggle_mod`/`delete_mod` guard on `os.path.lexists` - a stale UI mod list
  must produce a message/no-op, never FileNotFoundError.
- Worker DM refusals are never silent: `onDm` sends `T.ERROR
  {code: dm_bad_recipient|dm_empty|dm_not_friends}` (toasted by
  `friends_service._on_error`). Asserted in `tools/test_friends.py`.


## Chat tab identity card (2026-09-13)
- `ui/chat_tab.py` `_apply_identity` previously crashed on a typo'd control
  name (`you_id_text` vs `your_id_text`); the poller swallows exceptions, so a
  bug in an identity/roster paint path silently leaves the UI stale — never
  assume a blank control means no data, grep for a name error first.
- The Cubeon ID must always be rendered through `_friends.canonical_uid()` to
  keep the zero-padded 8-digit form.
- Flet 0.86 clipboard: `page.set_clipboard` is gone. Use
  `page.run_task(ft.Clipboard().set, value)` (async service). FakePage
  harnesses lack `run_task`, so clipboard handlers must try/except.
- **Worker deploys lag code (resolved 2026-09-20, but the pattern repeats).**
  The 8-digit-ID repo code sat undeployed for a day: production still ran the
  12-digit worker, so every add-by-ID failed with "No Cubeon user with ID"
  (the /uid/ lookup 404'd any 8-digit ID). Deploy is
  `cd worker && npx wrangler deploy -c wrangler-friends.toml`. Verify the
  deployed shape with `curl <base>/uid/00000001` — 200 = current, 404 with
  `/uid/000000000001` = 200 means the stale 12-digit worker is live.
- Chat identity labels use validated Minecraft usernames with the Cubeon UID
  (8-digit since `c28b8f0`, `UID_WIDTH=8` in `cubeon/friends.py`) visible
  separately. Auto-minted relay handles are routing keys,
  never display-name or tooltip fallbacks; missing metadata uses UID/Player.
- **Two-launcher testing:** `tools/launch_sandbox.py <name>` boots an isolated
  second launcher (fresh HOME → fresh friends account; `--list`/`--wipe`).
  MUST set `PYTHONUSERBASE=<real home>/.local` or flet can't import. Bridge
  uses a random port + token, so instances coexist. Default shares
  `~/.cubeon_minecraft` via CUBEON_GAME_DIR (no re-download); `--isolated-game`
  gives the sandbox its own game dir.
- Chat identity card (ui/chat_tab.py): profile avatar (PFP via
  `cubeon.profile.get_profile_picture_path`) + roster `you_minecraft_username`
  + the 8-digit Cubeon UID as a secondary line with a copy button. Self metadata
  comes from the latest live game's captured username, otherwise the committed
  launcher username (`watchdog.effective_username`), not an editable field.
  Friends/request labels use `FriendsService.peer_metadata` / `peer_label`;
  callbacks, history, and unread markers remain keyed by relay handle.
  PFP/self/peer metadata participate in refresh signatures. Legacy rename
  bridge/service entry points are immutable guards directing users to the
  launcher username setting; `/friends` retains rich request/self metadata.

 If a fact here contradicts the code, the
code wins — but fix this file too. Durable facts belong HERE, not in diary notes.

## AI app driver + mega smoke (2026-09-13) — read before writing a new test
- `tools/app_driver.py` is the reusable "hands": it boots the REAL UI headless
  (HOME sandboxed, `_fuzz_common.install_safe_stubs`) into a `Driver`, whose
  `tabs()`/`open_tab()`/`click()`/`type_fields()`/`fire_all()` an agent can
  call, and whose `report()` is JSON. Prefer extending it over re-deriving a
  FakePage harness. Its `DriverPage` adds the Flet 0.86 `show_dialog`/
  `pop_dialog` stack that `_fuzz_common.FakePage` still lacks, so
  `cubeon.dialogs`-opened dialogs are reachable. `shots` delegates to the
  windowed `ux_capture.py` (Flet has no headless renderer).
- **`fire_all()` fires the whole handler surface, not just clicks**: on_change/
  on_submit/on_click, plus on_hover (data "true"/"false"), on_focus/on_blur,
  and on_result (FakeEvent.files == [] = the picker-cancelled path). `report()`
  carries `handler_coverage` = fired/seen + the names of anything missed, so a
  shallow pass can't masquerade as coverage. As of 2026-09-13 `explore` =
  325/325 and `fuzz` = 4371/4371 (100%). A real pointer/OS event (physical
  hover, a real file chosen) has no headless analogue - the synthetic events
  above cover the *handlers*.
- **Headless `.update()` noise is filtered, not warned**: `Container.update()`/
  focus handlers raise `RuntimeError: Control must be added to the page first`
  when unmounted; the driver's `_classify` drops that (and "Event loop is
  closed") as an artifact, so hover logic is exercised without false alarms.
- `tools/test_mega_smoke.py` = the one-command gate, cheapest layer first:
  syntax (`compile` all 112 .py) → imports (62 modules) → type/contract
  (launcher_core facade covers every `core.*` in main.py+ui/, forbidden Flet
  APIs, None-in-controls, THEME/signatures, type hints) → AST control flow
  (unreachable, dup defs, bare except) → headless runtime (every tab opens,
  every handler fires, no errors, no None children, second build idempotent).
  `--static` skips runtime, `--json` for machines, `--suites` chains the
  repo's own harnesses.
- `ux_capture.py`'s TAB_ORDER now matches the live nav keys
  (play/mods/modpacks/chat/profile/server_console/server_plugins/
  server_settings/stats); Settings is not in `discover_nav` because its
  handler has no `k=key` default arg — capture it by other means if needed.
- **`_sandbox_home.isolate()` leaks into child processes** via `os.environ`
  (`HOME`/`USERPROFILE`). flet lives in the real user site-packages and is
  only resolved at interpreter STARTUP, so a child launched with a rewritten
  HOME gets `ModuleNotFoundError: No module named 'flet'`. Any harness that
  spawns a GUI suite after isolating HOME must pass the original HOME through
  (`test_mega_smoke.section_suites` does). Each suite re-isolates itself.
- **`install_safe_stubs()` patches `subprocess.Popen` process-wide** (to a
  `SimpleNamespace`), so any `subprocess.run` after it raises `TypeError`.
  Run subprocess-based suites BEFORE the runtime/driver layer, or restore
  `subprocess.Popen` afterwards.
- **Seeded browse hits matter (2026-09-13):** returning `[]` from the browse
  readers means no result row is ever built, so `build_browse_row()`'s
  `on_download` worker (the resourcepack/shader install) and the mod detail
  dialog are UNREACHABLE — the suite passes while that code is broken. The
  stubs return one realistic hit and shape-correct `get_mod_details` /
  `get_mod_versions` / `install_mod_with_dependencies` / `mod_doctor`; keep
  those shapes in sync with `cubeon/mods.py`.
- **The generic `except` in install workers hides defect signatures.** An
  `UnboundLocalError` there is caught and rendered as "Failed" — it never
  reaches `fire()`/`threading.excepthook`, so the defect detectors stay
  green. The only reliable guard is to stub the install leaves to SUCCEED and
  assert no row shows "Failed" (`test_fuzz` scenario D). Do this for any new
  install path.
- **Backend metadata reads go through `net.get_json`, not bare
  `requests.get`** (`mods.py`, `content.py`, `server.py`, `modpacks.py`,
  `minekube.py`). Any harness faking `requests.get` must ALSO route
  `net._do_get` + stub `updater.check_in_background`, `icons.prefetch`, and
  `core.get_mod_icons`, or a headless run silently hits the real network
  (the pooled `requests.Session` is invisible to a `requests.get` monkeypatch).

## Flet 0.86 hard rules (learned 2026-09-06, each cost real debugging time)
- **Dialog API: `Page.show_dialog(dlg)` / `Page.pop_dialog()` — there is NO
  `Page.open()`/`Page.close()` on 0.86.** Dialogs (AlertDialog AND SnackBar —
  both are DialogControls) live in the managed stack `page._dialogs.controls`,
  NOT in `page.overlay`. `show_dialog` raises on an already-open dialog —
  and since 2026-10-18 the shared helper ABSORBS that: `open_dialog` is
  idempotent (a mounted dialog is refreshed in place, and a lost race is
  swallowed only for the "already open" message), because the raw
  RuntimeError escaped the handler it was called from and reached users as
  "The application encountered an error: Dialog is already opened" from any
  path that could fire twice — a double click, a poll tick racing a button, a
  retry. Never call `page.show_dialog()` directly; `tools/test_dialogs.py`
  fails if anything outside `cubeon/dialogs.py` does.
  `pop_dialog` closes the top one; a buried dialog closes via
  `dlg.open = False; dlg.update()`. ALWAYS go through `cubeon/dialogs.py`
  (`open_dialog`/`close_dialog`/`show_snack`) — the app previously fell back
  to a pre-0.28 `page.dialog` branch that 0.86 silently ignores, which is why
  popups never closed and toasts never showed (fixed 2026-09-08; smoke §9
  pins it, FakePage mirrors the 0.86 API).
- `thread_safe_ui.final_update(page)` is NOT a generic "repaint now" — it
  only flushes a pending THROTTLED update. To paint one control from a timer
  thread, use `thread_safe_ui.refresh(ctrl)` (the account-panel scrim bug).
- `page.on_window_event` DOES NOT EXIST. Use `page.window.on_event`; `e.type`
  is a `WindowEventType` enum.
- The real X button delivers NO event to Python (X11/KDE verified). End-of-
  session cleanup must run after `ft.run` returns in `__main__`, not in an
  event handler. See `_session_end` dict (module-level!) in main.py.
- `window.prevent_close` makes the window UNCLOSABLE on Linux. Never set it.
- `Window.center()/to_front()/close()` are async coroutines; `run_task`
  requires a coroutine function (TypeError otherwise). `Window.update()` is
  sync.
- Async `window.center()` during first-frame reveal crashes flaky Mesa
  drivers (libgallium SIGSEGV). Center by computing left/top numerically
  BEFORE paint instead.
- The flet client may SIGSEGV in libgallium (Mesa 26.1/AMD Polaris; both hw
  and llvmpipe; ~50% flaky). main.py's `__main__` retry loop handles it:
  pre-paint death → `use_software_gl` marker + relaunch (2 retries).
  CONFIRMED 2026-10-18 with a real core dump (`libgallium-26.1.6` ←
  `libflutter_linux_gtk` ← `gtk_container_propagate_draw`): it is a Mesa
  26.1.x radeonsi/gallivm regression, so the retry ladder escalates
  llvmpipe → softpipe (no LLVM, therefore a different code path) and the fix
  for a user is the Mesa update (26.2+). Diagnosable from cubeon.log since
  2026-10-18 — see the crash-forensics section (`cubeon/incident.py`) for what
  a user "crash" report must contain.
- The flet client prints one `Atk-CRITICAL **: atk_socket_embed: assertion
  'plug_id != NULL'` line to inherited stderr on every launch (KDE/X11;
  GTK a11y socket with no atk-bridge). Harmless. `NO_AT_BRIDGE=1` does
  NOT stop it, and the env can't be fixed — main.py instead wraps
  `flet_desktop.open_flet_view_async` to pipe the client's stderr through
  a drop-filter (async `readline`; a SYNC read on the asyncio pipe eats
  ALL client stderr — verified). Non-matching lines still reach the log.
- After the retry loop: `os._exit(0)` — GLib/pango native threads can hang
  interpreter shutdown.
- System tray = `cubeon/tray.py` (pystray, optional dep, icon-only while
  running; true background-on-close is IMPOSSIBLE on this Flet build).
  Tray callbacks arrive on pystray's thread → marshal via `page.run_task`.
- **`ft.run()` is ONCE-PER-PROCESS on 0.86.** A second `ft.run` spawns a
  new flet client whose engine NEVER initializes (silent hang, no crash,
  no window — verified live). Tray reopen therefore RE-EXECS the
  launcher (`os.execv` in `__main__`, `CUBEON_TRAY_REOPEN=1` env, PyInstaller
  `sys.frozen` handled). Never "fix" this back to an in-process rerun.
- On X-close the flet CLIENT process stays alive with a ghost
  "Working..." window (0.86 can't remove its implicit view).
  `_kill_flet_client()` in `__main__` kills children named `flet`
  (SIGTERM→2s→SIGKILL). Match on the NAME — Minecraft (`java`) is also
  our child and must never be touched.
- Tray reopen events are timestamped (`reopen_at`) and honored only if
  newer than `session_ended_at - 5.0`. NEVER blind-clear the reopen/quit
  events — that silently drops every fast Open click made during window
  teardown.
- **`control.page` RAISES `RuntimeError` on unmounted controls** (Flet
  0.86, `base_control.py` — it walks `.parent` and raises "Control must
  be added to the page first"). `hasattr(ctrl, "page")` returns True (the
  property exists), so it catches nothing. Any generic repaint helper
  must wrap the `.page` read in try/except. Flet sends a control's full
  state when it's mounted, so pre-mount mutations are NOT lost by
  skipping the repaint. Verified 2026-09-07 (Mods-tab click crash).
- The launched game gets its own session + real log file
  (`~/.cubeon_launcher/game.log`, `start_new_session=True`, stdin
  /dev/null) so it SURVIVES launcher exit/terminal close. Don't
  "simplify" this back to inherited pipes.
- Repaint profiler: `CUBEON_PERF=1` times every `page.update()` by call
  site (table at exit, in `cubeon/thread_safe_ui.py`). Use it before
  any UI-performance guesswork.
- **Repaint rule:** one small region changed → `thread_safe_ui.refresh(ctrl)`
  (control-level diff, ~0.35ms avg); structure changed (add/remove/swap)
  → `page.update()` (full-tree, 5-8ms avg). All per-keystroke /
  per-file / per-log-line paths already use refresh(); keep new code on
  that pattern. `refresh()` is thread-safe like page.update().
- Startup: `minecraft_launcher_lib` is lazy (`cubeon/lazy.py`); Mods/
  Modpacks/Servers tabs build on FIRST VISIT, not at startup.
- Test-harness gotcha: `tools/test_ui_smoke.py` imports `main` as a module,
  so anything `main()` references must exist at module scope (bit us with
  `_session_end`).
- **A `None` inside any Flet `controls` list (e.g. `ft.Text(...) if cond
  else None` in `ft.Column([...])`) does NOT raise Python-side.** It
  serializes as a null child; the Dart client fails to build that subtree
  and Flutter's release-mode ErrorWidget paints a giant gray box in its
  place — with zero output in any log. This was the "white thing on
  uploaded capes" bug (2026-09-07). Never put None in controls lists;
  test_ui_smoke §5b walks the built Cape pane asserting None-free lists.



## Version art + new-UI preview (2026-09-08)
- `cubeon/version_art.py`: version id → official banner image (minecraft.wiki).
  Lookup: `<id>_banner.jpg` URL first (covers 1.15.2+, snapshots), then the
  page's lead image via the MediaWiki `pageimages` API (old versions 1.8-1.14
  have no banner file). Disk cache `CACHE_DIR/version_art/<id>.{jpg,png}` is
  FOREVER (banners never change); memory dict short-circuits both hits and
  misses-per-session. UI threads must use `fetch_async()` — `get_version_art()`
  downloads synchronously on miss.
- `ui_new/preview.py` is the REDESIGN PREVIEW, launched by `python main.py
  --new-ui` (intercepted in `__main__` before any flet-desktop stderr
  wrapping). It shares NOTHING with the real UI: top-bar nav, cinematic
  banner hero, version card grid. It reuses real palettes through
  `cubeon.color_templates`. Do not build features in the preview — port them
  into main.py only after user approval.
- Launcher's visible name is "Cubeon" (unchanged). The IN-GAME MOD is named
  "Cubeon Client" (fabric.mod.json `name`, screen title + corner-icon tooltip
  in CubeonClientScreen.java) — jar id / package `cubeon-client` /
  `com.cubeon.client`.
- Sidebar brand = cube mark + "Cubeon" + a Feather-style player pill:
  small avatar + in-game username (`sidebar_brand_avatar` /
  `sidebar_brand_username`, refreshed in `refresh_avatars()`), click →
  Profile tab. test_ui_smoke asserts the window title string.
- **Play page composition (2026-09-11 refinement).** PAGE HEADING ("Play" +
  "Launch Minecraft your way.", FONT_DISPLAY only for the heading) → the
  single hero card, top-aligned and compact (padding 20, internal `spacing=0`
  with explicit spacers; NOT stretched to fill the viewport). The card is
  three labelled bands, separated by explicit spacers only - the two
  `pixel_divider()` calls that used to sit under the Mod loader and above the
  footer were removed (2026-09-11): INSTANCE HEADER
  (grass-block emblem, `hero_title`, loader chip + version meta, rename/
  delete) → CONFIGURATION (a row of the two related fields, Game version
  dropdown + Account field, then the Mod loader segmented control) →
  ACTION FOOTER (PLAY right at 280px).
  Below the card sits a full-width OG Minecraft key-art banner
  (`assets/titleimg.jpg`, 2000x1000): wrapped in a `Row` so an expanded
  `Container` stretches it edge-to-edge (the card itself stays compact), fixed
  height 220 + `BoxFit.COVER` + `ClipBehavior.ANTI_ALIAS` so it crops cleanly at
  any window width.
  PLAY text uses the clean UI font (not Minecraftia) — pixel face is reserved
  for branding/page heading/instance title. Delete is TEXT_DIM at rest and
  DANGER only on hover; rename TEXT_DIM→TEXT on hover.
- **Top nav**: icon-only buttons (`build_top_nav_button`) are 21px icons with
  a green underline AND an `ACCENT_TINT` wash for the active tab; tooltips
  carry every destination (test_ui_smoke's `all_text` includes
  `tooltip` attrs, so nav names are asserted from them). Do not change
  tooltip words without updating `nav_labels` in test_ui_smoke.
  Account/Settings icons are 22px.
- **Palette is true black + green, via the `green` template (2026-09-11).**
  The app default is `DEFAULT_COLOR_TEMPLATE = "green"` in `cubeon/__init__.py`
  (was `"carbon"`). `templates/color_green.py` and the fallback `cubeon/theme.py`
  now both carry the user's exact scheme: `BG=#050505` (true black),
  `SURFACE=#0B0D0A`, `SURFACE_HI=#131711`, `SURFACE_MAX=#1A2015`,
  `BORDER=#242B1E`, `TEXT=#DDF6D5` (pale green-white), `ACCENT=#46BA34`,
  `ACCENT_HI=#5FD24B`, `ACCENT_DIM=#2BAF00`, `ACCENT_DEEP=#052400`,
  `ON_ACCENT=#04120A`, `CARD_FILL_HERO=#0C0F0B`. Surfaces are black with a
  faint green cast - never grey. Green stays reserved for
  ACTIVE/SELECTED/ACTION/SUCCESS (`ACCENT_TINT` 0.12 wash; `ACCENT_TINT_HI`
  0.20). The loader segmented-control thumb uses the solid `ACCENT_DEEP`
  (`#052400`) now, not the `ACCENT_TINT_HI` wash of the previous pass.
  `ACCENT_DEEP` is a module-level token (NOT in `THEME`) exported by
  `cubeon/theme.py`; templates that don't declare it get it derived in
  `cubeon/color_templates._derive()` (darkened `ACCENT_DIM`). The old olive
  literals (`#33431E`, `#0E110A`, ...) must not come back.
- **Corners are softened (2026-10-15, user request) — INVARIANT-ish.**
  The one radius family in `cubeon/theme.py` is now `RADIUS = 8`
  (controls/inputs/chips/nav), `RADIUS_LG = 12` (cards/dialogs/large panels),
  `RADIUS_PILL = 999` (genuinely round; defined but no live call site),
  `RADIUS_NONE = 0` (flush insets: progress bars, dividers, image edges).
  It used to be dead-square `RADIUS = 2`, which read as sharp/harsh. `block()`
  defaults to `RADIUS`, so Flet's own controls (dialogs/buttons/chips/cards)
  follow it through `apply_page_theme`. Deliberate hardcoded exceptions to
  leave alone: pixel-art confetti particles (`ui/seasonal_ui.py`, 2px), the
  connection dot (`ui/chat_tab.py`, 4px → a circle) and the unread badge
  (9px). Version art keeps its own `ART_RADIUS = 12` (rounder than controls).
  No test pins a radius value — change the tokens, not call sites.
- **Copy rule (binding, 2026-09-11):** all user-facing text is plain and
  gamer-friendly — no jargon (`jar`, `process`, `PID`, `hash`, `config.json`,
  `UUID`, `endpoint`, `.zip`, `OS`, `plugin stack`, "in this build"). Settings/
  Stats captions, mods/modpacks/shader notices, server tooltips and the legacy
  note were all rewritten. Keep new strings short and non-technical.
- **Minekube badge = credit card (2026-09-21):** the DNS icon in Settings
  header no longer teleports to the web. Clicking opens an in-app AlertDialog
  (`_open_minekube_info` in main.py) explaining WHY Cubeon backs Minekube —
  they're OPEN SOURCE and give EVERYONE (not just Cubeon) a free public
  address for a home-hosted server, and Cubeon's server sharing runs on their
  network — with a "Open their website" FilledButton (webbrowser.open
  connect.minekube.com, snackbar fallback) and a Close button. Tooltip reads
  "We back Minekube - open source, free addresses". The relationship is
  Cubeon supporting Minekube, NOT Minekube sponsoring Cubeon — keep the copy
  pointing that way.


- Loader support/installed lookups MUST use `core.extract_mc_version(version_id)`
  — the raw dropdown id can be a loader-install row (`fabric-loader-…`),
  which makes `find_installed_loader_version` miss and `is_loader_supported`
  lie. The launch path always knew this; the UI path didn't (fixed).
  **NeoForge specifically (2026-10-14):** a NeoForge id like
  `neoforge-21.1.99` is a real on-disk folder whose base Minecraft version lives
  in its version json's `inheritsFrom` — `extract_mc_version` MUST resolve it
  via `cubeon/versions.py:_inherited_base_version()` (traversal-guarded
  `_plain_filename`) and never by stripping the prefix/arithmetic (21.1.99 →
  "21.1" and 26.x-era numbers are both wrong). If `_inherited_base_version`
  can't read the json it returns the raw id as a safe fallback, so mods never
  sync from an empty folder.
- **Same rule for anything PER-VERSION on the server side (2026-10-17):** a
  launch id must never reach Paper's Fill API or Modrinth's
  `versions:`/`game_versions` facet. Paper publishes per Minecraft release, so
  a loader id is a guaranteed 404 (the "Install server" button failed on
  Fabric profiles with `Couldn't reach .../versions/fabric-loader-0.19.5-1.21.11/builds
  after 3 tries: 404 Client Error`), and Modrinth matches ZERO hits for a
  loader id, so the Plugins tab search AND the managed AuthMe install came back
  empty on exactly the Fabric profiles that need them. Use
  `core.minecraft_version(version_id)` (= `extract_mc_version` + id fallback)
  at `server._get_paper_download_url`, `server.ensure_default_plugins` /
  `ensure_smooth_mode_plugins`, and the `search_plugins` / `get_plugin_download`
  callers in `ui/server_tab.py`. Verified live: `1.21.11` → Paper build 67 and
  27 worldedit hits; the loader id → 404 and 0 hits.
- Loader checks run in PARALLEL (one thread/loader); results cached in the
  session `loader_check_cache` keyed by raw version id. mll timings:
  fabric 0.6s / quilt ~1s / forge ~1.9s / neoforge ~1s, cached 1 week via
  `cubeon/local_cache` (`loader_support` namespace).
- Segment dim rule: only dim when (unsupported AND not installed). Never dim
  just because the version is installed — the pill stays clickable
  (on_loader_toggle_change allows any INSTALLED loader + vanilla).
- Headless diag recipe: extract FakePage from tools/test_ui_smoke.py,
  call `main.main(page)`, walk control tree (see
  agents/2026-09-06_agent_loader-ui-fixes.md).

## KV write discipline (all Workers, 2026-09-06)
- KV free tier: 1,000 writes/day **account-wide**, 100,000 reads/day. Never
  write without comparing first — use `putIfChanged(env, key, value, opts?)`
  (cubeon-skins.js); it returns `"quota"` on limit-exceeded → caller maps to
  429. TTL'd puts can't skip the write (the TTL refresh IS the write).
- Steady state (repeat heartbeat, identical re-upload) costs ZERO writes:
  verified against `wrangler dev --local`.
- Friends worker = Durable Objects (NOT KV-metered). Waitlist/invites dedupe
  by read before writing.
- **Never `git add -A` in worker/ after `wrangler dev`** — `.wrangler/` local
  state (sqlite/blobs) is gitignored now; check `git status` first.

## Skins identity guard rails (2026-09-07)
- `ownsUuid` returns `"quota" | "claimed" | true | false`: check quota
  first; `"claimed"` = first-contact TOFU (race-fixed: re-reads owner
  after put). Heartbeat uses it to exempt the INITIAL name claim from the
  move cooldown.
- Pointer moves are per-identity rate-limited: `lastmove:<uuid>` stamp,
  3600s cooldown (`429 name_move_cooldown`). Rename costs 2 KV writes
  (pointer + stamp); first claim 2 (owner + pointer, no stamp); steady
  state 0.
- Heartbeat responses carry `name_contested: bool` (computed from the
  PRE-move holder + their lastmove stamp — post-write holder would always
  be self). Client persists it in skin_net.json → `skins.name_contested()`
  → status-bar note on rename (main.py, 3s-delayed daemon thread).
- Unlocks POST on KV quota → real `429 kv_write_budget_exhausted` (was
  200-with-stale-set; milestones.py still tolerates both shapes).

## Window launch (main.py, 2026-09-06)
- `page.window.visible = False` at setup; after `mark_mounted`, a
  `page.run_task(_reveal_window)` awaits `wait_until_ready_to_show()` then
  flips visible → no default-size flash / blank frames.
- Geometry persists to `~/.cubeon_launcher/window_geometry.json`
  (`load/save_window_geometry` in cubeon/config.py); debounced 400 ms saves,
  clamp on restore, maximized saves keep the restore size.
- Flet 0.86: `Window.center()` / `wait_until_ready_to_show()` are async —
  must go through `page.run_task()`; `Window.visible` is a plain field.

## cubeon-skins Worker — face avatars (2026-09-05)
- `GET /faces/<username>.png` — player's head crop, same pointer→uuid→record
  chain as profiles; falls back to the full sheet for pre-face records.
- `POST /api/skin` body may include `face` (128×128 PNG) — content-addressed,
  stored as `record.face`. PNG guard is `isPngWithSize(bytes,w,h)`; **faces
  are 128×128**, sheets 64×64/64×32 — size-mismatched uploads are silently
  dropped, so new texture shapes must update the guard.
- Launcher: `_compose_face_png` (cubeon/skins.py) renders the head crop
  (base + hat layer) from the composed sheet; rides the skin upload, never
  raises (None → omitted).
- Discord presence small_image = `<CUBEON_API_BASE>/faces/<name>.png`
  (external URLs are allowed in RPC asset fields; third-party mirrors like
  minotar are useless for offline names — they only know Mojang accounts).

## What Cubeon is, in one paragraph

A Minecraft launcher (Python/Flet desktop UI) with a friends/social layer:
a Fabric mod (`mod/`) injects an in-game **chat screen** (2026-10-14: everything
else friends-related was removed from the mod - see the invariant section),
talking to the launcher over a localhost HTTP bridge, which talks to
a Cloudflare Worker relay (`worker/`) over WebSocket. The launcher ALSO has its
own top-nav **Chat tab** (`ui/chat_tab.py`, 2026-09-11) that drives the same
process-scoped `FriendsService` directly, so the social layer works without
launching the game - and the in-game screen and the launcher tab show the SAME
conversations. DMs and sync frames are E2EE (`cubeon/e2ee.py`). Local
server hosting is Paper-only, exposed to friends via Minekube Connect tunnels.

## Repo layout (top level)

| Path | What it is |
|---|---|
| `main.py` | UI glue: builds tabs, owns FriendsService, avatars, dialogs. ~3000 lines. |
| `launcher_core.py` | Re-export shim over the `cubeon` package (legacy import surface). |
| `cubeon/` | All launcher logic (see table below). |
| `ui/` | Flet tab builders: `server_tab.py` (biggest), `mods_tab.py`, `modpacks_tab.py`, `skin_tab.py`, `stats_tab.py`, `chat_tab.py`. Pure builders — they receive `cfg`/`state` by reference and helpers (`section_label`, `pixel_divider`, theme) from main.py. |
| `mod/` | The in-game Fabric mod. **2026-10-15: the standalone HUD mod merged in — one jar per Minecraft version, 24 of them, 1.20 → 26.3. 2026-10-17: renamed throughout to the Cubeon Client.** Shared tree `src/main/java/` is Minecraft-FREE: `Bridge.java` (localhost HTTP client: roster/chat/players/events only - `/dm` via sendChat is the mod's only POST), `Json.java`, `BadgeNames.java`, `mixin/YggdrasilSessionServiceMixin.java`, `com/cubeon/client/hud/CubeonHudConfig.java`. Everything that touches Minecraft lives in a per-bracket overlay: `java-overlay-api-yarn/` (1.20–1.21.11, Yarn names - `CubeonClient.java` entrypoint/chat notices, `TabListTag.java`, `WorldPlayers.java`, `mixin/PlayerTabOverlayMixin.java`) and `java-overlay-api-mojang/` (26.x, the same four files in plain names). The HUD is seven `java-overlay-hud-*/` copies of **`com.cubeon.client.hud`** (`CubeonHudClient`/`CubeonHud`/`CubeonHudKeybinds`/`CubeonHudMenuScreen`/`MoveOverlayScreen`, plus `PingProbe` and a `mixin/` for 26.x); its Minecraft-facing API only moved 5 times across the 24 versions (26.3 also renamed `InputConstants.Type.KEYSYM` to `KEYBOARD`, so it has its own copy of the 26.2-era HUD). 26.x also adds `resources-26x/cubeon-client-hud.mixins.json`. `brackets.json` = **single source of truth** for the matrix (read by build.gradle AND cubeonfriends.py). |
| `worker/` | Cloudflare Worker + Durable Object relay (`cubeon-friends.js`, `cubeon-invites.js`). Protocol constants must stay in parity with `cubeon/friends.py` (asserted by `tools/test_friends.py`). |
| `assets/jars/` | Shippable jars: both Friends mod jars + `connect-spigot.jar` (Minekube Connect). |
| `tools/` | Test harnesses (plain scripts printing `N passed, M failed`). |
| `agents/` | Agent notes (history) + `docs/` (guides) + this map. |
| `archive/` | Old PyInstaller output — ignore, never edit. |

## Key modules in `cubeon/`

| Module | Owns |
|---|---|
| `paths.py` | Every on-disk location + `ensure_disk_space()`. CUBEON_GAME_DIR env overrides the game dir (tests use it). |
| `friends_service.py` (~2800 lines) | Headless friends owner: roster, add/rename (local-state answers, no blocking lookups), E2EE chat, sync compare channel, P2P sessions, notification ring (200 events). Serves all bridge providers. |
| `local_api.py` | The localhost HTTP bridge the mod polls. Token file `~/.cubeon_launcher/local_api.json`, 0600, loopback only. |
| `friends.py` | Relay client (WebSocket, secret as first frame), name rules, identity.json, claim/rename. `auto_name()`/`ensure_identity()` = the secret-derived automatic handle (no claim prompt). `T_*` constants = protocol truth. |
| `e2ee.py` | X25519 DM encryption; keys published to the relay under the claimed name. |
| `p2p.py` | P2P worlds: STUN + relay fallback, mod/asset sync, teardown. INVARIANTS (2026-09-17 wave 1): `_mod_target()` (basename + .jar + realpath containment) is the ONLY way a peer-named jar becomes a file — used by BOTH the download path and the cache-hit path; `_asset_target()` enforces the extension allowlist + symlink-safe containment receiver-side; `_accept_chunk()` bounds seq/total (strict ints, encoded-size cap, base64 validate) — NEVER allocate from peer-declared totals; STUN attrs pad `(-attr_len) % 4`. ModSync/AssetSync have cancel()/journal for cancel-with-rollback and an on_error callback the service wires to session failure. |
| `worldgate.py` | The OPTIONAL password on a P2P LAN world (in-memory only, dies with the session). Host arms it from the mod's password prompt; the joiner proves it via HMAC(PBKDF2(pw,salt), nonce) over the E2EE signal channel - the p2p_offer (LAN port + relay token) is withheld until a proof lands, so the gate is real, not decorative. GATE SIGNALS ARE E2EE-SEALED (2026-09-17): friends_service `_send_gate`/`_open_gate` wrap every gate_* frame in the peer's DM envelope; unsealed/tampered gate signals are refused, and every transport path (`_send_p2p_offer`, `_switch_to_relay`, `_run_host_punch`) checks `_transport_allowed` (per-session `gate_required`/`gate_authorized`) BEFORE creating a transport. Harnesses firing gate frames must seal them (see `gate_build`/`gate_signals` in test_friends_service.py). |
| `server.py` | Paper server hosting: install (Fill v3 API), start/stop, properties, orphan detection. |
| `minekube.py` | Public address tunnels: finds/installs Connect plugin, endpoint config. |
| `modpacks.py` / `mods.py` / `global_mod_cache.py` | Modrinth/CF packs; per-profile mods LINK into one global store (`~/.cubeon_minecraft/global_mods`) — never copy jars between profiles. |
| `cubeonfriends.py` | Which Cubeon Client jar goes into which profile (24 brackets, one per exact MC version), injected at launch. Also `ensure_fabric_api()`: installs **Fabric API** from Modrinth beside the jar, because the merged HUD is built on it — the mod only *recommends* it (and `KeyHudClient` catches `NoClassDefFoundError`), so a missing API costs the HUD, never the game. `mod_stamp()` = jar freshness fingerprint. |
| `perf_mods.py` | FPS boost: installs **Sodium only** (`PERF_MODS`) into a Fabric/Quilt profile at launch when `client_mod_enabled` AND `perf_mods_enabled` (narrowed 2026-10-05 — the 8-mod suite added little and carried crash surface). `_present()` dedupes by slug/name/id/filename; skip-if-present (no auto-update); best-effort, never raises. `prune_retired_perf_mods()` deletes the 8 retired mods from a profile that have them (only Cubeon-installed, by recorded slug/project id). Also `sanitize_entityculling_config()` — strips null/blank whitelist entries that crash the game on tick 1 (called unconditionally on the launch path) — and `apply_max_fps_sodium()` (2026-10-18), which rewrites the perf keys already in `config/sodium-options.json` back to Sodium's own fast defaults on every boosted launch (never creates the file; see the `sodium-options.json` section). |
| `game_options.py` | Frame-rate unlocker: flips ONLY `enableVsync`→false and `maxFps`→260 in `MINECRAFT_DIR/options.txt` (atomic, idempotent, no unknown keys). `apply_max_fps()` (FPS boost, ON by default) additionally sets the speed-only graphics keys AND, since 2026-10-18, the distance levers — `renderDistance` 6, `simulationDistance` 5, `mipmapLevels` 2, `renderClouds` "fast". `restore_vanilla_look()` writes every one of them back to 12/12/4/"true" plus fancy/ao-on when the boost is off. |
| `launch.py` | `launch_game()` — injects CSL + friends jar + **Fabric API** (via `cubeonfriends.ensure_fabric_api`, the HUD's dependency) + perf suite + frame-rate unlock, syncs mods, launches MC. `client_jvm_flags()` (CPU-aware, see below) + matched `-Xms/-Xmx` + RAM-gated `-XX:+AlwaysPreTouch`. Requires mc_version/loader, no silent defaults. |
| `capes.py` | Custom capes: any image accepted, auto-fitted onto the cape layout, synced into CSL's LocalSkin. Static images only — the animated-cape system was removed 2026-09-07. No Worker/KV involvement at all. |
| `config.py` | cfg schema, username validation, auth key (public_uuid/secret_token). |
| `gate.py` | Server join password (PBKDF2, escalating lockouts). |
| `eta.py` | Measured "time left" for downloads (`EtaEstimator`). There is no size to divide by (mll reports file COUNTS per phase, mod installs file units, content downloads bytes), so it samples how fast the fraction actually moves. Silent until ~2s and ≥1% of movement, recalculates from the last 30s, drops its history on a BACKWARDS jump (a new phase — libraries→assets, or the next file of a batch), stops promising after 15s of no progress, and never reports past 6h. Used by main.py's install label, the mods Download button, the modpack install line and the server plugin row. |
| `shortcuts.py` | The keyboard-shortcut decision table (pure, Flet-free): `resolve(key, ctrl=, alt=, shift=, meta=) -> action id`, `tab_action/tab_index`, and `CATALOGUE` (what main.py's F1 dialog renders). main.py's `_on_key` only dispatches — see the "Keyboard shortcuts + F11 fullscreen" invariant section. |
| `incident.py` | Crash forensics for the flet desktop client: `describe_exit(code)`, `crash_record(...)`/`record_session_end(...)`, `record_giving_up(...)`, `ClientOutputTail`, `wayland_x11_fallback(env)`. Pure/total — it only DESCRIBES a session end, main.py still owns recovery. See the "Flet client crash forensics" invariant section. |
| `status_text.py` | `human(text)` — strips Python object reprs (`<... at 0x7f...>`) out of anything user-facing. `str(requests.ConnectionError)` genuinely contains `<urllib3.connection.HTTPSConnection object at 0x7f3c8a1b2d90>: Failed to establish a new connection...`, which is what painted a memory address into the UI when a download failed. Applied in `net.py` when it builds `DownloadError`, and at the UI status/error setters. Only reprs are removed — hashes stay (they are diagnostic in an integrity error); the one meaningless bare hash, an asset's sha1 as a "file name", is fixed at the source by `versions.py:_FriendlyStatus` (→ "Downloading game assets (412/2586)"). |

## Facts that bite if you don't know them

- **mll's Java runtime is load-bearing (2026-10-17).** `install_jvm_runtime`
  downloads Mojang's JDK into the game directory and `mll.command` uses it
  whenever `options["executablePath"]` is absent — which is Cubeon's launch
  whenever `cfg["java_path"]` is empty. Only skip it via
  `install_version(..., explicit_java=True)`; see the 2026-10-17 install
  section for the full trap.

- **24 jars, not two (2026-10-15).** One jar per Minecraft version, 1.20 → 26.3,
  all through Gradle. `fabric-loom` + **Yarn** mappings (remapped to intermediary)
  for the obfuscated 1.20–1.21.11; loom's **no-remap marker plugin**
  (`net.fabricmc.fabric-loom`) with no `mappings` line for the unobfuscated 26.x.
  Which plugin is applied is derived from the bracket's `mappings` field — using
  the real plugin on 26.x fails with "Cannot use Mojang mappings in a
  non-obfuscated environment", using the marker on 1.20.x can't remap.
  - Every bracket needs **Fabric API** on the compile classpath (the HUD is built
    on `HudRenderCallback` / `HudElementRegistry` / `KeyBindingHelper`), which is
    why the old javac path is gone: javac cannot read Fabric API's nested module
    jars. The 26.x build fetches it too.
  - Every jar emits **Java 17** bytecode regardless of bracket, because
    `cubeon-client.mixins.json` declares `compatibilityLevel: JAVA_17` and Mixin
    refuses a mixin class newer than that. The *toolchain* that reads each
    Minecraft jar is per bracket (17 / 21 / 25).
  - **Gradle itself must RUN on a JDK 25+** (loom 1.18 requirement) while the
    system gradle here sits on 21. `tools/build_mod_jars.py` finds a 25+ JDK and
    sets `JAVA_HOME` for the build; running `gradlew` by hand needs
    `JAVA_HOME=/usr/lib/jvm/java-26-openjdk` or it dies during configuration.
  - **26.3 moved MC's input backend GLFW → SDL, so mouse button numbers change.**
    GLFW numbers buttons from 0 (left=0); SDL from 1 (`SDL_BUTTON_LEFT`=1,
    middle=2, right=3). `MouseHandler` still calls
    `Screen.mouseClicked(MouseButtonEvent, ...)`, so the API looks identical —
    but the 26.3 HUD's drag editor must grab on `event.button() == 1` while the
    GLFW overlays (1.20–1.21.9, 26.1, 26.2) keep `== 0`. Vanilla's own
    `ContainerEventHandler` moved its drag check to `event.button() == 1` for
    the same reason. The wrong number fails SILENTLY (the click never starts a
    drag, nothing can be moved) — the "can't move the widgets in 26.3" report.
    Guarded by `test_mod_matrix.py::test_mouse_buttons`.
  - The mod still compiles against a stub API subset (`tools/test_mod_compile.py`)
    — but the stub is written in **Mojang** names, so that test covers the
    `api-mojang` overlay only. The real per-version check is
    `python3 tools/build_mod_jars.py` (24 real builds). If javac fails on 26.x,
    the API moved; javap the real jar in `~/.minecraft/versions/26.1.2/26.1.2.jar`.
  - `KeyHud/` (the standalone mod this absorbed, 732 MB) is git-ignored and is
    **not** a source of truth any more — `mod/` is.
  - `launch_game` also calls `cubeonfriends.ensure_fabric_api`, which is a
    LOCAL check first (`fabric_api_installed` → `list_mods`) and only reaches
    Modrinth when the profile really has no Fabric API. Any suite that drives
    `launch_game` must stub it (`cubeonfriends.ensure_fabric_api = lambda *a,
    **k: ""`): in a sandboxed HOME the real one downloads, and
    `tools/test_launch_fixes.py`'s staging test failed on exactly that network
    wait instead of on what it tests.
- **Animated capes were REMOVED (2026-09-07).** Custom capes are static
  images only now: no `AnimatedCape.java`, no `.frames.json`, no
  `GET /cape/frames`, no `animated` flag in capes.json. If it ever comes
  back, the historical contract (CSL `(LOCAL_LEGACY)` texture-hash trap,
  1.21.x reflection traps) is documented in
  agents/2026-09-07_agent_animated-cape-static-fix.md and
  agents/2026-09-07_agent_flexible-animated-capes.md — read those before
  re-deriving anything, they cost real debugging time to learn.
- **Everything user-facing must degrade to a human sentence.** No blocking
  calls on the mod's request thread; no raw exception text in the UI; errors
  and confirmations both land via the notification ring → in-game chat.
- **Launcher jar vs game jar staleness is guarded**: `mod_stamp` in the roster
  payload vs the mod's own hash → one-shot red chat warning.
- **On-disk roots**: `~/.cubeon_launcher` (launcher state, cache, servers),
  `~/.cubeon_minecraft` (game dir: versions/mods/global_mods). `~/.minecraft`
  must NEVER be touched.
- **Packaged launchers have no `mod/build/libs`** — jars must exist in
  `assets/jars/`. `find_jar` order: cache → assets/jars → build/libs.
- **The live relay lags the repo.** Features needing new Worker behavior
  (e.g. the T_SYSTEM "No Cubeon user" reply) must degrade gracefully; never
  block a request thread on the relay.
- **UI text policy** (user preference, enforced 2026-09-04): minimal visible
  text, hints live in tooltips, sections collapse behind toggles, no jargon
  (no "API", no raw errors) anywhere visible.

## Tests — run these, in this order of relevance

```
python3 tools/test_seasonal.py           # 98: season tables + precedence + palette AA contrast
python3 tools/test_mega_smoke.py        # deep gate: syntax + imports + contracts + control flow + headless runtime
python3 tools/app_driver.py explore     # AI driver: use the app headless, JSON error/coverage report (`fuzz`, `script`, `shots`)
python3 tools/test_friends_service.py   # 213: service + bridge contract + identity + unique rename + chat tab
python3 tools/test_friends.py           # 37: relay client + worker parity
python3 tools/test_mod_bridge.py        # 137: reads Bridge.java, asserts launcher serves it
python3 tools/test_mod_compile.py       # mod source compiles vs the stub API subset
python3 tools/test_mod_matrix.py        # 206: brackets/jar routing + Fabric API install
python3 tools/test_capes.py             # 14: flexible capes + CSL sync
python3 tools/test_ui_smoke.py          # 148: tab builders build, invariants hold
python3 tools/test_invites.py           # 127: Minekube/tunnel flows
python3 tools/test_modpacks.py          # 66: pack installs
python3 tools/test_pack_install_guard.py # 28: a pack install claims its instance (no PLAY mid-install)
python3 tools/test_keyboard_shortcuts.py # 50: shortcut table + F11 fullscreen wiring
python3 tools/test_incident.py          # 74: crash forensics record + retry env ladder
python3 tools/test_update_notice.py     # 20: one update notice per version, one check
python3 tools/test_mod_store.py         # 27: global mod store
python3 tools/test_net.py               # 54: download retry/resume/cap + updater
python3 tools/test_production.py        # 51: watchdog
python3 tools/build_mod_jars.py         # rebuild mod jars -> cache + assets/jars
```

Harnesses are mostly hermetic (sandboxed HOME via CUBEON_GAME_DIR etc.), with
two exceptions worth knowing before you trust a red line:

- `test_mod_store.py` reads the ambient store, so it is only clean on a fresh
  `HOME` **and** `CUBEON_GAME_DIR` (24/3 on a warm sandbox is the artifact, not
  a regression).
- `CUBEON_GAME_DIR` **wins over HOME** in `cubeon/paths.py`, so a test that sets
  its own `HOME` must pop it too or it writes into the shared real game dir.
  `tools/test_csl.py` does exactly that.

The Workers' own tests are Node and **are not run by CI** — `node
worker/test-*.mjs`. They cover the security properties (`test-downloads.mjs`
asserts 100 downloads cost one GitHub API call), so run them by hand whenever
you touch `worker/`; `tools/test_web_download_count.py` is the Python half that
CI does run.

After ANY mod source change run `build_mod_jars.py` — stale deployed jars in
`~/.cubeon_launcher/cache/` are the classic "I fixed it but nothing changed"
trap (the mod now warns about it in chat, but don't rely on that).

## Where deeper docs live (agents/docs/)

`guide-cubeon-modules.md` (module deep-dive), `guide-worker-backend.md`
(relay protocol), `guide-data-flow.md` + `diagrams-flows.md` (flows),
`production-readiness-gaps.md` (known gaps), `phase2b-*.md` (P2P history).

## Open items (2026-09-04 production review)

1. Relay deployment pipeline — repo Worker code can be ahead of the live
   deployment; no version handshake exists yet. Deploy manually with
   `cd worker && npx wrangler deploy -c wrangler-friends.toml`
   (last done 2026-09-05, version 6b7ac883, repo == live as of then).
2. One live two-launcher in-game end-to-end run has never happened.
   (Launcher↔relay↔launcher IS proven live as of 2026-09-05 — see
   agents/2026-09-05_opencode_live-two-player-relay-verified.md. The
   in-game mod ↔ local bridge hop is the remaining unproven leg.)

## Production pass (2026-09-05, Cline) — what landed

- `cubeon/net.py`: downloads get retry+backoff (3 attempts, honors
  Retry-After), HTTP-Range RESUME via `.part` + atomic replace, hash
  verification covering prefix+tail, and a global 4-download gate. Wired into
  modpacks._stream_download, mods.download_mod, server.install_server
  (Paper). Contract: error message must contain "integrity" (test asserts).
  **2026-09-13 additions:** a lazy process-wide pooled `requests.Session`
  (connection/TLS reuse; `requests.get` makes a new Session per call),
  `net.get_json()` (retry-wrapped metadata/API GET — a blip must not read as
  "no matching file"), and `net._do_get` is now the SINGLE transport seam:
  production = pooled session, tests monkeypatch `net._do_get`. Harnesses that
  fake `requests.get` (test_modpacks) must route `net._do_get` back through it
  or they'll hit the real network.
  **2026-10-17 — a permanent 4xx now fails FAST:** `get_with_retry` retried
  everything, 404 included (its own docstring claimed otherwise), so a version
  that simply doesn't exist cost the user 1.5s+3s of backoff and then read
  `Couldn't reach <url> after 3 tries: 404 ...` — blaming the network for an
  answer. A 4xx other than 429 now closes the response and raises
  `net.HTTPStatusError` (a `DownloadError` subclass carrying `.status_code`) on
  the FIRST response, naming the status. Anything wrapping `net.get_json` that
  cares about a 404 must catch `net.HTTPStatusError`, NOT `requests.HTTPError`
  — that handler is unreachable, which is how the Paper 404 message stayed
  dead. Pinned by `tools/test_net.py` §_no_retry_on_404 /
  §_retry_on_429_never_on_403 / §_get_json_failure_is_clean. Note that
  §_no_retry_on_404 had been defined but never CALLED since it was written, so
  the regression it guards shipped silently — check new tests are actually
  invoked.
  **Also now wired:** `content.download_content` (resource packs + shaders —
  was the last bare single-attempt `requests.get`, hence the "network error"
  on install), `server.download_plugin`, `minekube` Connect plugin. Modpack
  mod-file downloads run in a `ThreadPoolExecutor(max_workers=4)` so the
  gate is actually used (the old serial loop made it decorative);
  `global_mod_cache` index writes + store-name choice are lock-guarded for
  that concurrency.
- **Gotcha: `tools/test_mod_store.py` is NOT hermetic - it uses the ambient game
  dir instead of one of its own.** Three of its checks assert the store holds
  *exactly one file*, so on a REUSED sandbox (a `CUBEON_GAME_DIR` other suites
  have already installed into - the HUD jar alone is enough) they fail with a
  listing of every leftover jar. `24 passed, 3 failed` on a warm sandbox is
  therefore expected and is **not** a regression; `27 passed, 0 failed` on a
  fresh `HOME` + `CUBEON_GAME_DIR` is the real result. That is why
  `test_mega_smoke.py --suites` goes red on that one suite after a few runs
  while CI (a virgin sandbox per job) stays green. Fix = point the test at its
  own store dir. Reported, not changed.
- `cubeon/logging_setup.py`: rotating file log at
  `~/.cubeon_launcher/cubeon.log` (5MB x3), sys/threading excepthooks, and
  `diagnostics_text()` for bug reports. setup_logging() is idempotent; call
  it EARLY in main().
- `cubeon/updater.py`: APP_VERSION constant (bump per release!), release-feed
  check via `CUBEON_UPDATE_FEED` override, `check_in_background()`; main.py
  shows a non-blocking snackbar with a "Get it" button on a newer release.
  **"Get it" opens `updater.DOWNLOAD_URL` (cubeon.ylet.online/download), never
  the release's own `html_url`** - see the private-repo note below.
- CI: `.github/workflows/build.yml` now has a `test` job running every
  tools/test_*.py (Java 21 for test_mod_compile) before builds.

## Production pass 2 (2026-09-05, Cline) — items 6-14

- **Relay abuse guards** (#6): `limiterAllow` (pure, exported) + Hub.allow —
  120 frames/min per user (silent drop), 10 friend-requests/min per user
  (T_ERROR `rate_limited`, human message). In-memory per DO, deliberately
  not SQLite. `wrangler deploy` needed to go live!
- **Crash reporting REMOVED (2026-09-20, user request)**: `cubeon/crashreport.py`
  and the Settings > Privacy section are gone. Uncaught exceptions are still
  written to the rotating log by `logging_setup._install_excepthooks()`, but
  nothing is ever sent anywhere. `setup_logging()` no longer takes a crash_cfg.
  Do NOT reintroduce a network crash reporter or a Privacy settings pane.
- **Game watchdog** (#9): `cubeon/watchdog.py` — running_game.json record at
  launch, cleared on confirmed exit; `stale_session()` at startup detects an
  orphaned game and the launcher offers a "Close it" snackbar. Never raises.
- **macOS CI build** (#11): inline PyInstaller on macos-latest. DISCOVERY:
  `packaging/` scripts (build_appimage.sh, build_windows.py) DO NOT EXIST in
  the repo — the Windows/Linux build jobs reference them and will fail.
  Either restore those scripts or convert those jobs to inline PyInstaller
  (copy the macOS job; `--add-data "assets:assets"` is mandatory).
- **Onboarding** (#10): first-run dialog (no "onboarded" cfg key) asking for
  the in-game name; reuses on_profile_username_change for validation/skin
  sync/avatars, then sets cfg["onboarded"].
- **Skipped**: #8 code signing (needs a paid cert - user only), #12
  minimize-to-tray (Flet window-API risk) and background toasts (needs
  hooking every download site - medium), #13 i18n/accessibility (high effort).
- New tests: tools/test_production.py (13). Worker: node worker/test-worker.mjs.

## Follow-up 21: cosmetics = LOCAL library folders (2026-09-14, replaces the real-player gallery)

The Mojang "browse REAL players" system was REMOVED by user request (2026-09-14).
Browse is now two local drop-folders; the only network skin path left is the
skins-worker publish (cubeon/skins.py, worker/cubeon-skins.js).

- **cubeon/gallery.py (reworked)**: the catalog is the contents of
  `~/.cubeon_launcher/skin_library/` and `~/.cubeon_launcher/cape_library/`
  (image extensions png/jpg/jpeg/webp/gif/bmp). One item per file; `id` = file
  name; fuzzy search over stems (`_norm`/`_match_score`); previews rendered
  from the actual pixels once and cached under `gallery/previews/` (memoized
  per folder signature in `_CATALOG_MEMO`). `install_gallery_skin/cape`
  run the file through the exact upload pipeline (`_skins.add_custom_skin` /
  `_capes.add_custom_cape`) and wear it. `gallery_id_for_file/forget_file/
  ensure_gallery` keep their shapes. The old featured/Mojang names
  (`featured_count`, `featured_cached_count`, `prefetch_featured`,
  `suggest_player`, `load_player`) remain exported as honest no-op stubs
  because launcher_core re-exports them and harnesses probe them.
- **cubeon/remotes.py**: dead code - nothing imports it anymore. Kept in the
  tree (test_skins_net.py does NOT cover it; it tests skins.py). Do NOT call
  it from new code.
- **ui/skin_tab.py**: hat/Cosmetics pane REMOVED entirely (user: "remove the
  hat BROWSE shit too") - the section is Skin | Cape panes only, and
  `build_skin_section` no longer takes `start_prefetch`. Each Browse pane has
  a search box + an "open folder" button (`_open_folder` -> xdg-open/open/
  os.startfile). `core.ensure_gallery()` runs at every section build so the
  drop-folders exist on first run. `cubeon/cosmetics.py` hat drawing helpers
  still exist (launcher_core re-exports) but have no UI.
- **build_skin_section signature**: `(..., file_picker, cape_file_picker)` -
  NO `start_prefetch`. test_ui_smoke's six call sites were updated.
- **Front/Back preview switch (2026-10-18)**: the Skin pane's "CURRENT LOOK"
  box has a Front/Back segmented switch (hidden until a custom skin is
  active - a control that changes nothing is worse than none). The back view is
  a REAL 180° turn, not a cosmetic flip: `render_local_skin_preview(..., view=)`
  composites the sheet's BACK-face regions and swaps the two sides, because
  that is exactly what turning a body half around does. Back-face origins are a
  fixed offset right of the front ones on a 64x64 sheet - head +16, torso +12,
  limbs +8 (the right-then-front-then-left-then-back order of every box) - and a
  legacy 64x32 sheet defines NO back faces, so there the crops stay on the
  front and only the side swap happens (never invent pixels). The view is read
  from `_view_state` at RENDER time (not when queued), so a fast toggle lands
  on the side the user last chose; the cached PNG per view is
  `_preview_<view>_<filename>.png` so flipping back and forth cannot race one
  file. Default stays `front`, so the gallery/thumb callers are unchanged.
  Regression: `tools/test_skin_preview.py` (geometry + legacy + predicate) and
  the `test_ui_smoke.py` probe that proves the switch reaches the renderer.
- **Tests**: test_gallery.py rewritten for the local-library pipeline (25
  checks); test_ui_smoke hat checks replaced with "hat browse is gone" and
  the search/pane-flip checks re-pointed at the local library ("your skin
  library folder" caption).
- GOTCHA from the 2026-09-13 session: a mid-refactor skin_tab.py shipped to
  the user's RUNNING launcher and crashed with `NameError: _img_b64` at
  import-time call `refresh_skins_list()` (line ~429) - in the current tree
  `_img_b64` is defined INSIDE build_skin_section at line ~312, before the
  first statement-level `refresh_skins_list()` call, which is correct. If you
  move those defs, check statement-call order, not just name resolution.

Still-true invariants from the pre-local era:

- **Installed lists show previews as a wrapping card grid (2026-09-11)**:
  `_owned_card(...)` builds each card (real preview via `_skin_card_b64` /
  `_cape_card_b64`, name, optional sublabel, hover-revealed Use/Delete, and an
  accent border + ACTIVE pill for the active item). `skins_list_col` /
  `capes_list_col` are `ft.Row(wrap=True)` grids; the built-in Cubeon cape is
  the first card (no delete, `on_delete=None`). `_grid_scroll(grid, height=290)`
  wraps a grid in a fixed-height scrolling Column so a long list never
  stretches the tab. NO pager anywhere in the cosmetics tab.

- **Cosmetics theming matches the Mods tab (2026-09-11)**: the tab used to be
  the only one wrapped in its own bordered SURFACE card in `main.py`, and every
  inner stage/tile was another solid bordered box - i.e. "box in a box".
  `main.py`'s `profile_tab` is now a plain `ft.Column([skin_section_container])`
  (padded by the tab switcher), exactly like Mods/Stats/Settings. `ui/skin_tab.py`
  paints its panels with the Mods-tab translucent tokens: stages / tiles / cards
  use `CARD_FILL` + `CARD_BORDER` (no more solid `SURFACE`/`SURFACE_HI` + hard
  `BORDER`/2px `ACCENT_DIM`), cards/tiles lift to `ROW_HOVER` on hover and
  selected hats/cards wash with `ACCENT_TINT`; the search fields use
  `CARD_FILL`/`CARD_BORDER` + `focused_border_color=ACCENT_DIM` + faint hints.
  Reuse these tokens when adding new cosmetics surfaces - do NOT reintroduce a
  solid nested panel.

- **Cosmetics-tab open freeze (fixed 2026-09-21):** `refresh_profile_tab()` /
  `rebuild_skin_section()` (main.py) used to call `build_skin_section()` from
  scratch on EVERY visit — measured ~130-150 ms of control construction plus a
  full subtree re-serialization to the client (the "freezes for a moment when I
  open Cosmetics" report). The section is now CACHED in
  `skin_section_container` and rebuilt only when its inputs change: the key is
  `(version_dropdown.value or cfg["last_version"], state["mod_loader"])` —
  exactly the two values the rebuild exists to track (the CSL status tooltip).
  The section's own handlers (upload/use/delete) refresh their lists in place,
  so nothing goes stale between visits; `_THUMB_MEMO`/`_IMG_MEMO` now survive
  across visits too, so thumbs are instant instead of placeholder-pop. Do NOT
  revert this to a per-visit rebuild; if a "stale cosmetics" report arrives,
  check the cache key inputs first.
- **Browse/Installed visibility BUG (fixed 2026-09-10)**: `_view_tabs`'
  `switch_view` used to update `view_state` + the tab highlight but NOT the
  two columns' `.visible`, so clicking "Installed" moved the underline and
  left Browse on screen - users reported "Installed shows nothing". The
  columns now register in `view_panes` and `_apply_view(pane_id)` flips
  `.visible`. Keep that registry when touching the pane builders.

- **Browse grid is built ONCE, search flips `.visible` (2026-09-11)**:
  `refresh_skin_gallery`/`refresh_cape_gallery` used to `controls.clear()` +
  re-render + re-base64 every preview on each keystroke (janky search, image
  flicker), and the empty-result state offered a "Look up ... on Mojang"
  button (removed). They now build all tiles once from `gallery.all_gallery_items`
  (cached + uncached recommended, memoized per cache signature), stash
  `{skin,cape}_gid` on each tile's `.data`, and toggle `.visible` via
  `gallery.matches_query`. The module-level `_img_b64` memoizes base64 by
  path+mtime. Install/delete paths reset the `{skin,cape}_tiles_sig` dict to
  force the one rebuild that reflects the new INSTALLED pill. `skin_empty_hint`/
  `cape_empty_hint` carry the "no match / still loading" line so install status
  text in `*_browse_status` is not clobbered. Both browse grids also sit in
  `_grid_scroll(...)` so a long result set scrolls inside a fixed-height region
  instead of stretching the tab.

- **HONEST LIMIT - there is NO hat API.** Vanilla Minecraft has no hat slot;
  hats are pixel art the launcher paints into the skin's hat layer, and they
  are only visible to you (like a custom skin), not other players.
- **List functions must stay network-free**: refresh_*_gallery in skin_tab
  runs at build time; remotes.cached_player_ids + _snapshot_from_profile must
  never hit the network (they short-circuit on fresh cache). Keep it that way.
- **os.path.isfile(None) crashes**: _snapshot_from_profile must guard paths
  with `path and os.path.isfile(path)` - a player with no cape has cape_path
  None.

## Follow-up 20: frozen builds need flet_desktop bundled (2026-09-05)

- **Invariant: `--collect-all flet` is NOT enough for PyInstaller builds** —
  `flet_desktop` is a separate wheel; without `--collect-all flet_desktop`
  the frozen exe tries to pip-install at runtime and exits before a window
  ( symptom: exe closes instantly).
- The PyPI `flet-desktop` wheel ships `flet_desktop/app/` EMPTY — the window
  binary downloads from GitHub Releases on first run. All packaging scripts
  now fetch the client archive at BUILD time into the interpreter's
  `flet_desktop/app/` (that's `get_package_bin_dir()`, the first place
  `ensure_client_cached()` looks), so first run works offline.
- Artifact filename is platform-specific: use
  `flet_desktop.get_artifact_filename()`, not a hardcoded name.
- Windows builds also pass `--windowed` now.

## Follow-up 19: KV write-quota storm (2026-09-05)

- **Invariant: Cloudflare KV writes are ACCOUNT-WIDE (1k/day free tier)
  across ALL workers** — waitlist, skins, invites share one budget. A
  spammy client of any worker starves them all; budget resets 00:00 UTC.
- The username field's on_change fires PER KEYSTROKE → each used to run
  the full skin publish (heartbeat POST). Stale skin_net.json → retried
  forever. Fix: debounce rename publishes in main.py (1.2s/on-blur) AND a
  10-min failure cooldown in skins.py (`retry_not_before` in
  skin_net.json). Both layers are needed.
- Workers translate quota-thrown KV puts into clean 429s (never 500/
  1101): see handleJoin (waitlist), ownsUuid/handleHeartbeat/
  handleSkinUpload (skins). Clients treat non-200 as cool-off.
- Deploy commands: `cd worker && npx wrangler deploy -c wrangler-<name>.toml`
  — configs now exist for friends, waitlist, AND skins (skins previously
  had no repo config; its KV id is in wrangler-skins.toml).
- The site lives in `web/` and is deployed on **Vercel at `cubeon.vercel.app`**
  (project root = `web/`, so `web/vercel.json` + `web/_redirects` are the live
  route tables and `web/api/*.js` are the serverless functions). Still NO build
  step. Pages sharing `web/assets/site.css` + `web/assets/site.js`: `index.html`
  = landing (story), `download.html` = the files, `benchmarks.html` = the measured
  FPS comparison, `help.html` = the manual, plus `404.html` and the legal pages
  (cookies / licenses / privacy / refunds / terms). The navbar is
  Home / Download / Benchmarks / Help / Discord / Get Cubeon on every page. They cross-link by clean route (`/download`, `/help`, ...) and mark
  the current page with `aria-current="page"` (the old `docs.html` name and the
  `download.html#files` / `docs.html#faq` fragments are GONE). `site.js` is
  shared verbatim: every block bails out when the page lacks its elements (the
  sky canvas + roster only exist on the landing page).
- **EVERY page must load `assets/site.js`** - the page itself is the wiring, and
  a page that forgets the tag loses the counter, the cookie note and the mobile
  menu while still looking fine in review. `index.html` shipped exactly that way
  until 2026-09-22: it kept an inline copy of the old OS-detect + FAQ behaviour
  and never loaded site.js, so the landing page (the one with the download
  buttons AND the counter) showed nothing. The landing-only pane switching
  (`html.js .pane` hidden until a pane carries `.on`, the "Not your system?"
  buttons) now lives in site.js's `markSystem` block. `tools/test_web_download_count.py`
  now fails if any `web/*.html` lacks the tag or keeps a second copy of a handler.
- **Landing page (rebuilt 2026-10-13)**: `web/index.html` is the full design-system
  page now — shared `navbar` (Home/Download/Benchmarks/Help/Discord/Get Cubeon) + `.hero`
  (grass/dirt split, OS-pane picker, `.shot`) + `.strip` facts + `.cards` features
  + `.steps` how-to + `.faq` + closing `.cta` + fine-print cards + footer. It keeps
  four things `tools/test_web_download_count.py` asserts verbatim: the
  `<script …assets/site.js>` tag, a hidden `<p data-download-count>`, the class
  `discord-cta`, and the Discord invite `https://discord.gg/Vj7g7vVY8K` (subpages
  need `nav-discord`, index is exempt but carries it too). All interactive
  behaviour (menu, FAQ, OS panes, counter) is site.js only — never inline.
- **`web/benchmarks.html` (added 2026-10-16)**: the measured-FPS comparison
  (Cubeon vs SKLauncher vs FastClient, Minecraft 1.21.11, Xeon E5-1650 / RX 580).
  The numbers' source of truth is `benchmarks/Minecraft_FPS_Report-1.pdf`
  (8 pages, written 2026-10-15), copied verbatim to
  `web/assets/Minecraft-FPS-Report.pdf` and linked twice (download + open in tab).
  The page draws its own bars in CSS (the `.bm-*` rules at the end of
  `web/assets/site.css`): a bar's width IS its number, scaled to the fastest run
  in that same chart, and the exact value is printed beside it, so no figure has
  to be read off a pixel. The full stats table sits in `.bm-scroll` (min-width
  640px) so it scrolls on a phone instead of squashing. The "Read it honestly"
  section is deliberate and must stay: SKLauncher ran vanilla with no Sodium,
  F3 was on for two of the three launchers, and each run was in a different
  world spot. `index.html` links it from the "Is it fast?" FAQ entry and the
  "Every version, ready" card; `help.html` links it from a frame-rate answer.
- The download-count guard in that test only rejects **per-device count**
  storage: since `2aeae94` the counter block legitimately touches localStorage
  for its testing-mode flag (`TEST_FLAG` lines, Ctrl+Shift+T / `?nocount=1`).
  The check greps `localStorage.` lines excluding `TEST_FLAG` (fixed 2026-10-13;
  it had been red since that commit).
- Site verification gotcha: headless Chrome (`google-chrome-stable --headless
  --screenshot --window-size=W,H`) has a **500px minimum window width** — a
  390px shot silently renders at 500px and crops, which looks like horizontal
  overflow. Real narrow-layout checks: shoot at 500px, or inject a probe that
  reports `innerWidth`/`scrollWidth` via `--dump-dom`.
- **Never pair a `/page` → `/page.html` redirect with `cleanUrls: true`** (both
  `web/vercel.json` and the repo-root one): the host already serves the page at
  the extensionless path and rewrites `/page.html` back to `/page`, so the rule
  becomes ERR_TOO_MANY_REDIRECTS. That shipped for `/download`, `/help` and
  `/404` (2026-09-22, removed - the legal pages proved cleanUrls alone works).
  Only the `/<os>download` release-asset routes belong in the redirect list; a
  test asserts no such loop and that all four asset routes survive.
- Every SITE download is a plain anchor to a clean route — `/windowsdownload`,
  `/linuxdownload`, `/linuxdeb`, `/linuxsetup` — which Vercel 307s to the GitHub
  release asset named in `web/vercel.json`; the old `../dist/<file>` hrefs are
  gone (`dist/` is gitignored and absent from the deploy). The public UI offers
  the Windows installer and the Linux trio; macOS is an honest "not available
  yet" card. Byte sizes printed in the cards are hand-written — re-check them
  after any rebuild. Measured against the v1.0.4 artifacts (2026-10-13):
  installer 119,878,260 B → "120 MB", AppImage 108,034,552 B → "108 MB",
  deb 114,504,390 B → "114 MB", setup.sh 1,341 B → "1 KB" (decimal MB).
  **The Worker's `/linuxdeb` resolves the deb by prefix, not by a literal
  name**: `FILES["/linuxdeb"]` is `{ prefix: "cubeon_", suffix: "_amd64.deb" }`
  and `pickLatestPrefixed()` picks the highest version present (compared
  numerically per segment, so `1.0.10` beats `1.0.9`). It previously pinned the
  literal `cubeon_1.0.0_amd64.deb`, so every version bump that renamed the deb
  silently 404'd that route — the 1.0.4 bump did exactly that, patched around
  at the time by re-uploading the new bytes under the old name. **After a
  version bump: just upload the normally-named deb and deploy the Worker —
  no alias and no filename edit are needed.** The three other routes are
  version-agnostic literals and stay as they are.
- **What the site may claim about multiplayer (audited 2026-10-13 against the
  code):** the short-code invite system (`docs/protocols/invites-api.md`,
  `cubeon/invites.py`, the invites Worker) has **no UI anywhere** — the doc
  itself says "Nothing calls it until the host UI lands". The real shipped
  flow is the in-game friends list (mod `CubeonClientScreen`): per-friend row
  buttons **Invite / Join / Ask to join**, plus the launcher Servers tab
  (install a local server → free public Minekube address + join password +
  whitelist). "Groups" exist only as frames in `cubeon/friends.py` (no UI);
  "voice" is signalling-only behind the optional `cubeon/voice.py` add-on
  ("voice UI was removed" — see friends_service.py). Chat = the launcher Chat
  tab, which only appears when `friends_enabled()` is true. Site copy
  (index/help/download) was corrected to match; don't reintroduce "press Host
  and send a short code" phrasing until that UI actually ships.
- **The GitHub repo is PRIVATE** (anonymous `github.com/Shadow-457/Cubeon` → 404,
  and anonymous `releases/latest/download/<asset>` → an auth wall too). Visitors
  get the files through the `cubeon-downloads` Worker instead — see the direct
  downloads bullet below. It is also why the page cannot ask GitHub anything
  directly.
- **Release download count on the site (2026-09-22, v2)**: `index.html` and
  `download.html` carry `<p class="download-count" data-download-count hidden>`;
  `site.js` shows the SHARED number of download-button presses for everyone: on
  load it reads Abacus (`https://abacus.jasoncameron.dev/get/cubeon-site/downloads`,
  an open-source cookieless counter) and on a press it calls `/hit` with
  `keepalive: true` so the +1 survives the jump to the release file. A global
  count cannot live in a browser, so this is the one outside request the site
  makes - cookies.html and privacy.html disclose it (a test enforces that they
  do). A failed lookup hides the line; 0 is shown as a real 0. The v1
  GitHub-count plumbing (web/api/download-count.js, download-count.json,
  the scheduled workflow, tools/refresh_download_count.py) was REMOVED the same
  day at the owner's direction - recoverable from git history around commit
  `ddc5374`. Guard: `tools/test_web_download_count.py` (real site.js in Node on
  a DOM stub, zero network).
- **Direct downloads (2026-09-22)**: the repo is PRIVATE, so GitHub's release
  URLs are an auth wall for visitors and signed asset URLs minted from a
  session expire within the hour (one was briefly committed to web/vercel.json
  by mistake). The `cubeon-downloads` Worker (worker/cubeon-downloads.js +
  wrangler-downloads.toml) holds a read-only `GITHUB_TOKEN` as a Worker secret
  and streams the latest release's four installer files straight out with
  `Content-Disposition: attachment`; web/vercel.json + web/_redirects point the
  four `/<os>download` routes at it. The counter's ROUTES in site.js, the
  vercel.json sources and the Worker's FILES list must stay in lockstep - a
  test asserts all three agree.
- The waitlist form + "In line" counter are gone from the site (the
  `worker/cubeon-waitlist.js` Worker still deploys but has no caller). JS only
  stars the button/card matching the visitor's OS with `.rec` — with scripting
  off both pages are still fully usable. Class names that came with the rename:
  `#oven` → `#release`, `.oven*`/`.trays`/`.tray*` → `.board*`/`.tiles`/`.tile*`,
  and `.wl*`/`.countline`/`.countbar` → `.dl-hero*`/`.dl-note`/`.dl-*`.
- `@font-face` in `site.css` must stay `url('fonts/Minecraftia-Regular.ttf')` —
  CSS-relative, NOT `assets/fonts/...` (that path 404s now that the font is
  reached through the stylesheet instead of the page).

## Follow-up 18: live UI inspector (2026-09-05)

- `cubeon/inspector.py`: dev-only DevTools for the launcher's own Flet UI.
  CUBEON_INSPECT=1 gates it (public builds never show it). Opens via
  sidebar bug button or F12. Tree browse + text search + live edit of
  Text.value/size/color/weight and tooltip — session-only, points at the
  source string to change for real. Note: this repo's Flet 0.86 uses
  `ft.padding.Padding.only` / `ft.border.Border.all` (NOT ft.padding.only /
  ft.border.all) — got me twice; update() on unmounted controls raises
  RuntimeError, so use the module's _safe_update().

## Follow-up 17: public-build launch crash (2026-09-05)

- Public builds (Friends disabled via features.py) set
  `friends_service = None` in main.py; the launch path called
  `friends_service.set_version(version_id)` unguarded → AttributeError
  AFTER the game process spawned (so MC still started, error spooked the
  user). Fixed with the same `is not None` guard the on_exit path had;
  regression check added to tools/test_ui_smoke.py.
- **Invariant: every friends_service reference outside the
  friends_enabled() block must tolerate None** — public builds are a
  first-class configuration, not an edge case. test_ui_smoke now asserts
  the guard textually.

## Mod in-game UI (2026-09-08; menu removed 2026-09-11) — durable facts
- **The full Cubeon in-game menu is GONE** (Profile/Skins/Capes/Cosmetics/
  Statistics/Chat/Online). It was `CubeonMenuScreen.java` plus the per-era
  overlay `CharacterView.java` + `mixin/CubeonMenuRenderMixin`. All five files
  were deleted, the mixin deregistered, and both `PauseScreenMixin` and
  `TitleScreenMixin` now add ONLY the Friends corner icon
  (`CubeonClientScreen.menuButton`). Do not reintroduce a second menu button
  under the Friends icon. The overlays still exist for `CornerIcon` (the
  Friends glyph), which is unrelated to the menu.
- **authlib split**: GameProfile is a record on 26 (`.name()`) but a class on
  1.20.1 (`.getName()`), and PlayerInfo exposes no name — WorldPlayers resolves
  it reflectively. Do not "simplify" that back to a direct call.
- New bridge endpoint GET `/players` (local_api.py `_providers["players"]` ←
  `FriendsService.players_payload`). Fail-soft contract: no provider or a raise
  must answer an empty `players` list, never a 404 the mod crashes on; the mod
  treats null/empty as "nothing known". Skin/cape are display strings only —
  the launcher never ships pixels over the bridge; a friend's skin lives on
  their launcher.
- test_mod_compile's stub includes LivingEntity, ClientPacketListener,
  PlayerInfo, GameProfile and Minecraft.getConnection() for WorldPlayers. The
  now-removed character preview's GuiGraphics + InventoryScreen stubs were
  deleted with the menu.

## Mod bridge hardening (2026-09-19) — durable facts
- `Bridge` is the only localhost transport. It validates the token file's port
  and header-safe token, fingerprints both file mtime and size, invalidates a
  token after HTTP 401, accepts only 2xx `{"ok": true}` action responses, and
  caps response parsing at 1 MB. Chat/sync query values must stay URL-encoded.
- A temporary `/status` failure retains the last session for two polls, then
  clears it; `/friends` remains the liveness check. Event cursors accept only
  finite non-negative integers, while a valid lower cursor is treated as a
  launcher restart so notifications recover after the launcher restarts.
- `CubeonClientScreen` owns a stable notice callback and clears it with
  compare-and-set on close. An old screen therefore cannot silence a newer
  screen during a close/reopen transition; Sync teardown uses the same
  expected-owner guard. The bridge poller resets its own thread handle in
  `finally`, so a later screen can restart it after an interruption or
  unexpected failure.
- Guards: `tools/test_mod_bridge.py` / `mod/tools/SelfTest.java` cover 8-digit
  IDs, port validation, HTTP status handling, cursor poisoning, and malformed
  chat sequences; `tools/test_mod_compile.py` covers the cross-version UI API.

## Mid-session GPU-crash auto-recovery (2026-09-08; discriminator fixed 2026-09-11)
- The Mesa 26.1/libgallium SIGSEGV also happens **mid-session** (during a GTK
  paint), not just pre-paint. A pre-paint death is retried in-process (safe:
  the engine never initialized); a mid-session death must NOT re-run ft.run
  (once-per-process → silent hang). `_session_loop` classifies the end via
  `_classify_session_end(ui_painted, client_exit)` → arm `use_software_gl`,
  bump `CUBEON_GPU_RESTARTS` (env, survives execv, reset on clean close) and
  **re-exec the whole launcher** (the tray-reopen trick), max 2 restarts, then
  park like a user close.
- **The old discriminator was wrong and made every close reopen the window
  (fixed 2026-09-11, live bug).** `_kill_flet_client()` returning "a live flet
  child" can NEVER be true: flet 0.86's `ft.run()` reaps the desktop client
  itself (`await fvp.wait()` inside `flet/app.py`) and only returns after the
  child is gone. So the "live child = user close / no child = crash" test always
  said "crash" and re-exec'd on every normal X-close. The reliable signal is the
  client's **exit status**, captured by `_capture_flet_client_exit()`, which
  wraps `flet_desktop.open_flet_view_async` so the process object's `.wait()`
  records `returncode` while flet awaits it: `0` (or any `>=0`) = normal close,
  negative = signal death (`-11` SIGSEGV, `-6` SIGABRT), `None` = unobservable →
  treat as clean close (never a surprise relaunch). Verified live under Xvfb:
  window close → 0 → exits with no relaunch; `kill -SEGV` on the client → -11 →
  restarts with software GL. Regression covered by `test_ui_smoke.py` §4b.
  **A client that exited 0 is ALWAYS a clean close (2026-10-13)**, even when
  the `ui_painted_ok` marker is missing: the marker write in `_reveal_window`
  is OSError-swallowed best-effort, and "marker lost + exit 0 → pre_paint_crash
  → software-GL retry" was the second "Cubeon reopens after I close it" bug
  (first was the live-child test above; third was the wedge false positive —
  see the burst-gap note). Signal (<0) still classifies by the marker.
- `_kill_flet_client()` is kept only as a best-effort ghost-window cleanup; its
  return value no longer classifies the session. Zombie flet children are still
  excluded from the scan (state `fields[0]` of /proc stat after
  `rpartition(b")")`).
- The parked `_reopen.wait(timeout=30)` can be interrupted by flet's
  exit_gracefully handler after the asyncio loop closed → spurious
  "Event loop is closed" RuntimeError (logged CRITICAL cubeon.fatal twice
  live). Now caught: teardown noise, treated as quit.
- **The software-GL fallback must NEVER reach the game** (2026-09-08, live
  bug: Minecraft ran at 4 FPS). The launcher's `LIBGL_ALWAYS_SOFTWARE=1` +
  `GALLIUM_DRIVER=llvmpipe` used to be inherited by the java child (verified
  in /proc/<pid>/environ). Two guards: (1) `cubeon/launch.py` strips
  `LIBGL_ALWAYS_SOFTWARE`/`GALLIUM_DRIVER`/`LIBGL_DRM_DEVICE` from the game
  env; (2) `_reveal_window` deletes the `use_software_gl` marker as soon as
  the UI paints (the fallback only needs to survive until first paint, not
  until clean close — waiting let it linger armed across kills/crashes).
- **Not every /dev/input/js* is a gamepad** (2026-09-08, live bug: "🎮 Baseus
  K03 Keyboard connected"). Some keyboards expose a js HID interface (that
  one: 3 buttons, 1 axis) for media keys. `cubeon/controller.py` now probes
  each device's INIT-event shape (`_probe_shape`) and gates it through
  `_looks_like_gamepad(name, buttons, axes)`: keyboard/mouse-named devices
  are refused outright; named pads need ≥4 buttons; unnamed devices need
  ≥8 buttons + ≥4 axes. Rejected paths go to `_rejected` so the 2s scan
  doesn't re-probe them. Verified against the real js0 on this box.
- **No Material ink ripples** (user preference, 2026-09-08): every clickable
  `ft.Container` uses `ink=False`. ui_smoke §10 asserts no `ink=True` /
  `ink=not ` anywhere in main.py, ui/*.py, cubeon/theme.py, cubeon/inspector.py
  (archive/ and ui_new/preview.py are exempt: dead dist copies and the
  --new-ui mock).
- **Account panel toggles must diff, not page.update()** (2026-09-08): the
  open/close handlers repaint ONLY the two overlays via
  `thread_safe_ui.refresh(account_scrim)` + `refresh(account_panel)`. A
  `page.update()` there re-synced every mounted control — user saw the whole
  app "reload" on each panel toggle. General rule for animation-y overlay
  choreography: always per-control refreshes. ui_smoke §10 asserts no raw
  `page.update()` line inside the two handlers.
- **Tab switching stays an INSTANT content cut; only the top bar's affordance
  animates** (2026-10-16, user ask "animate the top tab switcher"). `TAB_FADE_MS
  = 0` — the cross-fade has now been tried TWICE and rejected twice: 220ms in the
  2026-09-09 pass ("sloppy rendering") and 170ms in this one ("stucky buggy and
  not smooth"). Do not bring it back a third time; two live tab trees animating
  at once is what the user is seeing, and `switch_tab` is a whole-tree diff.
  The active affordance animates in three parts at once, all sharing
  `NAV_ANIM = ft.Animation(150, EASE_OUT_CUBIC)` so the switch reads as one
  gesture:
    * the green underline GROWS as a **paint-only `scale_x` 0↔1, centred**
      (`ft.Scale(scale_x=…, alignment=ft.Alignment.CENTER)`), with `width`
      pinned at 24. Animating the real `width` (the first cut) reflowed the
      centred nav row 1–2px per frame — that WAS the stutter.
    * the icon lifts (`animate_scale`, 0.94↔1.0).
    * the tint fades (the button's `animate`).
  `switch_tab`'s tail is STILL a scoped diff —
  `thread_safe_ui.refresh(tab_switcher)` + `refresh(subnav_bar)` + per-nav-button
  refreshes, never `page.update()`. Keep it that way.
  Measured in the FakePage harness: steady-state switch = 0 page.update calls.
- **Download progress is throttled at the SOURCE** (2026-09-09 efficiency
  pass): `net.stream_to_file` fires progress_cb per 64 KiB chunk — hundreds
  of UI repaints/sec on fast links. It now emits at most every 33ms OR every
  1% of the file, with one guaranteed final callback carrying the exact byte
  count (resume/hash callers rely on that). Measured: a 100 MB instant
  download = 101 callbacks (was 1600). All progress bars route through this
  (version installs, mods, modpacks).
- **Worldgate (2026-09-12): the LAN-world password gates the OFFER, not the
  invite.** Host states: hosting_wait_port -> gate_wait (mod prompt) ->
  ringing_out -> (accept) verifying -> connected. Joiner: connecting ->
  password_needed -> connecting. Signal kinds: gate_challenge/gate_proof/
  gate_fail (carries the FRESH nonce + salt for the next round)/gate_ok.
  MAX_ATTEMPTS=3 then the room closes; a 60s watchdog closes an
  unanswered round; the password (hash included) never touches disk.
  The offer precedes any fallback decision, so the gate covers both.
- **Mod-diff report calls out version clashes (2026-09-12):** the sync
  report's missing-mod list splits a mod the joiner HAS at a different
  hash into its own "You have a DIFFERENT version of" block, by matching
  filename stems (_mod_stem: tokens before the first digit-led one).
  Purely presentational - never gates can_download. The Fix-button
  label in the mod is now "Fix" (was "Download mods").
- **LAN worlds NEVER hand the joiner to Minekube (2026-09-12, behavior
  change).** connect-spigot is a tunnel for the host's PAPER SERVER (verified
  in the shipped jar - no target/local-port config key), so a joiner pointed
  at <endpoint>.play.minekube.net would land in the server's world, not the
  LAN world. `_switch_to_minekube` now only ANNOUNCES the address into the
  host's Minecraft chat (copyable, labelled as the server); the punch-failed
  session stays on Cubeon's relay, which carries the world correctly. The
  joiner's `p2p_use_minekube` handler is kept for OLD-launcher hosts.
- **Address into Minecraft chat:** `FriendsService.notify_active()` (class
  seam; `_active` set in start(), cleared in stop()) lets any module push a
  line into the mod's event ring - the Server tab's public-address watcher
  uses it, one line per resolved address. Host also gets world-live lines at
  worldgate_set; the password is never echoed into chat (streamers).
- **P2P outbound loop is event-driven** (2026-09-09): `_tcp_outbound_loop`
  polled `time.sleep(0.01)` forever (~100 wakeups/sec per session). Now waits
  on `_outbound_wake` (Condition on `_state_lock`), nudged by ACK-freed
  window space in `_handle_frame` and by `close()`. A 0.2s wait timeout
  covers the window-full backpressure case. `test_p2p_*` suite green.
- **Content surfaces are Browse/Installed toggle views** (2026-09-09): mods
  (incl. resource packs + shaders, which share the tab), modpacks, and
  server plugins each show ONE pane at a time — `view_segment_row` underline
  tabs (`text_tab`) above `browse_pane` / `installed_pane`, both mounted,
  only `.visible` flips on `on_view_change` (no rebuild, no re-fetch). The
  Installed tab label carries a live count ("Installed (7)"), refreshed by
  the same refresh_*_list() calls that rebuild the list. Pattern is identical
  in all three files; server_tab's panes are built AFTER the market controls
  exist (plugin_search_field etc.) — `refresh_plugins_list` may be defined
  before them but only CALLS `_build_plugins_view_segment` at runtime. The
  old stacked layout (browse results with installed list a full scroll
  below) is gone. ui_smoke §11 asserts the pattern in all three files.
- **Browse paging is lazy, one page at a time (2026-09-20)**: both the Mods
  tab (`ui/mods_tab.py`, BROWSE_PAGE_SIZE=5, MAX_BROWSE_PAGES=20) and the
  Modpacks tab (`ui/modpacks_tab.py`, PAGE_SIZE=5, MAX_PAGES=10) advertise a
  full page count but fetch only the requested page — the pager's Next/Prev
  triggers a fetch for that offset, not a 20-page prefetch. `browse_state`
  holds the page cache; a page already in `results` renders without refetching.
  `offset` is part of every search cache key in `cubeon/mods.py`,
  `cubeon/content.py`, and `cubeon/modpacks.py` so pages cache independently.
  Modrinth's per-request cap is 100 (`limit`); a SHORT page clamps
  `total_pages` down (the API over-reports count for filtered queries). The
  curated no-category mod list ignores `offset`, so it sets
  `browse_state["paged"] = False` and slices client-side. Modpacks fetch
  Modrinth + CurseForge in parallel per offset and merge via
  `merge_modpack_hits`; keyless cfwidget returns [] for offset>0.
- **Installed content shows real thumbnails (2026-09-20)**: a bare `.zip`
  carries no Modrinth identity, so `download_content()` records the browse
  hit's `icon_url`/`slug`/`title` (via `content.remember_content_meta`) in the
  `content_meta.json` sidecar under `CUBEON_HOME`, and `list_content()`
  re-attaches it (`_attach_content_meta`); `delete_content()` calls
  `forget_content_meta()` so a reused filename can't inherit stale art.
  Modpacks do the same through their `_modpack.json` meta: the install paths
  take an `icon_url` kwarg (`install_modpack_from_url` /
  `install_modpack_from_cf` -> `_install_from_zip`) and `build_installed_row`
  draws `icons.src(meta["icon_url"])`. No recorded art (hand-dropped file) ->
  keep the quiet type glyph, never a broken image.
- **Shader requirement notice is state-aware (2026-09-20)**: the Shaders view's
  "install Iris/Sodium/OptiFine" banner (`shader_notice`) shows only while the
  requirement is actually missing — `shader_requirement_installed()` scans
  `core.list_mods()` display names for "iris"/"optifine", so installing the
  loader clears the notice on the next `refresh_mods_list`.
- **Browse rows share ONE visual pattern everywhere** (2026-09-09): the mods
  tab's row style is the canonical one — `attach_hover(container,
  "transparent", ROW_HOVER)` (transparent at rest, faint lift on hover, no
  permanent slab), 15px W_700 title / 12px TEXT_DIM description / 11px
  TEXT_FAINT FONT_MONO metadata, and the action button a restrained
  ACCENT_TINT wash with ACCENT text (solid ACCENT is reserved for the one
  hero action per screen). `build_pack_row` (ui/modpacks_tab.py) and
  `_plugin_result_row` (ui/server_tab.py) follow it exactly. Tab builders
  only receive the fixed THEME kwarg set — extra tokens (ROW_HOVER,
  ACCENT_TINT, TEXT_FAINT, attach_hover) are imported directly from
  cubeon/theme.py; do NOT add keys to THEME (TypeError at every call site).
- **Stats tab** (2026-09-09, ui/stats_tab.py): top-nav "stats" key, lazy
  tab like the others. Read-only counters over existing state
  (milestones.json, versions scan, folder globs, skins/capes meta) in
  three sections (Playtime / Library / Cosmetics). RULE: never call
  get_profile_dir() / get_plugins_dir() / content_dir() from a read-only
  scan — they CREATE directories as a side effect; glob PROFILES_DIR /
  SERVERS_DIR / RESOURCEPACKS_DIR / SHADERPACKS_DIR directly
  (ui_smoke §12 enforces via a comment-stripping matcher). Flet 0.86 has
  no `ft.margin.only/.symmetric` — use `ft.Margin(l, t, r, b)`. "Playing
  since" reports the full date (`%b %d, %Y`), not just month+year.
- **Chat tab + automatic identity** (2026-09-11, ui/chat_tab.py): top-nav
  "chat" key, inserted at index 3 ONLY when `features.friends_enabled()`, so a
  public no-Friends build has no dead entry. It talks to the process-scoped
  `FriendsService` directly (roster/chat/requests), NOT the mod bridge, and:
  - `build_chat_tab(page, cfg, state, service, *, section_label, **THEME) ->
    (root, refresh)`; `service is None` returns a static notice (never crashes).
  - polls on its own daemon thread via `cubeon/thread_safe_ui.py` (service
    reads block on the websocket — never touch Flet from them); `refresh()` is
    main.py's on-open reconcile hook.
  - auto name: `friends.auto_name()` = `"Player_" + sha256(stable_secret())[:8]`
    (deterministic per auth_key.json, 15 chars, allowed name set, never
    reserved). `friends.ensure_identity()` mints it only when no identity has a
    name, so it can never silently rotate a name a friend already knows; the
    server binds it claim-on-connect at WS hello. No claim prompt exists.
  - the tab shows the server-assigned 8-digit **ID**, not a name: a name is
    only a cosmetic label and there is NO rename field (the old
    `rename_unique`/"Your name" flow was removed 2026-09-12; test_ui_smoke
    pins `name_field`/`rename_unique` OUT of chat_tab.py). Add a friend by ID
    via `friends.canonical_uid(raw)` -> `FriendsService.add_friend(uid)`.
  - main.py startup connects only if an identity ALREADY existed; a brand-new
    one connects when the Chat tab first opens (keeps headless UI builds from
    opening real websockets with throwaway identities).
  - **layout reworked 2026-09-11, professional pass 2026-09-13**: left rail =
    "Chat" header + connection dot, identity block (avatar + name, and the ID
    in a bordered badge chip), add-friend field, requests section (only when
    non-empty), then Friends. Roster rows are chat-style: avatar ringed green
    when online, name, last-message preview ("You: ..." for outbound) or
    presence when there is no history, and a right-aligned clock + accent
    unread badge. Right pane = conversation header (avatar + name + presence)
    with a centered empty state until a friend is picked, day separators and
    grouped spacing in the transcript, content-hugging bubbles ("mine" =
    `ACCENT_TINT` wash, theirs = `SURFACE_HI`), an inline send-error line, a
    rounded composer (`shift_enter=True`: Enter sends, Shift+Enter newline),
    a square accent send button, and a warning banner while the socket is
    down. Avatars are per-name `theme.AVATAR_COLORS`. Bubble width is measured
    from the longest line, capped at half the window. Message/name text uses
    the body font, not mono.
  - **optimistic sends + scroll + emoji (2026-09-20)**: pressing Enter shows
    the bubble IMMEDIATELY (dim, "Sending…"); `_do_send` clears the composer
    before `send_chat` runs (it blocks ~1s on the peer-pubkey lookup). The
    echo-filed line REPLACES its pending bubble by FIFO text match
    (`_append_messages`); a refusal (or 12s silence, `_sweep_pending`) turns
    it red "Couldn't send". Auto-scroll: `auto_scroll=False`, `_stick["at_end"]`
    from `on_scroll` (`extent_after < 48`); `_stick_bottom()` only follows
    when at end (or forced on open) via `page.run_task(transcript.scroll_to,
    -1)` — scroll_to is async and requires auto_scroll=False. Emoji picker:
    `emoji_panel` (32 literal emojis, no plugin) toggled by `emoji_btn`,
    hidden on select/send/clear.
  - **chat conveniences (2026-09-21)**: (a) composer DRAFTS survive friend
    switches and tab closes within the session — `_drafts` keyed by canon
    friend, saved on every keystroke (`on_change`), restored in `_select`,
    cleared on send/remove. (b) `_jump_row` "Newest" pill visible only while
    scrolled up (`_stick`), click = `_stick_bottom(force=True)`. (c) bubbles
    are click-to-copy (`_copy_message` via the Clipboard service; full date
    "Mar 3, 2026 · 14:23" on hover — `_full_date`). (d) the clock line is
    GROUPED: only the first bubble of a same-side run or day shows it
    (`with_time` in `_append_messages_inner`); roster stamps use
    `_short_stamp` ("14:23" today, "Mar 3" older). (e) `find_field` filters
    the Friends rail client-side over the last roster snapshot (no service
    query per keystroke). All pure UI — no protocol changes.
  - **roster rail data contract (2026-09-13)**:
    `FriendsService.roster_payload` decorates each friend with
    `last_text`/`last_ts`/`last_dir` and `unread` (inbound msgs after that
    peer's read marker). `FriendsService.mark_read(friend)` advances the
    marker monotonically; the Chat tab calls it on select and on every poll
    while a conversation is open, which clears the badge. The tab's
    `_mark_read` uses `getattr(service, "mark_read", None)` so stub services
    (test_fuzz/app_driver) keep working. GOTCHA: a multiline Flet TextField
    with default `shift_enter=False` makes Enter insert a newline and never
    fire `on_submit` - the composer must set `shift_enter=True`.
    `test_friends_service.test_chat_read_rail` and the ui_smoke chat checks
    pin the rail contract, the Enter-to-send rule and the day separators.
- **Playtime is a durable on-disk play session (fixed 2026-09-11)**: the game
  outlives the launcher (launch.py `start_new_session=True`) and a GPU-crash
  re-exec (main.py `os.execv`, sets `CUBEON_TRAY_REOPEN`) replaces the process,
  killing the in-process on_exit watcher. So playtime is persisted, not just
  credited in memory:
  - `launch_game` calls `milestones.begin_play_session(pid)` right after
    `watchdog.register` → writes `~/.cubeon_launcher/play_session.json`
    (`{started, pid}`).
  - `main.py` on_exit / the startup reconciler call
    `core.milestones_end_play_session()`, which credits `min(now, mtime of
    game.log) - started` (the log mtime bounds idle time when the launcher was
    off for hours) and clears the record. Idempotent under `_session_lock`, so
    on_exit and a reconcile poll can't both credit.
  - `main()` calls `core.milestones_reconcile_play_session()` on EVERY start
    (including re-execs - do NOT gate it on `CUBEON_TRAY_REOPEN`, which is set
    on exactly the crash path that needs it): a dead pid is credited and
    cleared; a live one is left on disk and watched by a 30s poll until exit.
  - GOTCHA: `core.add_play_seconds` does not exist; launcher_core re-exports
    `milestones.add_play_seconds` as `milestones_add_play_seconds`, and session
    helpers as `milestones_begin/end/reconcile_play_session`. A bare rename
    fails silently under `except Exception: pass` (that was the original
    "Time in game stays 0" bug). ui_smoke pins the session wiring + a real
    3661s accumulation; test_milestones §7 pins the durable-session semantics.
- **Browse/installed PANE anatomy is the mods tab's** (2026-09-09): bare
  Columns with NO enclosing SURFACE slab, a quiet search field (CARD_BORDER,
  ACCENT_DIM focus, CARD_FILL fill, 46px, TEXT_FAINT hint, no separate
  solid-green Search button — Enter/typing carries it), a 12px TEXT_DIM mono
  caption line ("Recommended" / "Popular modpacks" / "Plugin picks") sharing
  a row with the status text, and transparent-until-hover rows everywhere
  (browse AND installed). Hero headers (big ACCENT icon + Minecraftia title)
  are gone from these panes — the one hero per screen rule.

## Top-bar layout + mod deps + legacy gate (2026-09-08, later)
- **The sidebar is gone.** Navigation is now a top icon bar (`_build_top_bar`):
  Play / Mods / Modpacks / Cosmetics / Servers centered (icon + green
  underline for active, marker attr `cubeon_top_icon` on those buttons),
  Account + Settings icon buttons on the right. The top-bar "Servers" icon is
  an entry point that maps to `server_console`; the Console/Plugins/Settings
  chips live in `subnav_bar` between the top bar and the content surface and
  are visible only while a server tab is active. The identity card moved out
  of the old Profile tab into an `account_dialog` opened by the Account icon
  (`_account_open["fn"]` holder is filled after the dialog is built).
- **The old "profile" tab is now Cosmetics** (skins/capes/hat only) - key is
  still `"profile"` internally, switch_tab/refresh_profile_tab unchanged.
- **Required-dependency auto-install**: `mods.required_dependencies()` reads
  Modrinth's latest-version `dependencies` (only `dependency_type ==
  "required"`), resolves each with the cached `get_mod_download()`;
  `mods.install_mod_with_dependencies()` downloads main mod + missing deps
  (skips by project_id/slug via `mods.installed_project_ids()`), returns
  `{installed, skipped, failed}` and never raises for a failed dep.
  `ui/mods_tab.py` on_download uses it and reports "Installed +N deps" /
  per-dep failures. Verified live: iris→sodium resolved, junk→[].
- **Batch install progress is in FILE UNITS (2026-09-15)**: `install_mod_with_
  dependencies()` amortises the whole batch as `(whole files finished + the
  current file's fraction, TOTAL FILE COUNT)` - a total that is FINAL before
  the first byte moves - so one click climbs 0→100 once instead of restarting
  per dependency (the reported "1-100% doesn't work" bug). Success finishes at
  exactly 100; a failed dep holds the floor short of 100. The UI label is
  `ui/mods_tab.batch_progress_text(value, total)` → "Downloading… 42%
  (file 2/3)" (plain percent when total <= 1). Single-file callers
  (resourcepack/shader via `content.download_content`) still report BYTES and
  pass their own `_bytes_label`; don't feed byte counts to
  `batch_progress_text`. Contract pinned by `tools/test_mod_install_progress.py`
  (39 checks, offline, fakes cubeon.mods).
- **Legacy gate**: versions below 1.20 (numeric only, `_is_legacy_version`)
  are hidden from BOTH the installed and online lists until the user enables
  it. The **Legacy toggle lives in Settings → "Game versions"** (a real
  on/off toggle via `_set_legacy_ui` + `state["legacy_ok"]`; the choice
  PERSISTS as `cfg["legacy_versions"]`, seeded at startup). The "Show
  snapshots" checkbox also lives in that card (always visible,
  re-fetches on toggle). The Play tab and the version picker dialog no longer
  carry either control - test_ui_smoke asserts their absence on the Play tab.
- **Cubeon Client mod off-switch**: Settings → "Game versions" →
  "Install the Cubeon Client in-game mod" checkbox, `cfg["client_mod_enabled"]`
  (default True). cubeon/launch.py treats off like a public build: no jar
  install AND `cubeonfriends.remove_installed()` sweeps stale jars (a
  leftover would still load). Smaller blast radius than
  features.friends_enabled(), which is a BUILD-time switch removing the whole
  backend.
- **FPS boost = SIX MODS (2026-10-14, supersedes the 2026-10-05 Sodium-only
  narrowing).** The user then asked for "twice as much FPS"; Sodium alone
cannot deliver that, so the suite is Sodium + Lithium + ImmediatelyFast +
Entity Culling + FerriteCore + More Culling (all IDs verified live on
Modrinth). EntityCulling's tick-1 crash is neutralised by the unconditional
sanitize at launch (below). The four still-retired mods
(BadOptimizations/Krypton/ThreadTweak/Dynamic FPS) stay retired. Older bullet (2026-10-05): The suite was cut from 9 mods to Sodium, the
  one that replaces the renderer and is the overwhelming share of the client
  FPS win; the other 8 added little and each was third-party crash surface
  (EntityCulling alone killed the game on tick 1, see above). **Do NOT widen
  `PERF_MODS` again without the user's say-so.** A clean profile gets Sodium
  when `client_mod_enabled` (and config-only `perf_mods_enabled`) is on and the
  loader is Fabric/Quilt; `_present()` matches slug/display_name/project_id/
  filename so a manual jar is never duplicated; skip-if-present, no
  auto-update. `prune_retired_perf_mods()` removes the 8 retired mods from a
  profile that already has them, matching ONLY the recorded slug/project id, so
  a hand-dropped or user-owned mod (Iris, Wurst, Xaero, Jade…) is untouched.
  The user's own mods stay: "no more mods" means the launcher stops ADDING
  them, not that it deletes what the player chose.
- **EntityCulling's config is REPAIRED at launch (2026-10-05) — INVARIANT.**
  EntityCulling 1.11.2's `clientTick` walks `blockEntityWhitelist` (and the
  entity/tick lists) and parses every entry as a ResourceLocation. A **legacy
  config with a `null` (or empty-string) entry** — which its defaults and
  ConfigUpgrader never produce but never clean out either — throws
  `NullPointerException: Cannot invoke "String.indexOf(int)" because "$$0" is
  null` on the FIRST tick, so the window never reaches the menu. The user hit
  exactly this on 2026-10-05 (`config/entityculling.json` had `null` +
  `""`), immediately after the perf suite added the mod. Guard:
  `perf_mods.sanitize_entityculling_config()` drops only entries that cannot
  run (strips null/blank from the three whitelists, preserves every other key
  and valid entry, atomic + idempotent), and `launch_game` calls it
  UNCONDITIONALLY (even with the perf suite off) because the stale broken
  config lingers. Guard: tools/test_perf_mods.py §8. Do NOT remove the mod's
  crash-causing entry handling without re-reading this.
- **Max FPS mode (2026-10-14; distance levers added 2026-10-18,
  cubeon/game_options.py `apply_max_fps`) — INVARIANT.** On the launch path
  (gated on `fps_boost_enabled`, default True, the PLAY-menu switch) the
  launcher ALSO sets the game's own speed-only options: graphicsPreset:"fast",
  particles:2 (MINIMAL — 0 is ALL), ao:false, entityShadows:false,
  entityDistanceScaling:0.75, biomeBlendRadius:0, syncChunkWrites:false,
  renderDistance:6, simulationDistance:5, mipmapLevels:2, renderClouds:"fast"
  (`MAX_FPS_OPTIONS`). unlock_frame_rate() and apply_max_fps() share
  `_set_options()` — the contract is: only keys ALREADY in options.txt are
  touched (no invented unknown keys), values written only when they differ,
  atomic + idempotent, never raises. STRING options (graphicsPreset,
  renderClouds) must be written QUOTED. `restore_vanilla_look()` is the OFF
  switch and restores all of the above to Minecraft's defaults, distance
  levers included. Tests: tools/test_perf_mods.py section 10 + 11.
- **Frame-rate unlock (cubeon/game_options.py)**: adding mods only raises what
  the machine CAN render; Minecraft's own `options.txt` will still read 60 (or
  ~30, Vsync halving) if `enableVsync:true` / a low `maxFps`. This module flips
  EXACTLY those two keys (`enableVsync:false`, `maxFps:260`, vanilla's top
  slider) on the launch path, atomically and idempotently, and touches NOTHING
  else (render distance / graphics / packs / shaders stay the player's choice —
  same rule as content.py). Only keys already present are changed, so an older
  options.txt without them is not given unknown keys. Called in
  `launch_game` right after `perf_mods.ensure_installed`, gated by the same
  `perf_mods_enabled`. The game is not running yet at that point, so it cannot
  race the game's save-on-exit.
- **Client JVM flags are CPU-AWARE (2026-10-05) — INVARIANT.** `cubeon/launch.py`
  builds them per launch with `client_jvm_flags()` (NOT a fixed list), so a
  pinned/limited CPU is tuned correctly:
  - `_available_cpus()` = `len(os.sched_getaffinity(0))`, so `taskset -c 0,1`
    (2 cores) is seen as 2, not the 12 physical CPUs.
  - **≤4 usable CPUs**: `G1NewSizePercent=20`, `G1MaxNewSizePercent=30`,
    `MaxGCPauseMillis=100` — a smaller young gen because copying a huge young
    generation on 2-4 threads is a visible frame spike.
  - **>4 CPUs**: Aikar's `30/40` + `MaxGCPauseMillis=200`.
  - `G1HeapRegionSize=8M` for both (was 16M) — correct for a client-sized heap
    (half of system RAM); 16M made young collections coarser.
  - `CLIENT_JVM_FLAGS` is kept as the many-core default for callers/tests.
  - `-XX:+AlwaysPreTouch` is added by `build_launch_command` **only when
    `_pretouch_flag(ram_mb, system_ram_mb)` allows it** (system RAM ≥ 8 GB AND
    heap ≤ half of it). It faults the whole heap in at startup instead of on
    the render thread during the first world load. Low-RAM boxes keep it OFF —
    that was the original reason the client set omitted it; the gate preserves
    that intent. Guard: tools/test_perf_mods.py §6.
  - Flag changes MUST be validated against a real `java` before shipping (see
    the JVM FLAGS gotcha above). The whole set incl. pretouch was run through
    Java 21 on 2026-10-05.
  - **World-entry stutter on 2 cores is NOT fixable by flags.** Measured
    2026-10-05 on a 2c/4GB pin: entering a world saturates both cores
    (integrated-server worldgen + chunk mesh build), `Preparing spawn area`
    took 11.2 s, the server fell `2061ms / 41 ticks behind`, and the client
    rendered ~1 FPS until it caught up — then settled to 70-80. Heap was
    healthy (1.5 GB used / 1 GB young), so it is CPU contention, not GC. The
    only real levers are fewer chunks (render/simulation distance) or more
    cores.
- **"Invalid session" on online-mode servers is INHERENT, not a Cubeon bug —
  INVARIANT (2026-10-12).** Cubeon hands the game `accessToken="0"`
  (`cubeon/launch.py`). The vanilla client's OWN handshake listener
  (`hie.class` in 1.21.11.jar, implements `ako`) calls
  `MinecraftSessionService.joinServer(uuid, username, serverHash)` on the
  encrypted/online-mode login path only (`hie.a(String, akz, Cipher, Cipher)`
  takes ciphers). An `InvalidCredentialsException` from that call maps to
  `disconnect.loginFailedInfo.invalidSession` = "Invalid session (Try
  restarting your game and the launcher)". Offline-mode servers never hit this
  path; LAN joins (`hit.d()` true only for `LAN`) downgrade it to a warning and
  proceed. **No launcher-side argument can make token "0" pass an online-mode
  server's session check** — a player hitting this on an `online-mode=true`
  server needs a legitimate account, full stop. Do NOT chase this in the launch
  path. (There is now ONE client-side exception — the Velocity cracked-fallback
  case and the mixin that unlocks it — see the next invariant; it changes the
  CLIENT's give-up point, not the server's check.)
- **`YggdrasilSessionServiceMixin` — client-side session-check bypass for
  cracked-enabled proxies — INVARIANT (2026-10-12).** Many cracked-enabled
  networks run a **Velocity proxy** with `online-mode=true` plus a plugin that
  treats a failed session verification as "this player is offline" and lets
  cracked players through. The proxy sends an `EncryptionRequest`; the vanilla
  client then calls `MinecraftSessionService.joinServer(uuid, username,
  serverHash)`, which throws on Cubeon's `accessToken="0"`, and the client
  disconnects with "Invalid session" BEFORE it sends the encryption response —
  so the proxy's cracked-fallback never runs. Premium players and modified
  cracked clients (which send the response anyway) get in; the vanilla cracked
  client does not. This is the `lemonmc.fun` case (mcsrvstat: Velocity,
  "Premium & Cracked supported"; the vanilla client gave up in ~2s, while other
  launchers join). The mixin
  (`mod/src/main/java/com/cubeon/client/mixin/YggdrasilSessionServiceMixin.java`)
  cancels `joinServer` at HEAD (a clean no-op — the method only POSTs to Mojang
  then throws on failure, so cancelling skips the POST and never throws), so the
  handshake proceeds and the encryption response is sent. It is **client-side
  only**: it does not make token "0" pass any server's real check. Offline-mode
  servers are unaffected (the method is never called). A plain online-mode
  server with no fallback still kicks the player — just by its own check instead
  of the client giving up first. **Build safety:** the mixin uses
  `@Mixin(targets = "com/mojang.authlib.yggdrasil.YggdrasilMinecraftSessionService",
  remap = false)` with a STRING target, so it resolves at RUNTIME and never
  imports authlib at compile time — one shared source file is safe across both
  build brackets, and on Minecraft 26.x (authlib 10.x restructured these classes
  away) the target is simply not found and the mixin is skipped (`required:
  false` + `defaultRequire: 0`). authlib is a Mojang library with unobfuscated
  names, so there is nothing to remap. Registered in
  `cubeon-client.mixins.json` under `client`. Verified in the built
  1.20-1.21 jar (string-target survives loom's remap intact); the launcher
  reinstalls the jar on every launch (`ensure_installed` in the pre-launch path,
  `find_jar` checks `~/.cubeon_launcher/cache/` first), so a rebuild is live on
  the next launch. Tests: all green (launch 101, ui 176, mega 16, matrix 68,
  client_json 40). The `26` bracket does not build in this environment (Gradle
   on JDK 21, Minecraft 26.x needs JDK 25) — a pre-existing env issue, not this
   change; the old 26 jar is left untouched.
- **KNOWN GAP (2026-10-14): `YggdrasilSessionServiceMixin` is not in
  `tools/build_mod_jars.py`.** The mixin source exists and is registered in
  `cubeon-client.mixins.json`, but it is missing from `MOD_SOURCES`
  (`tools/test_mod_compile.py:47`) and from `REQUIRED_ENTRIES`
  (`tools/build_mod_jars.py`, which lists Pause/PlayerTabOverlay/TitleScreen
  Mixins only). So `build_mod_jars` cannot detect a half-compile that drops
  this REQUIRED runtime mixin, and `tools/test_mod_compile.py` FAILs 2 checks
  on a clean tree (pre-existing, not caused by any 2026-10-14 change).
  Fix = register it in both lists (2 lines).
- **Mixin confirmed working live; the remaining kick is server-side (204) and
  the username is the lever — INVARIANT (2026-10-12, verified on lemonmc.fun).**
  A live test after the mixin shipped proved the client-side fix works: the game
  log shows `Cubeon Client: skipped the online-mode session check…` and the
  vanilla "Invalid session" key is gone. What replaced it is Velocity's own
  `velocity.error.online-mode-only` ("You are not logged into your Minecraft
  account…"). Source-confirmed in Velocity's
  `InitialLoginSessionHandler.handle(EncryptionResponse)`: after the client sends
  the encryption response, the proxy calls Mojang's `hasJoined` and **204 No
  Content** (no session registered — unavoidable for a cracked client, since the
  mixin skipped `joinServer`) maps exactly to that message. So the mixin moved
  the failure from the CLIENT giving up to the SERVER deciding — which is the
  whole point: a cracked-bypass plugin can only act on a connection that reaches
  it. **The username is the remaining lever:** `shadoww_` is a REAL premium
  Minecraft account (Mojang profile id `4e491dc22b654e8aa024d9ac1532f1de`).
  Cracked-support proxies (FastLogin and friends) treat a premium name as
  premium-only and demand a valid session, so a cracked client using that name
  is kicked (impersonation protection) even though the server advertises cracked
  support. A NON-premium name (e.g. `shadow4638`, already in the launcher config,
  confirmed to have no Mojang profile) is treated as cracked and forwarded to the
  backend for register/login. No code change is needed — the Play/Account
  username field is the lever. Do NOT conclude "lemonmc.fun is premium-only"
  from a `shadoww_` test alone; retest with a non-premium name first. If a
  non-premium name STILL gets the `online-mode-only` kick, then that entry point
  has no active cracked bypass and only the server admins can change that.
- **`build_launch_command()` scrubs unresolved `${...}` placeholders —
  INVARIANT (2026-10-12).** `minecraft_launcher_lib` 8.0's `replace_arguments()`
  does NOT substitute `${clientid}` / `${auth_xuid}` (Microsoft-only
  placeholders), so a real 1.21+ version.json leaks them into the argv as the
  LITERAL strings `--clientId "${clientid}" --xuid "${auth_xuid}"`.
  `build_launch_command` (`cubeon/launch.py`) does a final pass that drops any
  `--flag` immediately followed by a bare `${...}` placeholder (both the flag
  and its value) plus any stray bare `${...}`. Healthy substituted args are
  untouched. Guard: tools/test_launch_fixes.py §N. This is cosmetic hygiene
  (the game is never handed garbage where a real clientId/xuid would go) — it
  is NOT what causes "Invalid Session" (see the invariant above).
- **Custom JVM flags (Settings > Java) — contract (2026-10-12).** The config
  key `custom_jvm_flags` (a single string, default `""`) holds extra JVM flags
  the player types in the Settings tab's "Custom JVM flags" field (built in
  `main.py` next to `java_path_field`, rendered in `ui/settings_tab.py`'s Java
  section, saved by `save_settings` on blur/submit like width/height/java).
  `build_launch_command` (`cubeon/launch.py`) takes an optional
  `custom_jvm_flags` arg, splits it with `_parse_custom_jvm_flags` (shlex —
  quotes respected, e.g. `-Dfoo="a b"` stays one arg; an unbalanced quote falls
  back to a naive `.split()` so a typo never aborts a launch), and appends the
  result AFTER Cubeon's tuned defaults in `options["jvmArguments"]` — so a
  repeated flag overrides (JVM honors the last). `launch_game` passes it from
  `cfg.get("custom_jvm_flags")`. Because the vanilla command builder force-inserts
  `-XX:+UseG1GC` and strips every other `-XX:±Use(X)GC` collector flag, a custom
  GC-*algorithm* flag is overridden by design (documented in the field's
  subtitle); every other flag is honored. Guard: tools/test_launch_fixes.py §O.
  NOTE: any `patch` of `build_launch_command` in a test MUST accept `**k`
  (e.g. `lambda *a, **k: ...`) — the real call now passes `custom_jvm_flags=`
  as a keyword, and a positional-only mock raises TypeError.
- **Settings → Import (scan a folder, import what it finds) — contract
  (2026-10-12).** A new rail section `("import", ...)` sits second in
  `ui/settings_tab.py:SECTIONS`; `main.py` builds its pane via
  `ui/import_section.build_import_section(...)` (passing `section_label`,
  `get_active_target`, `show_snack`, `**THEME`) and hands the finished
  `import_pane` into `build_settings_tab(...)`. All logic lives in the new
  **`cubeon/importer.py`** (Flet-free, so it unit-tests with temp folders):
  - `scan_folder(root, max_depth=8, max_files=50000)` walks a user folder and
    classifies **mods** (`.jar` ONLY if it declares itself: `fabric.mod.json`,
    `quilt.mod.json`, `META-INF/mods.toml`, `META-INF/neoforge.mods.toml` or
    `mcmod.info` — a library jar or corrupt file is SKIPPED, not listed),
    **resource packs** (`.zip` or folder with `pack.mcmeta`, incl. nested
    `MyPack/pack.mcmeta` — an unrecognised zip is SKIPPED, never guessed as a
    pack), **shader packs** (`.zip`/folder with `.fsh/.vsh/.glsl` or a
    `shaders/` dir), **modpacks** (`.mrpack`/zip containing
    `modrinth.index.json` or `manifest.json`) and **worlds** (folder with
    `level.dat`). Classifies by WHAT IS INSIDE each archive, never extension
    alone; prunes `libraries/`, `versions/`, `assets/`, hidden dirs and world
    interiors; a symlink/realpath loop guard and a file-count cap keep it from
    running away. **Never raises** — per-file failures go into
    `result["errors"]`.
  - `import_item(entry, mc_version, loader, version_id, ...)` reuses the trusted
    installers: mods → `mods.install_local_mod` (lands in the **per-profile**
    folder, NOT the wiped staging `MINECRAFT_DIR/mods`), packs →
    `content.install_local_content` with content_type **`"resourcepack"`/`"shader"`
    (SINGULAR — not the plural category name), modpacks →
    `modpacks.install_modpack_from_file`, worlds → `shutil.copytree` into the
    shared `SAVES_DIR` (with a guard so a world already under `saves/` isn't
    duplicated onto itself). Extracted pack FOLDERS are zipped to a temp `.zip`
    first (`install_local_content` only accepts a `.zip`).
  - The import TARGET is per item via the **"Import to..." picker** (2026-10-13;
    "Import all" was removed on purpose). `main.py` also passes
  `get_instances=_import_instances` → `[{"version_id", "mc_version", "loader",
    "label"}, ...]` from `core.get_installed_versions()`; loader is derived by
    `importer.loader_of(version_id)` (the only place it's known for non-active
    instances). The picker greys out (a) incompatible rows —
    `importer.instance_compatibility(entry, mc, loader)`: a Fabric jar never
    goes into Forge, a declared `mc_dep` like "1.21" fails on 1.20.1 — and
    (b) rows that already contain the exact item —
    `importer.already_in_profile(...)`. The DEFAULT target (and the basis of
    the scan-time duplicate flags) is still the Play-tab selection via
    `main.py:_import_target()`. No version selected and no instance chosen
    ⇒ every import refuses with "Pick a game version on the Play tab first."
    (never lands in the throwaway `unknown-vanilla` profile).
  - **Mods can NEVER go to a vanilla target (2026-10-13) — INVARIANT.**
    Vanilla (or anything outside `mod_loaders.MOD_CAPABLE_LOADERS`) can't
    load mods, so a mod landing in the `(mc, vanilla)` profile folder is one
    the game never reads — the import would look like it silently did
    nothing. Both layers refuse: `import_item` raises ValueError with an
    actionable message ("switch the loader on the Play tab … and press
    Play to add it, then import again"), and
    `instance_compatibility` returns `(False, "vanilla can't load mods …")`
    so the picker greys the row with the same guidance. Packs/worlds/
    modpacks still import to vanilla fine. `_import_target()` defaults the
    loader to `"fabric"` but can read `"vanilla"` from the toggle, which is
    why the hard guard lives in `import_item`, not just the picker.
  - **Duplicate detection** (2026-10-13): `importer.mark_installed(result,
    mc_version, loader)` flags scan-time finds already in the target (mods and
    zipped packs by SHA-256 incl. the pack store's `.origin` sidecar —
    `_verify_and_fix` REWRITES stored packs, so current bytes alone never match —
    worlds by folder name in `saves/`); `import_item` refuses the same
    matches (no more `foo_xxxxxx.jar` / `MyWorld_xxxxxx` twins). Folder packs
    fall back to a stem check (they get re-zipped at import). Modpacks are
    never flagged (they update in place). The search field filters finds live.
  - Folder picking uses the new **`run_dir_picker(page, dir_picker, on_path, ...)`
    helper in `cubeon/config.py`** (re-exported as `launcher_core.run_dir_picker`),
    the `get_directory_path` sibling of `run_file_picker`. On Flet 0.86.5 and
    1.0.x `get_directory_path` is a **coroutine returning `str|None`**, so the
    helper awaits it via `page.run_task`. Scans and imports all run on daemon
    threads; UI repaints go through `cubeon.thread_safe_ui.refresh`.
  - Guards: `tools/test_importer.py` (52 checks, pure logic) and
    `tools/test_import_ui.py` (48 checks, renders + search + picker model +
    per-instance imports). The pane exposes `pane.render_scan_result`,
    `pane.import_item_ui(entry, btn, inst=...)`, `pane.picker_model_ui`,
    `pane.open_picker_ui`, `pane.remark_installed_ui`, `pane._results_col`,
    `pane._status_text`, `pane._search_field` so tests bypass the OS dialog.
- **`ft.Icon` swaps glyphs via `.icon`, NOT `.name` — pre-existing bug found
  (2026-10-12).** `ft.Icon` (both pinned 0.86.5 and current 1.0.3) stores its
  glyph in `_values["icon"]`; assigning `.name` just sets an unrelated instance
  attribute and the rendered arrow never changes. `main.py` (the play button:
  `play_button_icon.name = ...` around :2438) and `ui/mods_tab.py` (:1452,
  `icon.name = ft.Icons.CHECK_ROUNDED`) use the broken `.name` pattern, so those
  runtime icon swaps are silently no-ops. The new Import section's chevron
  correctly uses `chevron.icon = ...`. NOT yet fixed in main/mods_tab — flagged
  here so the next agent can repair it (`.name` → `.icon`) if the user wants.
- **Plain-English invalid-session diagnostic (2026-10-12).** `main.py` passes a
  `log_cb=_game_log_cb` into `launch_game()`. It tails the live game log,
  tracks the last `Connecting to X` server name, and on the FIRST
  `loginFailedInfo.invalidSession` line fires one snackbar naming the server and
  explaining it requires a premium account (a `shown` flag prevents repeat
  toasts across reconnect spam). Purpose: the raw translation key reads like a
  Cubeon bug to players who think the server allows cracked. `_show_snack`
  (sibling closure, thread-safe) is the toast helper. Guard: verified against
  the real `lemonmc.fun` log lines (tracks the name, fires once); UI smoke
  176/0. This does NOT let you join an online-mode server — it only explains
  the kick.
- **Mod detail menu + auto-repair (2026-09-12)**: clicking any mod row
  (browse OR installed, except protected/system files) opens a full menu via
  `ui/mods_tab.py:open_mod_detail()`. It fetches `mods.get_mod_details()`
  (one cached `GET /project/{id}`: gallery/featured art, body markdown,
  downloads, categories, loaders, game_versions, licence, links) and
  `mods.get_mod_versions()` (one cached `GET /project/{id}/version`: every
  release, each marked `compatible` for the current profile, with its primary
  file url/filename/hashes and dependencies). Both use the 6h `local_cache`
  so reopening is instant and works offline via the stale tier. Detail
  install buttons call `install_mod_with_dependencies`, then the doctor.
  The dialog uses `cubeon/dialogs.py` `open_dialog`/`close_dialog`
  (Flet 0.86 stack), `cubeon/icons.py` for art, and background threads +
  `thread_safe_ui.refresh` for painting.
  **Layout (2026-09-12, friendliness pass)**: 720px wide; scrollable height
  adapts to `page.height` (capped 640). Order = gallery strip (all screenshots,
  sideways scroll) → compact meta pills (downloads / loader / Minecraft) →
  **"Install latest" quick action** (or "You're up to date") → collapsed
  description (`Read more` reveals the full `ft.Markdown`) → version list.
  Version list shows at most **8 compatible** builds, then a "Show all N
  versions" toggle that also reveals incompatible builds tagged
  "other version". A shared `_install_button()` drives both the quick action
  and every row; on success all cached repaints in `quick_state["repaints"]`
  fire so the banner and rows stay in sync.
- **mod_doctor() auto-repair**: `cubeon/mods.py:mod_doctor(mc, loader,
  auto_fix=True, check_online=True)` returns `{checked, problems, fixed,
  unfixed}` and NEVER raises. Four checks: (1) duplicate copies - same
  Modrinth id => older copy DELETED via `supersede_older_copies`; same
  filename stem only => older copy DISABLED (reversible). Run once per
  duplicate group, not per loser, and `fixed` is computed PER LOSER (the
  file is really gone) rather than group-level, so a partial failure is not
  reported as success. (2) missing required dependencies
  (`_required_deps_cached`, 6h) => downloaded, tracked in `installed_ids` so
  two mods needing the same dep fetch it once. (3) no release for the current
  loader+mc_version => the jar is DISABLED (`toggle_mod`), never deleted.
  `get_mod_download` skips a newest release whose `files` list is empty so a
  usable older build isn't mistaken for "no release" (which would wrongly
  disable the mod). (4) **version conflicts** - see next bullet.
  Wired four places: automatically after every mod install (`ui/mods_tab.py`
  browse quick-download AND the detail dialog AND "Install from file"), by
  the Installed pane's **"Fix problems"** button, at launch in
  `cubeon/launch.py` with `check_online=False` (skips the per-mod API passes;
  duplicate + conflict repair still runs), and **proactively** by
  `main.py:_proactive_mod_repair()` when an (mc_version, loader) profile is
  selected - full `check_online=True`, once per profile per session, in a
  background thread, silent unless it changed something. Regression:
  `tools/test_mod_detail.py` (66 checks).

- **NEVER disable a mod because a DEPENDENCY didn't resolve (2026-10-18, user
  report: "whenever I press fix problems it just disables my sodium and some
  mods").** The `depends` pass (4b) used to treat "I could not fetch this
  dependency id from Modrinth" as proof the declarer could never load, and
  called `toggle_mod` on it. That is the most destructive way to be wrong: a
  profile provides FAR more mod ids than it has jar files, because Fabric mods
  ship other mods **inside** themselves (`META-INF/jars/*.jar`) - Fabric API is
  43 modules (`fabric-rendering-fluids-v1`, `fabric-resource-loader-v0`,
  `fabric-block-getter-api-v2`, ...) and c2me bundles 20+ of its own
  (`c2me-base`). None of those ids is a Modrinth project, so every lookup
  404'd and Sodium, Modmenu and c2me were silently disabled on every single
  run. Two rules now hold:
  1. `_nested_mod_metadata(jar)` indexes what each installed jar PROVIDES,
     including jar-in-jar children (depth 2, never raises). A dependency
     satisfied by a bundled module is SATISFIED, version predicate included
     (the **highest** bundled copy wins, matching what the loader registers).
  2. An id that is still unresolved is REPORTED as unfixed and the declarer is
     left ENABLED. Not resolving is not evidence of anything (bundled modules,
     CurseForge-only mods, a 404, a rate limit, a renamed project); the game's
     own dependency screen names a truly missing mod far more precisely. The
     only auto-disable left is the `breaks` conflict last resort below, which
     is decided from two jars' own metadata, not from a failed lookup.
  Regression: `tools/test_doctor_bundled_deps.py` (19 checks; also pins that a
  fetchable missing dep is still installed).

- **Version-conflict detection (`breaks`)**: Fabric records "this mod will not
  work with mod X version Y" in the jar's own `fabric.mod.json` `breaks`, and
  the **Modrinth API does NOT expose it** (`dependencies` only lists required/
  optional/embedded/incompatible PROJECTS, never version ranges) - so the jar
  is the only source of truth. `read_mod_metadata(jar)` unzips
  `fabric.mod.json`/`quilt.mod.json` (local, offline; returns `depends`,
  `breaks`, id, version, name). `version_satisfies(version, predicate)`
  implements Fabric/Maven ranges (`<=1.10.7`, `0.8.x`, `[1.0,2.0)`, `*`,
  `||`). `mod_doctor` builds an id->installed-version map, and for every jar
  whose `breaks` matches an installed mod it reports `kind="conflict"`.
  Resolution (`_resolve_mod_conflict`): (1) update the TARGET if a compatible
  build escapes the predicate; else (2) replace the DECLARER with the newest
  compatible build (stable before beta, compatibility filtered BEFORE any
  cap) whose own `breaks` no longer matches - e.g. Sodium 0.8.14 breaks Iris
  <=1.10.7, and the newest Iris for 1.21.11 *is* 1.10.7, so Sodium is
  downgraded to 0.8.12 (breaks Iris <=1.10.6). Remote candidate jars are read
  via `_read_remote_mod_metadata` (temp download, discarded). If neither side
  has a compatible replacement, `mod_doctor` falls back to DISABLING the
  target (`toggle_mod`, reversible) so the game still launches; a
  `disabled_targets` set stops a second declarer of the same target from
  toggling it back on. Never deletes blindly; `download_mod` supersedes the
  replaced copy.
- **Version manifest fetch**: `cubeon/versions.py` `MANIFEST_URLS` /
  `_download_manifest()` / `_manifest()`. Both Mojang hostnames are tried
  (`piston-meta` then `launchermeta`) via `net.get_with_retry` (timeout 15s,
  2 attempts); the raw manifest is cached in `local_cache` under
  `mojang_manifest` / `v2` for 1h and served STALE when both mirrors fail.
  `get_available_versions()` and `get_latest_release()` read that cache, NOT
  `mll.utils.get_version_list()` (single bare request, no timeout/retry).
  Regression: `tools/test_versions_manifest.py`.
- **"Update game version" REMOVED (2026-09-20, user request).** The Play tab
  button, its `on_update_version` handler, the `_newest_release_key` helper and
  the `all_online_options` cache are all gone; test_ui_smoke section 6b was
  deleted with them. Changing/selecting a version now happens ONLY through the
  version picker dialog - nothing auto-jumps the selection to the newest
  release. Don't reintroduce it without the user explicitly asking.
- test_ui_smoke now asserts nav via lowercased all_text (which includes
  tooltips - all_text already walked them); nav labels are
  play/mods/modpacks/cosmetics/servers/account/settings + the two buttons.
- **Version picker dialog**: the Play tab's config band is one compact row -
  GAME VERSION (button) | ACCOUNT (username field), both 48px. The `ft.Dropdown` is still
  the source of truth but is NOT mounted; the button (`version_dropdown_button`,
  label mirrored by `_sync_version_button()` from `on_version_selected`) opens
  `version_pick_dialog`: the search field `version_filter_field`
  (on_change = on_pick_search), scrollable `pick_list` rows, and a
  "Browse all versions →" link (refresh_version_list(online=True) + rebuild).
  (The "Show snapshots" checkbox lives in Settings now, not the dialog.)
  **Invariant (2026-09-11 fix):** the dialog filters its OWN snapshot,
  `pick_source["value"]` (installed-only offline, full online list when
  fetched), and `_rebuild_pick_list()` reads only that. It must NEVER rewrite
  `version_dropdown.options`/`.value` while filtering - the old `_filter_versions`
  did, so every keystroke could reassign the selection to the first match and
  call `on_version_selected()` (silently starting a prefetch/download), and
  closing the dialog left the dropdown stuck on a narrowed list. Selection
  commits only via `_pick_version` (a row click). `refresh_version_list` keeps
  both `all_online_options` (update-version path) and `pick_source` current.
  An empty `pick_source`/zero-match renders an explanatory row, never a blank
  box. test_ui_smoke guards this with a source assertion.
- **Version strings are shown verbatim; "1.21.11" is not a typo for "1.21.1".**
  Verified 2026-09-11: the installed folder/JSON id on this machine is
  literally `1.21.11` (alongside `1.21.8`, `26.1.2`), and `extract_mc_version`
  is non-destructive for it. Do not "fix" the displayed version without first
  checking `~/.minecraft/versions/<id>/<id>.json`'s `id` field.
- The `_reveal_window` GPU-marker NameError (from the mid-session recovery
  work) is fixed: `_CUBEON_HOME` is imported inside the coroutine; the fuzz
  suite (12 checks incl. run_task coroutine scan) catches this class.



## Follow-up 16: UI-freeze fix — throttled progress repaints (2026-09-05)

- **The "launcher froze during a download then recovered" bug**: mll fires
  progress once per FILE (~4000 files/version); every report called
  page.update() (full-tree repaint) → thousands of queued repaints
  saturated Flet's loop → window stopped taking input until the install
  ended. Fixed with `thread_safe_ui.throttled_update(page)` (coalesces to
  max 1 repaint / 0.1s) + `final_update(page)` to flush the last state.
  Flood sites: main.py do_install_and_launch callbacks, modpacks_tab
  status/progress/max, server_tab install progress_cb + _smooth_progress.
- Rule going forward: any callback that can fire per-file/per-chunk must
  use throttled_update, never bare page.update(). One-shot handlers can
  keep page.update().
- Verified: 5000 rapid calls → 1 repaint; 30 calls/1.5s → 15 (cap); all
  tools/test_*.py suites pass.

## Follow-up 15: CI green again (2026-09-05, opencode)

- `cryptography>=42.0.0` is now in requirements.txt — test_friends_service
  needs the E2EE path, so "optional at runtime" no longer means "optional in
  CI". Packaged launchers bundle it (no more degrade-to-unencrypted).
- javac lint asymmetry: CI resolves javac 25 (new `dangling-doc-comments`
  lint), local dev box has javac 21. Keep file headers in mod/**/*.java as
  `/*` not `/**` unless attached to a declaration.
- Artifacts from a green Actions run: Cubeon-Windows-x64-ZIP/Folder,
  Cubeon-Linux-x86_64-AppImage, Cubeon-macOS. Release flow unchanged.

## Follow-up 14: private repo + packaging scripts

- **Repo**: github.com/Shadow-457/Cubeon (PRIVATE), created + pushed via gh
  CLI. .gitignore excludes archive/, cline/, mod/build, dist, __pycache__.
- **Updater + private repo**: check_for_updates accepts a token (arg,
  CUBEON_UPDATE_TOKEN env, or cfg["update_token"]) sent as Bearer. Private
  releases need it; WARNING: the token ships inside any built launcher, so
  it must be a fine-grained READ-ONLY token and only for personal builds.
- **Never send users to the release page of a private repo (2026-10-17)**: the
  update snackbar used to open the feed's `html_url`, i.e.
  github.com/Shadow-457/Cubeon/releases/tag/vX.Y.Z - which is an auth wall (or
  a 404) for anyone without repo access, so the offer was a dead end for every
  real user. `check_for_updates` now returns
  `updater.DOWNLOAD_URL = https://cubeon.ylet.online/download`
  (param/env `CUBEON_DOWNLOAD_URL` to override) regardless of what the feed
  advertises. The site is the public front door: its buttons go through the
  downloads worker, which is where the token stays server-side. Pinned by
  `tools/test_net.py` ("NOT at the release's html_url").
- **packaging/ now exists** (was missing - CI jobs referenced it):
  build_appimage.sh (PyInstaller onedir -> AppDir -> appimagetool, tar.gz
  fallback), build_windows.py (onedir + zip), build_macos.sh (onedir + tar.gz).
  All bundle assets via --add-data (MANDATORY - jars live there).
  CI jobs now work as written; macOS job calls build_macos.sh.
- **Verified live on this machine**: full Linux build ran end-to-end,
  dist/Cubeon-x86_64.AppImage (103 MB) produced, and
  AppDir/usr/bin/_internal/assets/jars/ contains both mod jars + connect jar.
- **Windows EXE can be cross-built on this Linux box via Wine** (2026-09-07):
  `~/winpython/py311/python.exe` is a Windows embeddable Python 3.11.9 with
  pip + all requirements + PyInstaller installed, and flet-windows.zip
  pre-fetched into its flet_desktop/app/. Build from repo root:
  `wine Z:\\home\\fuckarch\\winpython\\py311\\python.exe -m PyInstaller
  --noconfirm --onedir --windowed --name Cubeon --add-data=...;...
  --collect-all flet --collect-all flet_desktop --collect-submodules
  templates main.py` (Z: drive paths; `--add-data=` EQUALS syntax only —
  space syntax is mangled by wine). Output identical to CI's
  packaging/build_windows.py layout. See
  agents/2026-09-07_agent_wine-windows-build.md for the full recipe. Re-run 2026-09-14 for the launcher-lib fix: add `--collect-all minecraft_launcher_lib` to the wine command (bundled + verified).
- **Windows-build verification recipe (2026-09-15)**: `wine
  /home/<user>/winpython/py311/python.exe -m PyInstaller ...` works with a
  plain UNIX path - no `Z:\...\` escaping needed, which makes the command far
  easier to run from a shell/agent (the double-backslash form is what silently
  broke earlier attempts). The wine build mirrors `packaging/build_windows.py`
  but bundles only `mod/brackets.json`, not the whole `mod/` dir (verified
  against the produced `_internal/`).
  **A frozen Windows launcher keeps its state in the WINE PREFIX, not the
  Linux home**: `~/.wine/drive_c/users/<user>/.cubeon_launcher/` holds
  `cubeon.log` and the `ui_painted_ok` marker - that is where to prove a
  Windows build actually booted AND painted (a running frozen build also emits
  endless `d3d11_swapchain_Present1` fixme lines, i.e. frames are rendering).
  Checking Linux `~/.cubeon_launcher/` for a Windows run tells you nothing.
  The CLI forms of the two Windows scripts are `packaging/build_windows.py`
  (onedir -> zip) and `packaging/build_windows_single.py` (onefile); both now
  carry `--collect-all minecraft_launcher_lib`. Bundling only
  `mod/brackets.json` instead of the whole `mod/` directory is equivalent
  (build_appimage.sh does exactly that and the app runs fine), but note an
  ad-hoc `--name Cubeon-single` run leaves a stray `Cubeon-single.spec` in the
  repo root - delete it, or invoke the script, which renames its output to
  `dist/Cubeon-Windows-x64-single.exe` for you.
- **Windows distribution choices (2026-09-20)**: `build_windows_single.py`
  emits a portable onefile EXE; it does not create shortcuts. For an actual
  per-user Windows app installation, first build the onedir package with
  `build_windows.py`, then run `packaging/build_windows_installer.py`. That
  wrapper uses native `makensis` or NSIS's `makensis.exe` under Wine and
  produces `dist/Cubeon-Windows-x64-Setup.exe`, which installs to
  `%LOCALAPPDATA%\\Cubeon`, creates Start Menu/Desktop shortcuts, and registers
  an uninstaller without administrator rights.
- **GOTCHA: artifacts go stale silently if you edit sources mid-build.**
  PyInstaller snapshots module sources at ANALYSIS time (~20 s in), so an edit
  made after that is NOT in the bundle even though the build runs for minutes
  more and still says "Build complete". Verify with `stat -c %w` (birth) on the
  build log vs. the newest source mtime, or just rebuild after editing.
  Grepping a built exe for a NEW Python symbol does not work as a check (the
  PYZ is zlib-compressed and the name matches nothing) - use packed data-TOC
  names such as `minecraft_launcher_lib`, which ARE greppable.
- **GOTCHA: `dist/Cubeon` is a contested name.** build_appimage.sh does
  `mv dist/Cubeon/* AppDir/usr/bin/` then `rmdir dist/Cubeon`, so the LINUX
  PyInstaller output must own that path. A wine/Windows onedir build lands on
  the SAME name and gets silently absorbed + deleted by the next AppImage
  build. Keep the Windows onedir as `dist/Cubeon-Windows-x64/` (matches the
  zip name) before running build_appimage.sh; the zip is the durable artifact
  anyway.
- **Modpack install progress, two phases**: `install_modpack_from_url()` /
  `install_modpack_from_cf()` download the pack ARCHIVE first (tens of MB, size
  unknown to the caller) - that phase reports its own whole-percent through
  `_archive_progress_status(prefix, status_cb)` fed to `_download_to`'s
  `progress_cb` (`"Downloading modpack... 42%"`), then `_install_from_zip()`
  drives the real bar via `progress_cb`/`max_cb` with `status_cb` giving
  `"Downloading mods... 12/345"`. `ui/modpacks_tab.py`'s `status_cb` repaints
  the status line + bar on EVERY call, so anything feeding status_cb must
  coalesce to whole percent (net throttles to >= 33 ms / >= 1% on top of that).
- Release flow: bump cubeon/updater.py APP_VERSION -> tag vN.N.N -> push ->
  gh release create with the built artifacts.

## Invariant: ft.Image never loads absolute filesystem paths (Flet 0.86)

- `ft.Image(src=...)` only accepts asset-relative paths (resolved against
  assets_dir) or http(s) URLs. A `~/.cubeon_launcher/...` absolute path
  silently fails and renders a PERMANENT BLANK BOX (this bit the chat
  tab's self-avatar; skin_tab hit it earlier). Three working patterns:
  1. base64 str (skin_tab previews, chat_tab `_set_you_avatar`)
  2. raw bytes via `ft.CircleAvatar(foreground_image_src=...)` (main.py)
  3. bundled asset-relative path (skin_tab DEFAULT_CAPE_PREVIEW_SRC)
- Chat tab gotcha: visible-toggled header chrome (avatar, remove button,
  header hairline) must be flipped together in `_select` AND
  `_clear_conversation` and listed in BOTH refresh tuples — an always-on
  divider rendered as a stray floating line in the empty right pane.

## Worker/relay invariants (2026-09-14 sweep)

- **`decodeURIComponent(url.pathname)` throws URIError on malformed escapes**
  (e.g. `/name/%zz`) and an unhandled throw in a Worker fetch surfaces as a
  Cloudflare "error 1101" page. All four workers route through `safePathname()`
  which falls back to the raw (always-valid) pathname. Keep that pattern for
  any new worker.
- **Durable Object race audit rule:** message handlers run one at a time, so
  code with NO `await` between a read and its write is race-free by
  construction (`onAdd` mutual-add auto-accept). Only `await`-crossing
  sections are candidates — e.g. `onHello`'s claim-on-connect INSERT, guarded
  by a catch + re-read on the PRIMARY KEY violation.
- **Pre-auth WS flooding:** the per-user `frames:` limiter only exists AFTER
  hello authenticates. Unauthenticated sockets are gated per-IP (30/10min),
  with the IP captured into the socket attachment at upgrade time
  (`CF-Connecting-IP`) because headers are unavailable in
  `webSocketMessage`. `serializeAttachment` REPLACES the attachment, so any
  later write must re-include `ip`.
- **Chat history SQL:** newest-N-then-reorder needs a subquery, and `rowid`
  must be PROJECTED out of the subquery (`rowid AS rid`) or the outer
  `ORDER BY` fails with "no such column". Verified against real SQLite.
- **KV write budget:** every worker must keep the compare-then-write / body-
  cap discipline; the waitlist worker's `request.json()` was the one uncapped
  body parse (fixed 2026-09-14). invites' `RATE_LIMITER` binding is now
  actually consulted (`.catch(() => null)` → degrade to no limit, not 500).
- Deploy note: relay fixes require `cd worker && npx wrangler deploy -c
  wrangler-friends.toml` (plus -skins/-waitlist as touched) to go live.

- `web/` is the site sharing `web/assets/site.css` + `web/assets/site.js` (no build step): `index.html` (landing), `download.html` (the binaries, clean routes to release assets — see the web bullets above), `help.html` (the manual), plus the error pages `404.html` (void/creeper), `403.html` (locked chest), `429.html` (rate-limit), `500.html` (server exploded), `502.html` (bad gateway), `503.html` (overloaded), and the legal pages. Each error page is a self-contained `noindex` stub reusing the shared navbar/footer + the `.void` layout from `404.html`; keep them in sync if the nav/footer changes. `.btn` must stay `display:inline-block` — it is applied to `<a>` tags too, and inline padding overlaps sibling text. Fonts are Google-hosted Fredoka + local `web/assets/fonts/Minecraftia-Regular.ttf` (@font-face lives in `site.css`, so its url is `fonts/...` — page-relative paths 404 there; Minecraftia ONLY for h1-h3/.brand/.btn/.q-a, line-height ~1.12 — illegible <16px, keep Fredoka for body); images lazy-swap from `/tmp`-independent `web/assets/` paths.
- **OG card: `web/assets/og.png` (1200×630, added 2026-10-17).** Every content
  page (`index`, `download`, `benchmarks`, `help`, `terms`, `refunds`,
  `privacy`, `licenses`, `cookies`) declares `og:image` + `twitter:card
  =summary_large_image`. The URL must be **absolute**
  (`https://cubeon.ylet.online/assets/og.png`) — crawlers do not resolve
  relative `og:image`; the error stubs deliberately stay bare. The file is
  GENERATED, not hand-drawn: the source card is an HTML file that reuses
  `web/assets/fonts/*` and the `site.css` palette, so it cannot drift from the
  brand. Render it through **Playwright with an exact viewport** (`viewport=
  {width:1200,height:630}`, `device_scale_factor=2`, then halve it — the 2×
  source keeps Minecraftia's pixel grid on exact pixels instead of blurring it).
  Do NOT use `google-chrome --headless --screenshot --window-size=1200,630`:
  the window frame eats ~70px of height, so the page's own background stopped
  short of the bottom of the frame while the PNG still measured 2400×1260.
  Regenerate with `python3 tools/make_og_card.py` (repo root): it rewrites the
  source card `tools/og-card.html` and renders `web/assets/og.png` through
  Playwright with exactly that viewport + scale. It is the only supported way
  to produce the card — hand-editing the PNG drifts it from the brand. The
  source card deliberately lives in `tools/`, NOT `web/`: everything under
  `web/` is published, and `tools/test_web_download_count.py` asserts that
  every `web/*.html` wires `assets/site.js` (a stray card source in there fails
  the suite — 2026-10-17).

- `ui/skin_tab.py` (Profile > Skin/Cape panes) has NO browse/gallery area anymore (removed 2026-09-14): each pane is preview + installed card grid + upload CTA. `cubeon/gallery.py` survives only as core bookkeeping (`forget_file` in delete flows) + its tests; do not re-add library browsing without asking.

## Content compatibility + the unified doctor (cubeon/packformat.py, cubeon/doctor.py)
- **packformat.py** is the single source of truth for "will the game accept
  this file?": `pack_verdict(zip, targets)` for resource packs (pack_format /
  supported_formats / min-max keys, nested-wrapper and corrupt-zip detection)
  and `shader_verdict` (shaders/ folder structure). `repair_pack` widens the
  declared range to cover the installed versions — it NEVER invents a format
  for packs that declare none, and `_rewrite_zip` is temp-file + os.replace
  (a crash mid-repair can't leave a half-written pack).
- **doctor.py `run_doctor(mc, loader, auto_fix, include=...)`** is the ONE
  entry point covering mods (delegates to mods.mod_doctor), resourcepacks,
  shaders, modpacks (marker-vs-profile) and server plugins. Sections are
  independent; `include=` scopes a run. Report contract: `{checked, problems,
  fixed, unfixed, sections}` per-entry keys `section/kind/item/detail/fixed/fix`.
  Unfixable things (corrupt zips, gutted packs) are REPORTED, never deleted.
- **Browse filtering:** `content.py` drops search results whose file list has
  no build for the selected MC version BEFORE they render, and `get_content_download`
  re-checks at download time (defense in depth). Installed-but-incompatible
  items still show — with a badge + one-click doctor fix.
- **Launch pre-repair:** `launch.py` calls `run_doctor(..., include=("mods",
  "resourcepacks", "shaders"), check_online=False)` before every game start —
  best-effort, a failed check must never block playing.
- Suite: `tools/test_content_doctor.py` (88 checks, offline, sandboxed home).

- **Folder packs are first-class (2026-09-16):** packformat verdicts/repair,
  the doctor's content scan (`_iter_content_packs`), and
  `content.list_content`/`delete_content` all accept UNZIPPED pack
  directories (the game loads those too). Dir repair = atomic pack.mcmeta
  write + `_flatten_dir` (refuses to merge over an existing root entry).
  list_content items carry `folder: True`. CONTENT_TYPES keys are singular
  ("resourcepack", "shaderpack") - list_content('resourcepacks') raises.
  GOTCHAS hit while testing: run_doctor's auto_fix defaults TRUE (a detect
  probe must pass auto_fix=False); test fixtures that install fake versions
  leak their pack formats into every later section's targets - clean them up.

## Polish surfaces (cosmetics/settings/stats/server)
- ui/skin_tab.py renders card thumbs LAZILY (one worker per refresh batch,
  mtime-skipped; _THUMB_MEMO closure state) - never call _render_thumb on the
  UI thread. Big previews are single-flight off-thread. Upload handlers park
  their button while working.
- ui/stats_tab.py refresh_stats: milestone block is sync (1 JSON read); the
  directory-scan counters run on a worker guarded by _stats_gen. Tests must
  not expect scan counters synchronously after refresh_stats().
- settings persist on on_change_end (RAM) / on_blur/on_submit (fields), not
  per tick.
- Onboarding (_onboard_finish) publishes the username via the shared
  _publish_username synchronously - do not reintroduce a debounced fire there.

## Hats (REMOVED 2026-09-16)
Hats are gone: cubeon/cosmetics.py deleted, no cosmetic_hat config key, no
hat/unlock code anywhere. cubeon/milestones.py is now ONLY the activity-stats
store (seconds_played, sessions_hosted, friends_count_high, first_seen_at in
milestones.json + play_session.json crash-survival) - the Stats tab reads it.
The base-skin composer lives in cubeon/skins.py (compose_skin: active skin or
built-in default Steve) - vanilla players still publish a sheet so the shared
Cubeon cape resolves.
- ui/mods_tab.py installed rows: toggle/delete handlers are guarded and report
  through installed_status; mod delete re-renders the browse page. Local
  "Install from file" runs on the cubeon-local-mod-install worker with the
  button parked - never call core.install_local_* on the UI thread. The
  slug->icon worker repaints mods_list_view only, never the full page.
- Gotcha: test_ui_smoke source-pins read raw source; avoid the literal
  "page.update()" in comments inside pinned functions (it trips the pins).

## UI animation choreography (2026-10-16) — Phase 4
- Curves/durations live next to the thing they animate, as named constants:
  `NAV_ANIM` + `TAB_FADE_MS` + `ACCOUNT_ANIM_MS`/`ACCOUNT_PANEL_SQUASH` in
  main.py's TOP NAVIGATION / Account blocks, `RAIL_ANIM` in
  `ui/settings_tab.py`. There is deliberately NO `PANE_ANIM`: the Settings
  content pane does not animate at all (see the one-flush rule below).
- **ONE FLUSH PER GESTURE (the rule that replaced the "two-update" trick).** A
  property written in the same frame animates from the value the client already
  holds — so "dip then settle" needs two flushes, and the second one has to come
  from a `threading.Timer` through `thread_safe_ui`. The user read every such
  gesture as "stucky": click → full repaint → 30ms gap → second repaint. The fix
  is to make the RESTING value part of the BUILD and animate with a single write:
    * Account panel: mounted already squashed (`scale_y=ACCOUNT_PANEL_SQUASH`,
      i.e. 0.04), so ONE write to `scale_y=1` unfurls it and closing re-squashes
      it for next time. Equal 260ms in both directions, `BoxShadow.blur_radius`
      kept small (16) so the blur isn't what you're watching.
    * Settings rail: only the RAIL tint/icon animates; the pane's fade+slide was
      deleted because selecting a section re-syncs all 7 panes and the fade
      forced two flushes of that. `_select_section` is now a plain diff.
- **Animations need a control the client already knows about.** Rebuilding a
  control per interaction (the old `_rebuild_rail` cleared and re-appended
  every row) can only ever render the end state — the animation has nothing to
  move from. `ui/settings_tab.py` now builds the rail ONCE and mutates the rows
  in place via `_apply_rail_state`.
- **The Account panel is a "sheet of paper"**: docked edge square, free (left)
  edge rounded, one soft `ft.BoxShadow` offset left, and a `scale_y` unfurl on
  open. It still repaints ONLY its two overlays via `thread_safe_ui.refresh`
  (never `page.update()` — ui_smoke §10 pins that) and still slides via
  `animate_position` on `right`.
- **Wearing block**: the Account panel shows the current skin and cape
  (`refresh_wearing()`, called on open). Captions are set synchronously; the
  PNG composites run on a daemon thread (`ux-wearing-preview`) and land as
  base64 `src` — `ft.Image.src` cannot load a relative path that lives under
  `~/.cubeon_launcher`. Same rule as `ui/skin_tab.py`.

## The motion layer: cubeon/motion.py + liquid glass (2026-10-18) — INVARIANTS
- **One module owns every animation: `cubeon/motion.py`.** Everything else asks
  it. TWO levels only, `full` / `reduced` (`motion.LEVELS`; there is no "off" —
  `coerce()` maps a hand-typed `off`/`false`/`0` to `reduced`, never back up to
  `full`, and it must test `value is None` rather than `value or ""` or a JSON
  `false` reads as "empty" and gets promoted). Config key `motion_level`, a
  Switch labelled "Motion" in Settings > Display (a Switch, NOT a dropdown —
  `tools/test_seasonal.py` fails any `.on_change=` next to `dropdown` in that
  file), and `motion.set_level(cfg.get("motion_level", ...))` runs right after
  `core.load_config()` in main.py. The level is read WHEN AN EVENT FIRES, never
  at build time, so switching it takes effect on rows already on screen with no
  restart and no rebuild.
- `motion.polish(control, base_bg, hover_bg, glass=None, active=..., on_hover_fill=...)`
  is the hover/press engine and `theme.attach_hover()` is a thin wrapper over it.
  It snapshots the control's OWN resting `border_radius`/`border`/`shadow` first,
  then swaps two PREPARED states with ONE write per gesture (the Phase 4
  one-flush rule): lift (`ft.Scale`), press dip, rim, halo, corner morph. Paint
  only: it never resizes layout, never rebuilds the control, and never wraps
  `on_click` (the nav and the version picker identify their controls by
  `on_click.__defaults__`). A control whose `active()` is False keeps the fill
  swap (colour = "the row is here") but never the geometry (lift/dip/radius).
- **Glass = Flet's `Container.blur`, i.e. a real `BackdropFilter`.** It blurs what
  is painted BEHIND the panel, never the panel's own text, and it wraps the
  container in a `ClipRRect` — so a blurred panel CLIPS its children/glows
  (pass `blur=None` where a child has to bloom, as the Play hero panel does).
  Borders on glass panels must stay UNIFORM: non-uniform border + rounded rect +
  hover `BoxShadow` is the decoration shape Flutter refuses to paint.
  `theme.glass_hover()` is the style polish() reads; it is pinned onto the slot
  `motion.glass_style` at the BOTTOM of theme.py, because theme imports motion and
  the reverse import has to stay lazy.
- Siblings: `motion.sheen(radius=...)` (specular sweep — a transparent band slid
  by `animate_offset`, clipped by an outer shell, parked off-surface at opacity 0
  so `run()` is a single write), `motion.shimmer()` (loading-placeholder pulse),
  `motion.stagger()` (list cascade), `motion.ambient()` (the Play hero aura).
  Corner morph, stagger and the sheen are geometry/motion, so they are gated on
  `transforms()` (full only); fill, rim, halo and shimmer are colour/light and are
  allowed on `reduced` too. Do NOT stagger a list that refreshes on every toggle,
  and do not give a `Container` an `animate` you flip at runtime (Flet swaps the
  widget type when `animate` is set).
- Hover/press wiring on app handlers must not call `control.update()` from the
  headless driver; background-thread repaints go through
  `cubeon/thread_safe_ui.refresh()`.
- Guard: `tools/test_motion.py` (96 checks, in `test_mega_smoke.py`'s SUITES);
  `tools/ux_capture.py` is the visual tour (Flet 1.0 entry via
  `tools/_fuzz_common.run_app`/`has_async_entry`).

## Local OS notifications (2026-10-16) — Phase 7
- **One module, `cubeon/osnotify.py`; nothing server-side and nothing remote.**
  Desktop toasts only: Windows via `winotify` when importable, else a
  PowerShell `ToastNotification` (both spawned through `winproc.hidden` — a
  console flash is the exact thing winproc exists to prevent), Linux via
  `notify-send`, macOS via `osascript`. No notifier installed / any other
  platform → a quiet no-op.
- **Seven kinds, one Settings switch each**: `instance, mod, modpack,
  resourcepack, texturepack, friend, update`. `KINDS` in `cubeon/osnotify.py` is
  the single source of truth — `ui/settings_tab.py` builds the switch rows
  straight from it, so a switch can never drift from a kind that exists. Config
  keys are `notify_<kind>`, all defaulting ON.
  NOTE: a "texture pack" IS a resource pack in modern Minecraft, so the
  launcher's real third content type (`shader`, see `cubeon/content.py`) rides on
  the `texturepack` switch — `osnotify.content_kind()` is that mapping, and it
  never invents a kind that has no switch.
- **Invariants** (each one is a reportable bug):
    * `notify()` NEVER blocks and NEVER raises. The real `_send` runs on a
      daemon thread named `osnotify`: `notify-send` and PowerShell both take
      100–300ms to start, and several call sites are UI handlers or the friends
      event loop.
    * The toggle is checked BEFORE anything else, from the LIVE `cfg` when the
      caller has one, so flipping a switch takes effect without a restart.
    * Identical `(kind, title)` inside `_MIN_GAP` (1.5s) collapses to one — a
      pack install fires several success callbacks and presence flaps.
    * `CUBEON_OSNOTIFY_OFF=1` disables the whole module (tests, CI).
    * `force=True` bypasses the toggle; ONLY the Settings "send a test
      notification" button uses it, because a switched-off kind would make that
      button look broken exactly when you are trying to debug it.
- **Hook sites**: `main.py::prefetch_version` (version installs are INVISIBLE —
  they run in the background while you browse), `ui/mods_tab.py` (local
  mod/content install), `ui/modpacks_tab.py::_end_install_ok` (the longest
  install the launcher does), `cubeon/friends_service.py::_on_presence` (only on
  a False→True transition, and only for the most-talked-to friend), and `main.py`
  startup through `cubeon/updater.check_in_background` (marker
  `update_notice_seen` in config, written by
  `cubeon/updater.should_announce()`, so a restart does not re-announce the
  same release).
- **The update notice is announced ONCE PER VERSION, by ONE check**
  (2026-10-18 report: "the notification of new cubeon release is just spamming
  and not stopping ... coming up again and again"). Two invariants, both
  regression-tested by `tools/test_update_notice.py`:
    * `updater.should_announce(cfg, version)` is the gate. It is a total
      function (a non-dict or hostile config still answers True — a missed
      notice is worse than a repeated one) and it MARKS the version in the
      config in place; the caller saves it. The old snackbar had no memory at
      all, so any available update nagged on every single start.
    * main.py starts **exactly one** `updater.check_in_background(...)`, with
      the update token. There used to be a second, token-less check whose only
      job was the OS toast: two GETs per start, and on a private repo two
      different answers about the same release. Both channels now ride on the
      one gated callback (`main.py::_announce_update`); the snackbar is
      reachable only through it.
- **"Most-talked-to"** is `osnotify.top_friend({name: message_count})`, fed from
  the per-conversation history `FriendsService` already keeps
  (`self._chat[conv]["msgs"]`) — no new bookkeeping. Ties break on the
  case-folded name, and no history at all means STAY QUIET (the ask was one
  friend, not the whole roster).
- Test: `tools/test_osnotify.py` (in `SUITES`) — fully offline: no toast, no
  subprocess, no socket. Section 9 source-pins that the module imports no network
  client and no flet.

## The mod's package layout (2026-10-17 — the rename)
- **`com.cubeon.client` is the shared namespace; `com.cubeon.client.hud` is the
  HUD.** The HUD classes could NOT be moved into `com.cubeon.client` itself
  because the api overlays already define **`com.cubeon.client.CubeonClient`**
  (the mod entrypoint), and a HUD class called `CubeonClient` in the same package
  would be a duplicate class. Hence the `hud` subpackage, and the class names
  `CubeonHudClient` / `CubeonHud` / `CubeonHudKeybinds` / `CubeonHudMenuScreen` /
  `CubeonHudConfig` (so the two `Cubeon*Client` classes never collide). Anything
  that adds a HUD class should keep that split.
- **`MOD_ID` is `"cubeon-client"`** (`com.cubeon.client.hud.CubeonHudClient`), and
  it drives the translation keys rather than a hand-written string: the keybind
  category resolves to **`key.category.cubeon-client.main`** and the key to
  **`key.cubeon-client.open_menu`**. The other HUD strings are `cubeonclient.*`
  (`cubeonclient.menu.*`, `.state.*`, `.editor.*`) referenced literally from
  `CubeonHudMenuScreen` / `MoveOverlayScreen`, and they must match
  `assets/cubeon-client/lang/en_us.json` exactly. The asset namespace is
  `assets/cubeon-client/` (also the mod id) - `icon.png`, `lang/`, plus the
  Cubeon Client font the other half of the mod uses.
- **The 26.x HUD mixin config is `resources-26x/cubeon-client-hud.mixins.json`**
  with `"package": "com.cubeon.client.hud.mixin"`; `mod/build.gradle`'s
  `mixins_extra` fragment, `tools/build_mod_jars.py` (`REQUIRED_ENTRIES_26X`) and
  `tools/test_mod_matrix.py` all name it, so renaming it means touching three
  non-Java files.
- The HUD's config file is **`config/cubeon-client-hud.json`** (was
  `keyhud.json`). `CubeonHudConfig.load()` deliberately still falls back to the
  old file name so an upgrading player keeps their overlay positions.
- **After any rename here, all 24 jars must be rebuilt** — the jar is the only
  thing the launcher consumes. `python3 tools/build_mod_jars.py` (all 24, ~25s
  each with a warm loom cache) then `tools/test_mod_matrix.py` +
  `tools/test_mod_compile.py`. No test compiles the `hud-*` sources: only the 24
  real Gradle builds do, so a green test run does NOT mean the HUD compiles.

## Worker abuse protection (2026-10-17)
- **A fork cannot reach the owner's Cloudflare account — but it never needed
  to.** Every Worker URL is hardcoded in the shipped launcher
  (`cubeon/csl.py`, `cubeon/friends.py`, `cubeon/invites.py`) and in
  `web/vercel.json`, so those URLs are public to *everyone*, not just forkers.
  The protections therefore have to live **in the Workers**, not in the repo's
  visibility. All five are live and answer their own `/health` text (checked
  2026-10-17; a `workers.dev` subdomain with nothing deployed answers 404).
- **`cubeon-downloads.js` was one hole — the only Worker holding a
  credential.** It spent one GitHub API call per press against a 5000/hour
  token with `Cache-Control: no-store`, so ~1.4 req/s sustained by anyone with
  the URL took the download buttons down for every user. Now the release lookup
  is served from `caches.default` for `RELEASE_CACHE_SECONDS` (300), so a flood
  costs **zero** API calls, plus an optional per-IP `RATE_LIMITER` gate.
  - **`edgeCache()` returns null off-Workers** (`typeof caches !== "undefined"`),
    which is exactly what makes `worker/test-downloads.mjs` possible: it stubs
    `globalThis.caches` + `globalThis.fetch` and asserts 100 downloads cost ONE
    API call. **The cache is the fix; the rate limiter is the optional part.**
  - Dropping `no-store` is deliberate: the installer now carries the same
    5-minute max-age as the metadata, so browser/Vercel-edge repeat presses cost
    nothing and a fresh asset URL can never be paired with a stale body.
  - A **failed** lookup is never cached (`if (cache && assets.length)`), and both
    gates degrade rather than error (`edgeCache()` → null; `.catch(() => null)`
    on the limiter). Keep that property — a protection that becomes an outage
    when it misbehaves is worse than no protection.
  - Only `name`/`url`/`size` cross into the cache; the rest of the private
    release JSON is dropped at the `.map()`.
- **`cubeon-skins.js` had TWO holes, and neither needed a fork, a token, or an
  authenticated write.** Both were found by probe (not by reading) and both are
  pinned in `tools/test_skins_net.py` §4 as well as `worker/test-worker.mjs`,
  because **CI runs Python and not the `.mjs` tests**:
  1. **Write amplification.** The identity model is trust-on-first-use, so
     first contact is *deliberately* unauthenticated (`ownsUuid` writes
     `owner:<uuid>` on the first request from anyone). A random uuid and a
     random secret are both well-formed, so validation cannot help; each POST
     cost **2 KV writes** against a 1k/day account-wide budget. 500 anonymous
     POSTs emptied it. Fixed with `throttle()` — `WRITE_RATE = {max: 60,
     windowMs: 60_000}` per IP on all four write routes, running **before** the
     handlers (asserted — see below), using the `RATE_LIMITER` binding when
     bound and an in-isolate fallback map otherwise.
  2. **Name displacement (the worse one).** `pointer:<name>` is last-writer-wins
     by design, and the only guard was a cooldown keyed to the **identity** —
     which an attacker mints for free. Four successive attempts with a fresh
     uuid each all returned 200: the victim's name flipped to an identity with
     no `skin:` record, so every friend saw **cape-only** (their skin gone), and
     the victim's own rename back was cooldown-throttled for an hour. Fixed by
     also stamping the **NAME**: `namemove:<name>` = `"<sec>:<previousHolder>"`,
     written on **every** pointer write *including a first claim of a free name*
     (that closes the free displacement window right after someone picks a
     name). `nameMoveBlocked()` refuses a displacement while the stamp is
     younger than `POINTER_MOVE_COOLDOWN_S` — **except when the previous holder
     is the mover**, which is what lets a victim reclaim their own name
     instantly.
  - **Deliberate consequence:** renaming ONTO a name that was taken from someone
    else within the last hour now 429s (`name_move_cooldown`) instead of
    succeeding with a `name_contested` warning. The old pinned test
    ("other identity takes the name -> 200 but contested") was rewritten to
    assert the 429. Do not "restore" it.
  - The per-identity `lastmove` cooldown is still there and still useful; the
    name stamp is a second key, not a replacement.
  - `worker/test-worker.mjs`, `test-waitlist.mjs`, `test-invites.mjs` and
    `test-downloads.mjs` give every helper request its **own**
    `CF-Connecting-IP` (via `freshIp()`, a `10.0.0.x` counter), or the whole
    file shares one bucket and the suite 429s itself. Throttle checks pin an IP
    in `203.0.113.0/24` explicitly to share a bucket on purpose. **Any new test
    here must go through the file's `get`/`post`/`call` helper (or pass an IP)
    rather than a bare `worker.fetch`** - a bare fetch sends no header, so every
    request lands in the single `"unknown"` bucket.
- **`cubeon-waitlist.js` gates POSTs above the route dispatch** (above
  `handleJoin` / `handleUnsubscribe`). It is the only Worker whose writes carry
  no identity and its tally shares a KV namespace, so a script posting fake
  addresses used to be able to spend the free tier's account-wide ~1k writes/day
  and take every *real* signup down with it. **The gate must stay inside the POST
  branch above the dispatch** — moved below it still compiles and protects
  nothing.
- **The `RATE_LIMITER` opt-in is now a live `[[ratelimits]]` block** in
  `wrangler-waitlist.toml`, `wrangler-invites.toml`, `wrangler-downloads.toml`
  and `wrangler-skins.toml` (Cloudflare's Rate Limiting, GA — needs wrangler
  >= 4.36.0; the old `[[unsafe.bindings]]` spelling still parses but is not
  what these files use). Two rules that bite:
  - **Give each binding a unique `namespace_id`.** Two bindings that share one
    share their counters account-wide, which is only ever deliberate.
  - **Put the table after the top-level keys.** A `[[ratelimits]]` block
    followed by `name = "..."` parses that `name` as part of the binding.
- **A rate gate must run BOTH gates, and must never trust the binding alone.**
  `if (env.RATE_LIMITER) { ... }` alone means "no limit at all" whenever the
  binding is absent — and that is exactly what shipped, because the binding sat
  commented out in the toml while the code only checked for it. The shape to
  copy is `throttle(request, env)` in `cubeon-waitlist.js`, `cubeon-invites.js`,
  `cubeon-downloads.js` and `cubeon-skins.js`: consult the binding, and **always
  run `fallbackAllow(fallbackRL, ip, ...)` too** — either gate may refuse. An
  early `return null` on the binding's approval (the first attempt) skips the
  local bucket exactly when a burst needs it. Key it on the **IP**, not on a
  caller-supplied value — invites used to key on the invite `code`, which is
  attacker-chosen, so every request landed in its own fresh bucket and the
  limiter limited nothing. Per-IP caps: waitlist 5/min, invites 20/min,
  downloads 30/min, skins 20/min (`WRITE_RATE` in `cubeon-skins.js`, which
  deploys from the dashboard — the toml block mirrors the dashboard binding so a
  `wrangler deploy` produces the same Worker).
- **Measured live 2026-10-17, one fixed IP (the numbers the comments quote):**
  8 rapid POSTs → zero 429s, 25 → zero, 120 → 95 passed then 25 refusals. The
  **binding is the gate that works, and it works late** — Cloudflare documents
  Rate Limiting as "permissive, eventually consistent", and here it converged
  only after ~100 requests. The in-isolate fallback is best-effort: it can be
  **inert live**, because requests for a cold Worker need not share an isolate.
  It is still worth keeping (deterministic in `wrangler dev` and in the tests,
  and it fires on a warm isolate) — but do not describe it as the guarantee.
- **The per-IP caps are speed bumps, not walls, and the comments say so.** The
  scarce resource is the **account-wide** 1k KV writes/day (and the 100k
  requests/day, also account-wide — the download Worker shares it with the other
  four). Because the binding converges late, a flood gets ~190 writes' worth of
  signups through before it is held to ~5/min; after that 1k writes is hours
  away, not seconds, and the 00:00 UTC refill resets the window. The true fix for
  an unauthenticated write endpoint is a bot gate (Turnstile), not a per-IP cap.
- **"Already sound" is a claim that must be probed, not read.** `skins`,
  `invites` and `friends` all look fine on the authenticated paths — bearer
  secrets, constant-time compare, budgets. The skins holes were entirely on the
  *unauthenticated first-contact* path, which reading the auth code does not
  exercise. Write a probe.
- **Why `cubeon-friends.js` needs no name stamp (verified, not assumed).** Its
  names are OWNED: `httpClaim` compares the stored `secret_hash` and answers
  **409 `name_taken`** when a different secret claims an existing name (both on
  the normal path and in the concurrent-insert catch). So there is no
  displacement to guard — unlike skins, where `pointer:<name>` is an unowned
  last-writer-wins label by design and the secret only protects the *uuid*.
  That difference is the whole reason the two need different fixes; do not copy
  the skins `namemove` stamp into friends.
- `CUBEON_SKIN_API` now overrides the skins Worker base (parity with
  `CUBEON_FRIENDS_API` / `CUBEON_INVITE_API`) so a fork can point at its own
  deployment. `cubeon/skins.py` and `cubeon/faces.py` bind the constant at
  import time, so changing it needs a restart rather than a reload.
- **`tools/test_csl.py` was defeated by an ambient `CUBEON_GAME_DIR`**, because
  that variable *wins over HOME* in `cubeon/paths.py` and CI sets it for the
  whole job: the test wrote and CONSUMED ExtraList files in the shared real game
  dir instead of its own temp HOME. It now pops `CUBEON_GAME_DIR` before
  importing. Symptom if that regresses: "nothing registered before first run" /
  "only the api file is on disk" failing, then a `FileNotFoundError` on
  `cubeon-api.json`.
- **`worker/test-friends-metadata.mjs` still expected 12-digit UIDs** long after
  `c28b8f0` ("shorten Cubeon IDs") made them 8 (`UID_WIDTH = 8` in both
  `cubeon-friends.js` and `cubeon/friends.py`). Nothing in CI runs the `.mjs`
  tests, so it rotted silently. Changing a UID width means grepping the `.mjs`
  tests for the literal width too.

## Deleting the LAST instance repaints the whole Play area (2026-10-17) — INVARIANT-ish
- `refresh_version_list()`'s **"nothing installed" branch** is only reachable by
  deleting the last instance. It moves, not just re-renders, so anything that
  draws the selection must be reset there BY HAND: it calls `picker.sync_label()`
  (the compact Game-version button mirrors the dropdown and is NOT re-labelled
  otherwise), `_sync_instance_actions(None)` (the hero rename/delete pair),
  `version_issue_text.visible = False`, `update_pack_badge()`, then
  `refresh_mods_list()` / `refresh_browse_for_new_profile()` / `update_hero()`
  (the last one rebuilds the Jump back in row + hero title, so card/empty
  visibility and the banner come from there).
- `_sync_instance_actions(version_id)` (main.py, next to the two IconButtons) is
  the ONE owner of that pair's enabled/dimmed state - `on_version_selected` and
  the empty branch both call it. It is late-bound (defined after
  `on_version_selected`), safe because the first call is `refresh_version_list()`
  at the end of the build.
- `InstancesManager` (ui/versions.py) keeps ONE dialog + body and re-draws rows
  with `refresh()`, which `on_delete_instance` / `on_rename_instance` call after
  a successful action - a delete from a row leaves the dialog mounted, so
  without it the deleted row stays on screen until reopen. `open()` must not
  re-show a mounted dialog (Flet's `show_dialog()` raises) and tests membership
  in `page._dialogs.controls`: a barrier dismissal removes the dialog from that
  stack WITHOUT clearing `.open`, so the flag alone would make the Manage link
  stop working. `_close()` drops the reference so the next open builds a fresh
  dialog. Guarded by tools/test_version_ui.py sections 4-5.
- `InstanceCards.rebuild()` (ui/versions.py) is called from TWO threads - the UI
  selection path and the install/launch workers via
  `_rescan_installed -> update_hero`. It now serializes on a lock (body in
  `_rebuild()`); without it the pop-then-assemble order raised
  `KeyError: '<version id>'` on interleaving (1-in-5 flake in test_version_ui
  once a Play click was followed by a delete). Guarded by test_version_ui
  section 6. Still open: `_rescan_installed` touches ft controls off the event
  loop instead of going through `cubeon/thread_safe_ui`.

- **A release `--clobber` upload DELETES the asset before uploading the new one
  (2026-10-17) - INVARIANT-ish.** An upload that is interrupted in between
  therefore leaves the release with NO file under that name, not with the old
  one: a 600 s tool timeout during `gh release upload v1.1.2 ... --clobber`
  removed both `Cubeon-x86_64.AppImage` and `cubeon_1.1.2_amd64.deb` from the
  release while the local `dist/` copies were untouched. Run these uploads as a
  BACKGROUND process (`tools/` has no script for it; `logs/upload_linux_assets.sh`
  was the stopgap - three parallel uploads, per-asset log + exit status), and
  ALWAYS read the release back afterwards
  (`gh api repos/Shadow-457/Cubeon/releases/tags/v1.1.2 --jq '.assets[]|
  "\(.name) \(.size) \(.digest)"'`) - comparing `sha256sum` of the local files
  proves nothing about what is on the release.
- **A main push never touches the Linux assets.** CI's `build-linux-appimage`
  job (and its three release-upload steps) is gated on
  `startsWith(github.ref, 'refs/tags/v') || workflow_dispatch`, so a branch push
  rebuilds ONLY the Windows ZIP/Setup.exe and the macOS zip on the latest
  release and leaves the manually built AppImage/deb/Setup.sh alone. That is why
  a local AppImage rebuild + clobber can be pushed in any order.
