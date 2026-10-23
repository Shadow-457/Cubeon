"""
Cubeon - a Minecraft launcher UI built with Flet.
Dark control-room aesthetic, offline/cracked auth, version install+launch,
skin preview, RAM/Java settings, and mods folder management.

This is the main entry point for the launcher. It sets up the window,
loads configuration, builds the entire UI (Play, Skin, Mods, Settings tabs),
handles user interactions, and orchestrates game launching and mod management.

The code uses Flet for UI and relies on launcher_core.py for backend logic
(version installation, mod downloads, Java launching, etc.).
"""

# Standard library imports
import logging

import base64    # The Account panel's skin/cape previews are inlined as base64 (no file: src)
import os          # For file path/mtime handling (used for avatar cache-busting)
import asyncio     # For the filtered client-spawn wrapper (subprocess streams)
import subprocess  # Detached launcher fallback when execv cannot replace us
import re          # For regular expressions (used to clean mod slugs and parse version strings)
import sys         # For runtime platform detection and PyInstaller bundle paths
import threading   # For running long tasks (e.g., network calls, game launch) without freezing the UI
import time        # For the scheduled-backup timer loop
import signal      # For ending the leftover flet client process on session end
import tempfile    # For locating the flet client pid file (GPU-crash watcher)
import traceback   # For printing full tracebacks of swallowed launch errors to the console
import flet as ft  # Flet UI framework - provides widgets and app scaffolding

# Local module imports - our own helper functions for Minecraft-related logic
import launcher_core as core

# Opt-in startup timing (CUBEON_STARTUP_PROFILE=1). Imported this early so the
# first mark also covers most of main.py's own import cost.
from cubeon.startup_profile import mark as _startup_mark

# End-of-session cleanup slot. Flet 0.86 delivers no window events to
# Python on the real X button, so quit-time cleanup (Discord presence
# clear, friends stop, geometry save) is executed by the
# __main__ block right after ft.run returns - the one reliable "session
# ended" moment. main() registers its callable in the dict; the retry
# loop reads and clears it per attempt. Lives at module scope so main()
# can register it from any entry point (script OR test harness import).
_session_end = {"handler": None}

# Process-scoped Discord presence. See main() where it's created - the
# window can be closed and relaunched (Settings > Restart, GPU-crash
# recovery) within one process, and each new session must reuse THIS
# instance rather than stack a new retry-loop thread and IPC socket per
# session.
_rpc = None


def _dispatch_controller(kind: str, arg) -> None:
    """ControllerWatcher callback router (module-level so the ONE
    process-scoped watcher can serve any number of window sessions).

    The watcher runs all through the process life; the page it should
    toast on belongs to the CURRENT session. main() refreshes the
    "controller_page" slot each session; when no session is live
    (between sessions, during a relaunch) there is no window and events
    are dropped - correct: there's nothing to navigate with the window gone.
    """
    page = _session_runtime.get("controller_page")
    if page is None:
        return
    try:
        if kind == "event":
            _h = _session_runtime.get("controller_handlers")
            if _h and "event" in _h:
                _h["event"](arg)
        elif kind == "connect":
            _h = _session_runtime.get("controller_handlers")
            if _h and "connect" in _h:
                _h["connect"](arg)
        elif kind == "disconnect":
            _h = _session_runtime.get("controller_handlers")
            if _h and "disconnect" in _h:
                _h["disconnect"](arg)
    except Exception:
        pass

# Process-scoped state shared between main() (which builds the UI) and the
# __main__ session loop, plus the module-level dispatcher above. Anything here
# must survive a process replacement: the friends service/client (one
# connection per process, not per window session) and the gamepad watcher.
_session_runtime = {"friends_service": None, "friends_client": None,
                    "controller_page": None, "controller_handlers": None,
                    "controller_watcher": None}
# A user-requested relaunch ("Restart to apply" in Settings > Seasonal, and any
# future "apply and restart" flow). The execv must happen in the __main__ loop
# once ft.run has returned - doing it from inside main() would orphan the flet
# client as a ghost window, because `_kill_flet_client()` never gets to run.
_relaunch = {"request": None}

# Post-session SIGINT/SIGTERM presses, counted so the FIRST one can be graceful
# (finish the bounded teardown, then exit through the normal hard-exit) and the
# SECOND one is an immediate hard exit. See _reclaim_session_signals().
_session_signal_hits = {"n": 0}


def _reclaim_session_signals() -> None:
    """Take SIGINT/SIGTERM back from flet the moment the session has ended.

    flet installs its own exit_gracefully handler for both signals while the
    app runs and NEVER removes it - it only resets SIG_DFL from inside itself,
    and only when its own loop is still alive. Once ft.run has returned, that
    handler pokes an asyncio loop that is already closed
    (loop.call_soon_threadsafe -> RuntimeError('Event loop is closed')), and
    the exception is raised *from inside the signal handler*, on the main
    thread, at whatever frame happened to be running. Observed live
    2026-09-24: ^C right after the session ended landed in
    _ct.join(timeout=3.0) and escaped _session_loop() as a cubeon.fatal
    CRITICAL - the whole teardown (classification, geometry save) can be hit
    this way.

    From here on a signal is a plain quit request: the first press is counted
    and swallowed, so the bounded teardown finishes and the loop exits through
    its normal hard-exit; a second press - an impatient user - ends the
    process immediately, mirroring flet's own first-graceful/then-hard
    design. Called right after every ft.run return, so a retry session gets a
    fresh handler too.
    """
    _session_signal_hits["n"] = 0

    def _on_session_signal(signum, frame):
        _session_signal_hits["n"] += 1
        if _session_signal_hits["n"] >= 2:
            os._exit(0)  # second ^C: out NOW, teardown aborted

    for _name in ("SIGINT", "SIGTERM"):
        _sig = getattr(signal, _name, None)
        if _sig is None:
            continue  # platform without it (Windows has both, but be safe)
        try:
            signal.signal(_sig, _on_session_signal)
        except (ValueError, OSError):
            pass  # not the main thread, or the signal is unsupported here


def _relaunch_fresh_process() -> bool:
    """Replace this launcher with a fresh process, with a safe fallback.

    Flet is effectively once-per-process, so Settings > Restart and GPU-crash
    recovery must start a new interpreter.  On POSIX ``execv`` is preferred
    because it replaces this process outright (no second launcher, no race);
    on Windows - and whenever execv fails - the same command is started
    detached and the caller leaves through the normal hard-exit path.
    """
    if getattr(sys, "frozen", False):
        argv = [sys.executable] + sys.argv[1:]
    else:
        argv = [sys.executable, os.path.abspath(__file__)] + sys.argv[1:]

    env = os.environ.copy()
    # Tells the replacement image this is a deliberate relaunch, not a cold
    # start: it must not greet the user with an "orphaned session" prompt
    # about a game that is perfectly well looked after (see the watchdog
    # block in main()).
    env["CUBEON_RELAUNCH"] = "1"
    # PyInstaller >= 6.9 assumes a process spawned through sys.executable is a
    # WORKER that re-uses its parent's already-unpacked files. A restart is the
    # opposite: an INDEPENDENT instance that must outlive this process (which
    # deletes its extraction dir on exit in a onefile build). Without this flag
    # the replacement never comes up - the packaged Windows build's "restart
    # closes but never reopens". It is the documented way to implement
    # application restart; see PyInstaller's "Common Issues and Pitfalls" ->
    # "Implementing application restart".
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

    # POSIX: execv replaces this image in place. On Windows execv just goes
    # through CreateProcess with no advantage over a detached spawn, and the
    # frozen bootloader prefers the spawn path, so go straight there.
    if os.name != "nt":
        try:
            os.execve(sys.executable, argv, env)
        except OSError:
            pass  # a deleted/replaced executable (or a transient error): fall back

    # The parent must not keep running after handing off: it may still own
    # native Flet/GLib state and would race the replacement process.
    from cubeon.winproc import hidden
    try:
        subprocess.Popen(
            argv,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            **hidden(),
        )
        return True
    except Exception:
        # Both execv and the detached spawn failed: the caller is out of
        # in-process options (ft.run is once-per-process) and will exit, but
        # it does so knowing the relaunch did NOT happen.
        return False
from launcher_core import run_file_picker  # Version-safe FilePicker.pick_files() wrapper
from cubeon import thread_safe_ui  # Makes page.update() safe from background threads
from cubeon import motion  # The animation layer (hover/press/cascade/shimmer/ambience)
from cubeon import eta as cubeon_eta  # Measured "time left" for downloads
from cubeon import status_text as cubeon_status  # strips "<... at 0x...>" from labels
from cubeon import version_art  # Per-version wiki banners for the Play tab
from cubeon import dialogs as cubeon_dialogs  # Cross-Flet open/close/snackbar plumbing
from ui.skin_tab import build_skin_section, DEFAULT_CAPE_PREVIEW_SRC  # Imports the skin section builder, now embedded in the Profile dialog
from ui.mods_tab import build_mods_tab  # Imports the mods_tab builder function
from ui.modpacks_tab import build_modpacks_tab  # Imports the modpacks_tab builder function
from ui.server_tab import build_server_tab  # Imports the server_tab builder function
from ui.server_browse_tab import build_server_browse_tab  # Servers > Browse view
from ui.stats_tab import build_stats_tab  # Stats tab: playtime/library/cosmetics counters
from ui.settings_tab import build_settings_tab  # Settings tab: two-pane section rail + content
from ui.import_section import build_import_section  # Settings -> Import: scan a folder, import what it finds
from ui.seasonal_ui import (  # Seasonal badge/companion/ambience (the runtime half of cubeon/seasonal.py)
    SeasonalAnimator, build_ambience, build_badge as build_season_badge,
    build_perch as build_season_perch, icon_for as season_icon,
    pet_src as season_pet_src, quip_for as season_quip,
    reflow_ambience as season_reflow_ambience,
    update_badge as season_update_badge, update_pet as season_update_pet,
)
from ui.onboarding import build_onboarding  # First-run full-screen welcome/tour
from ui.crash_report import show_crash_dialog  # Game-crash report + log copy
from cubeon import seasonal as cubeon_seasonal  # Season detection/caching; the palette half runs in cubeon/__init__
from cubeon import friends  # Realtime social client (identity, presence, chat, calls)
from cubeon.friends_service import FriendsService  # Headless owner of friends/P2P (launcher Chat tab + in-game mod)
from cubeon.features import friends_enabled  # Development vs. public (no-Friends) builds
from ui.chat_tab import build_chat_tab  # Chat tab: friends list, requests, encrypted chat
from ui.screenshot_gallery import build_screenshot_gallery_tab
from ui.versions import (  # Play tab version management: picker, cards, instances manager
    VersionPicker, InstanceCards, InstancesManager,
)
from ui.window_chrome import (  # Windows-only custom frame widgets (policy: cubeon/winchrome.py)
    build_window_controls, set_maximized_glyph,
    build_resize_edges, set_resize_edges_visible,
)
from cubeon import winchrome  # Whether the frameless custom frame is used at all
from cubeon import instances as instance_info  # instance descriptors: loader / mods / size / last-played
from cubeon import shortcuts as cubeon_shortcuts  # keyboard shortcut table (F11 fullscreen, Ctrl+1..9, ...)
from cubeon.discord_rpc import DiscordPresence  # Optional Discord Rich Presence (no-op unless configured)
from cubeon.controller import ControllerWatcher  # Gamepad detection + menu driving (no-op without a pad)

# ---------------------------------------------------------------------------
# Design tokens - colors and fonts used throughout the UI.
#
# These now live in cubeon/theme.py rather than being defined here, because
# every tab module needs them and main.py can't be imported by them (it imports
# them, so that would be circular). They're re-exported into this module's
# namespace so the ~700 references below, and the `THEME`-passing call sites,
# keep working untouched.
# ---------------------------------------------------------------------------
from cubeon.theme import (  # noqa: E402  (kept with the other token setup)
    BG, BG_GLASS, SURFACE, SURFACE_HI, SURFACE_MAX, BORDER, BORDER_HI,
    ACCENT, ACCENT_HI, ACCENT_DIM, ON_ACCENT,
    TEXT, TEXT_DIM, TEXT_FAINT, DANGER, ON_DANGER, INFO, WARNING,
    FONT_DISPLAY, FONT_BODY, FONT_MONO,
    FONT_URLS, THEME, RADIUS, RADIUS_LG,
    CARD_FILL, CARD_BORDER, ROW_HOVER, ACCENT_TINT, ACCENT_DEEP,
    card as glass_card,
)
from cubeon import theme  # for theme.pixel_divider / theme.section_label
from cubeon import maintenance as maintenance_mod  # disk hygiene (see cubeon/maintenance.py)

# The four seasonal palettes that have a matching backdrop in assets/bg.
_SEASONAL_BACKDROPS = ("spring", "summer", "autumn", "winter")


def background_image_name(theme_key, bg_dir: str) -> str:
    """The backdrop file that suits `theme_key`.

    A seasonal palette boots with glass_<season>.jpg (generated by
    tools/make_background.py); everything else - green, a pinned --color, a
    template with no art - falls back to the green glass.jpg. Kept as a plain
    function so the choice is testable without building the whole UI.
    """
    if theme_key in _SEASONAL_BACKDROPS:
        candidate = f"glass_{theme_key}.jpg"
        if os.path.isfile(os.path.join(bg_dir, candidate)):
            return candidate
    return "glass.jpg"


def resolve_assets_dir() -> str:
    """Reliably find the 'assets' directory across all execution modes:
    - Running from source script (`python main.py`)
    - Running frozen by PyInstaller (`_internal/assets`, `sys._MEIPASS`, etc.)
    - Running inside Linux AppImage ($APPDIR)
    - Running inside Windows standalone exe/folder
    """
    candidates = []

    # 1. PyInstaller MEIPASS temporary extract dir (onefile mode)
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "assets"))

    # 2. PyInstaller executable directory (onedir mode)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "assets"))
        candidates.append(os.path.join(exe_dir, "_internal", "assets"))

    # 3. Linux AppImage environment
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.append(os.path.join(appdir, "usr", "bin", "assets"))
        candidates.append(os.path.join(appdir, "usr", "bin", "_internal", "assets"))
        candidates.append(os.path.join(appdir, "assets"))

    # 4. Source script location (__file__)
    try:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(this_dir, "assets"))
        candidates.append(os.path.join(this_dir, "_internal", "assets"))
        candidates.append(os.path.join(this_dir, "..", "assets"))
    except Exception:
        pass

    # 5. Current working directory
    candidates.append(os.path.join(os.getcwd(), "assets"))

    for path in candidates:
        if os.path.isdir(path):
            return os.path.abspath(path)

    # Fallback
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _explain_exit(code: int, lines=None) -> str:
    """Turns a game exit code + its last output into something actionable.

    The audience here is a kid whose game just closed, so this looks for the
    handful of causes that actually account for most failed cracked launches and
    names the fix. Anything unrecognised falls back to the real error line,
    which is still far better than the previous behaviour of showing nothing.
    """
    text = "\n".join(lines or [])
    low = text.lower()

    if "java.lang.outofmemoryerror" in low or "could not reserve enough space" in low:
        return "Crashed: out of memory. Lower RAM in Settings, or close other apps."
    if "unsupported class file major version" in low or "unsupportedclassversionerror" in low:
        return "Crashed: wrong Java version for this Minecraft version. Set Java in Settings."
    if "incompatible mod set" in low or "mod resolution encountered an incompatible" in low:
        return "Crashed: mods don't match this version. Disable mods on the Mods tab."
    if "org.lwjgl" in low and ("glfw" in low or "no opengl" in low or "failed to create window" in low):
        return "Crashed: graphics driver couldn't start the game window. Update your GPU drivers."
    # A Java problem may only be claimed from a Java-SPECIFIC line. This used to
    # read `"cannot run program" in low or "no such file or directory" in low
    # and "java" in low` - `and` binds tighter, so ANY "Cannot run program" line
    # in the game's output became "Java not found". And because the launch
    # command (with the JVM path) is itself part of that output, "java" in low
    # is true on EVERY launch, so any stray "No such file or directory" - a mod
    # config, a shader include, a missing native - was reported as missing Java.
    # That is the 2026-10-18 report verbatim: "minecraft crashes with this error
    # even if java fine bcz it ran minecraft in first place".
    #
    # So: one LINE must name java as the thing that failed. Matching on the line
    # (not the whole log) is what keeps the JVM path in the launch command from
    # counting as evidence.
    def _java_failure(lines):
        for line in lines or []:
            low_line = line.lower()
            if re.search(r'cannot run program\s+"?javaw?"?', low_line):
                return line
            if "could not create the java virtual machine" in low_line:
                return line
            if "unrecognized option" in low_line and "java" in low_line:
                return line
            if "no such file or directory" in low_line and "java" in low_line:
                return line
        return None

    java_line = _java_failure(lines)
    if java_line is not None:
        # The JVM names the offending option on its own line, then exits with
        # "Could not create the Java Virtual Machine" - so the option evidence
        # and the failure evidence are two different lines.
        if any("unrecognized option" in ln.lower() for ln in lines):
            return ("Crashed: Java rejected one of the launch options. Reset "
                    "the JVM arguments in Settings.")
        return ("Crashed: Java couldn't be started. Install Java, or set its "
                "path in Settings.")
    # A missing loader entrypoint means the classpath was wrong, so Fabric
    # could not start - the version's files are incomplete or broken. Do NOT
    # claim Cubeon fixed it: the client.json repair (_sanitize_client_json /
    # _restore_emptied_arguments in cubeon/launch.py) already runs BEFORE every
    # spawn, so if the game still died this way the repair was attempted and
    # did not help. The old "Cubeon repaired it. Press Play again." promised a
    # fix that had never worked, and left users relaunching a broken version
    # forever instead of reinstalling it (the reported "it says it fixed it but
    # it isn't actually fixed" confusion).
    if "knotclient" in low or "knotserver" in low:
        return ("Crashed: Fabric couldn't start - this version's files look "
                "incomplete. If pressing Play again still crashes, reinstall "
                "this version from the Play tab.")
    if "classnotfoundexception" in low and "net.minecraft" in low:
        return ("Crashed: the game files for this version look incomplete. "
                "Reinstall it, or pick another version.")

    # Nothing recognised - surface the last line that looks like an actual
    # error, rather than the harmless final log line.
    for line in reversed(lines or []):
        if any(marker in line.lower() for marker in
               ("exception", "error", "caused by", "fatal")):
            return f"Crashed (exit {code}): {line.strip()[:140]}"
    # Still nothing. Do NOT fall back to blaming Java: the game ran far enough
    # to produce output, and the two Java cases that CAN be proven (wrong
    # version, JVM wouldn't start) are named above from their own evidence.
    # Guessing "check that Java matches" sent people off fixing a Java install
    # that was already working - the game it just launched proves it. Say only
    # what is true, and name the one action worth trying next.
    return (f"Crashed (exit {code}) - the game closed without naming a cause. "
            f"Press Play again; if it keeps happening, run Fix problems on the "
            f"Mods tab.")


def _classify_session_end(ui_painted: bool, client_exit):
    """Why a flet session ended, using the client process's exit status.

    flet 0.86's ``ft.run()`` reaps the desktop client itself (``await
    fvp.wait()``) and only returns once the client is already gone, so a live
    child process can never be observed here - the old "is a flet child alive?"
    test was always false and made every normal close look like a crash.

    ``client_exit`` is the returncode captured by ``_capture_flet_client_exit``:
    ``0`` (or any non-negative) is a normal exit, a negative value is a
    signal death (``-11`` SIGSEGV, ``-6`` SIGABRT, ...), and ``None`` means it
    could not be observed. Returns one of:
      * ``"pre_paint_crash"``  - died before the window showed
      * ``"mid_session_crash"``- died to a signal after the window showed
      * ``"clean_close"``      - a normal close (default when unsure)

    A client that exited 0 is ALWAYS a clean close, even when the paint
    marker is missing: the marker write is best-effort (OSError-swallowed),
    and treating "marker lost + exit 0" as a pre-paint crash is exactly the
    bug that made Cubeon close and immediately reopen itself with software
    OpenGL after a perfectly normal session.
    """
    if client_exit is not None and client_exit < 0:
        return "mid_session_crash" if ui_painted else "pre_paint_crash"
    if client_exit == 0:
        return "clean_close"
    return "pre_paint_crash" if not ui_painted else "clean_close"


# A window close/hide/disconnect event is the user asking the window to go
# away. If the flet client then dies to a SIGNAL within this many seconds, that
# is teardown noise from a flaky GPU driver - NOT a crash worth auto-reopening
# for. Without this the mid-session recovery re-execs the launcher and the
# window pops straight back up after the user closed it (the reported "why did
# it launch again when I close, it's annoying"). A genuine mid-session crash
# has NO preceding window event, so it is completely unaffected.
_CLOSE_GRACE = 10.0


def _apply_dismissed_close(kind: str, dismissed_at, now: float) -> str:
    """Downgrade a crash to a clean close once the user dismissed the window.

    ``dismissed_at`` is the monotonic time of the last window close/hide/
    disconnect event (see ``_arm_window_gone_exit``), or None if none arrived.
    """
    if (kind != "clean_close" and dismissed_at is not None
            and (now - dismissed_at) <= _CLOSE_GRACE):
        return "clean_close"
    return kind


def _live_flet_clients(assets_dir: "str | None" = None) -> "list[int]":
    """PIDs of the flet desktop client(s) this launcher owns that are ALIVE.

    Zombies are skipped: a dead-and-unreaped client is not a reason to keep
    the process around (that is the "background after close" case). Matched
    two-factor (our child, or our assets dir in the command line) so a second
    live Cubeon is never touched; the "flet" name filter excludes Minecraft
    (java). Never raises.
    """
    try:
        import psutil
    except Exception:
        return []
    me = os.getpid()
    out = []
    for proc in psutil.process_iter(["pid", "name", "ppid", "cmdline",
                                     "status"]):
        try:
            info = proc.info
            if "flet" not in (info.get("name") or "").lower():
                continue
            if info.get("status") == getattr(psutil, "STATUS_ZOMBIE", "zombie"):
                continue  # already gone, only the exit status is pending
            cmdline = " ".join(info.get("cmdline") or [])
            if info.get("ppid") == me or (assets_dir and assets_dir in cmdline):
                out.append(int(info.get("pid") or 0))
        except Exception:
            continue
    return [p for p in out if p > 0]


def _terminate_flet_clients(assets_dir: "str | None" = None) -> int:
    """Ends the flet desktop client process(es) this launcher started.

    Used whenever a windowless leftover must not survive: there is no /proc
    on Windows/macOS, and the desktop client can outlive the window, which is
    exactly the reported "Cubeon is still running in the background after I
    close it". Best-effort; returns how many were ended.
    """
    try:
        import psutil
    except Exception:
        return 0
    ended = 0
    for pid in _live_flet_clients(assets_dir):
        try:
            psutil.Process(pid).kill()
            ended += 1
        except Exception:
            pass
    return ended


# ---------------------------------------------------------------------------
# "The window is gone, but the process is still here" watchdog.
#
# The window-close path runs ON flet's event loop, so it must never do work
# that can block: the observed failure (2026-10-06) was a Discord RPC
# self-deadlock inside _rpc.close() freezing the loop, after which ft.run()
# could not return and the launcher sat there with no window - the reported
# Linux AND Windows background bug. So close-time code only SAVES and ARMS;
# this timer is what actually leaves the process if ft.run() never comes back.
#
# It is deliberately conservative: it gives up whenever ft.run() already
# returned (the session loop owns the exit, including a pending relaunch) or
# whenever a flet client is still alive (a minimize, not a close).
# ---------------------------------------------------------------------------
_window_gone = {"timer": None, "ft_returned": False, "dismissed_at": None}


def _arm_window_gone_exit(reason: str, delay: float = 3.0) -> None:
    """Arms the last-resort exit for a window that vanished. Idempotent."""
    # Remember WHEN the window was dismissed: _session_loop uses this to tell
    # a flaky-driver death during teardown (the user is closing - never
    # reopen) from a genuine mid-session crash (recover). Recorded even when a
    # timer is already armed, because a repeated hide is still the user
    # asking the window to go away.
    _window_gone["dismissed_at"] = time.monotonic()
    if _window_gone["ft_returned"]:
        return  # ft.run() returned: _session_loop is already handling the end
    timer = _window_gone.get("timer")
    if timer is not None and timer.is_alive():
        return  # already armed by an earlier close/hide event
    t = threading.Timer(delay, _window_gone_finish, args=(reason,))
    t.daemon = True
    _window_gone["timer"] = t
    t.start()


def _window_gone_finish(reason: str) -> None:
    """Timer body: leave the process when nothing else is going to."""
    _window_gone["timer"] = None
    if _window_gone["ft_returned"]:
        return  # the session loop took over while we were waiting
    # A pending "Restart to apply" (Settings > Seasonal) outranks everything
    # else, including the live-client guard below. The Restart button closes
    # the window through the native close request, which on Linux/KDE can
    # arrive as a HIDE with the flet client still alive: the guard would then
    # treat a deliberate restart as a minimize and return, stranding the user
    # with a hidden window and a process that never re-execs ("restart closes
    # but never reopens"). When a relaunch is armed that cannot happen - the
    # restart IS the reason the window is going away.
    _rl = _relaunch.get("request")
    _relaunching = _rl is not None and _rl.is_set()
    if not _relaunching:
        try:
            if _live_flet_clients(resolve_assets_dir()):
                return  # client still up: a minimize or a reconnect, not a close
        except Exception:
            pass
    print(f"cubeon: window gone ({reason}) and ft.run() never returned - "
          "exiting so nothing is left running in the background")
    # Bounded: whatever cleanup is still pending gets a daemon thread and 2s,
    # so a wedged teardown can never become the new hang.
    _cleanup = _session_end.get("handler")
    if _cleanup is not None:
        _session_end["handler"] = None
        try:
            _ct = threading.Thread(target=_cleanup, daemon=True,
                                   name="cubeon-gone-cleanup")
            _ct.start()
            _ct.join(2.0)
        except Exception:
            pass
    # "Restart to apply" (Settings > Seasonal) outranks a plain close here,
    # exactly as it does in _session_loop: the user asked for a re-exec, and
    # leaving the process instead would make the Restart button look broken.
    _relaunched = False
    if _relaunching:
        print("cubeon: restart requested - relaunching to apply seasonal "
              "settings")
        try:
            _relaunched = _relaunch_fresh_process()
        except Exception as ex:
            print(f"cubeon: relaunch via re-exec failed ({ex})")
    if not _relaunched:
        # Only sweep clients when no replacement is coming: the detached spawn
        # may already be bringing up ITS client, and killing every process that
        # matches our assets dir would take that one down too ("restart closes
        # but never reopens", again).
        try:
            _terminate_flet_clients(resolve_assets_dir())
        except Exception:
            pass
    os._exit(0)


def _capture_flet_client_exit(slot: dict) -> None:
    """Installs a one-time wrapper that records the flet client's exit status.

    Only flet's own ``await fvp.wait()`` sees that status before the child is
    reaped, so we wrap the process object the moment ``ft.run`` obtains it and
    stash ``returncode`` into ``slot["code"]``. The classification then comes
    from ``_classify_session_end``. Best-effort: if the API moves, the slot
    stays ``None`` and every end is treated as a clean close (never a
    surprise relaunch).
    """
    try:
        import flet_desktop
    except Exception:
        return
    original = getattr(flet_desktop, "open_flet_view_async", None)
    if original is None or getattr(original, "_cubeon_exit_capture", False):
        return

    class _ClientExitProxy:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        async def wait(self):
            try:
                result = await self._real.wait()
            except BaseException:
                slot["code"] = None
                raise
            slot["code"] = self._real.returncode
            return result

    async def _wrapped(*args, **kwargs):
        proc, pid_file = await original(*args, **kwargs)
        return _ClientExitProxy(proc), pid_file

    _wrapped._cubeon_exit_capture = True
    flet_desktop.open_flet_view_async = _wrapped


def fit_geometry_to_area(width, height, left, top, area):
    """Fits a saved window rect inside a usable-desktop rect.

    Pure on purpose, so it can be unit-tested without an X server (see
    tools/test_startup.py). ``area`` is ``(x, y, w, h)`` or None when the
    desktop cannot be probed; with no area the geometry comes back untouched.

    Both axes are clamped to the work area, and a saved position is pulled
    back inside it. A window manager clamps every window to the WORK AREA
    (the screen minus panels/docks), and a client that asked for MORE waits
    forever for an OpenGL frame at the size it requested, then dies before
    the finished UI paints:

        Timed out waiting for OpenGL frame of size 1900x1170 (have 1872x1170)

    That is the "if I size it too much it won't open on the second launch"
    report (2026-10-16): the saved size is only restored on the NEXT start,
    so the window the user dragged large is the one that never appears.
    """
    if not area:
        return width, height, left, top
    ax, ay, aw, ah = (int(v) for v in area)
    w, h = min(int(width), aw), min(int(height), ah)
    if left is not None and top is not None:
        left = max(ax, min(int(left), ax + aw - w))
        top = max(ay, min(int(top), ay + ah - h))
    return w, h, left, top


async def main(page: ft.Page):
    """
    This is the main function that Flet calls when the app starts.
    It receives a `page` object representing the application window.
    We set up the page properties, load configuration, build all UI components,
    and define the app's behavior (callbacks, background threads, etc.).

    It is a COROUTINE (Flet awaits it - see flet/app.py). That matters: the
    window starts hidden and the splash below is only painted once we hand the
    event loop back, so the build MUST happen after an ``await``. A synchronous
    main() blocked the loop for the whole build, so the splash never reached the
    client and the window stayed hidden until everything was done - the "slow
    startup / process running with no window" report.
    """
    # Make page.update() safe to call from the background threads this file
    # starts. Without this, Flet 0.80+ silently loses those updates until some
    # unrelated input wakes its event loop - which is what made the Play button
    # sit on "Preparing" until you switched tabs. See cubeon/thread_safe_ui.py.
    thread_safe_ui.install(page)

    # Dev-only live UI inspector (CUBEON_INSPECT=1 or cfg["dev_inspector"]):
    # a DevTools-style dialog for browsing the mounted control tree and
    # editing text/tooltips live. Off by default; public builds never show
    # it. See cubeon/inspector.py. (Gate is set after cfg loads below.)
    from cubeon.inspector import open_inspect
    _inspector_enabled = False

    def _open_inspector():
        try:
            open_inspect(page)
        except Exception:
            traceback.print_exc()
            _show_snack("Inspector failed to open - see cubeon.log")

    # Central logging BEFORE anything else can fail: from here on, every
    # cubeon/ module's log calls land in ~/.cubeon_launcher/cubeon.log and
    # any uncaught exception (any thread) is written there with a traceback.
    from cubeon.logging_setup import setup_logging
    setup_logging()
    _startup_mark("main() entered (flet client already spawned/connected)")
    # --- Basic window configuration ---
    page.title = "Cubeon"
    # The window gets the opaque default here; the saved geometry and glass
    # mode are applied by _apply_real_geometry() the moment the config is
    # loaded - still on a HIDDEN window (see that function's docstring). The
    # splash card paints an opaque layer over the whole window, so a
    # translucent window background can never make the loading screen hard
    # to read.
    page.window.bgcolor = BG
    page.bgcolor = BG
    page.padding = 0
    # The window process must ALREADY be started hidden (see ft.run below,
    # view=FLET_APP_HIDDEN): the client creates its window before Python's
    # first message can arrive, so setting visible=False here would only
    # hide a window that had already flashed on screen once. With a hidden
    # start, the ONLY transition is hidden -> fully-painted reveal at the
    # bottom of main() - no flash, no hide/show double-take.
    # Restore the last window geometry instead of forcing 1180x760 every
    # launch - a user who resized their window shouldn't watch it snap
    # back every start (that resize-jump IS most of the "cheap" feel).
    # Saved by _save_window_geometry below on move/resize/close. Falls back
    # to the design default on first run / corrupt state.
    _geom = core.load_window_geometry()

    def _geom_num(key, lo, hi, default):
        try:
            v = _geom.get(key)
            if v is None:
                return default
            v = float(v)
            return default if (v < lo or v > hi) else v
        except (TypeError, ValueError):
            return default

    # 1060 wide, not the old 1180: at 1180 the Play tab's content had more
    # empty gutter than the layout needs, which read as a window stretched to
    # fill space rather than sized for its content.
    _LEGACY_DEFAULT_W = 1180  # what every pre-existing install has saved
    _gw = _geom_num("width", 980, 7680, 1060)
    if int(_gw) == _LEGACY_DEFAULT_W:
        # A saved width identical to the OLD default means the user never
        # deliberately resized - it's just the default that got persisted on
        # first close, so it should follow the new default. Someone who did
        # pick exactly 1180 loses it once; every other width is respected.
        _gw = 1060
    _gh = _geom_num("height", 640, 4320, 760)
    _gl = _geom_num("left", -3840, 15360, None)
    _gt = _geom_num("top", -2160, 8640, None)
    _saved_maximized = bool(_geom.get("maximized"))
    # Off-screen guard: a restored position from a monitor that's gone would
    # strand the window in unreachable space. -3840/-2160 allow one virtual
    # monitor to the left/above, but the position is dropped entirely if
    # invalid; the reveal task re-centers before showing.
    # (0, 0) is the native window's pre-reveal placeholder on some Linux/Flet
    # builds, not a deliberate saved location. Treat the old bad capture as
    # missing so the finished window is centered once and can then persist its
    # real position.
    _needs_center = (_gl is None or _gt is None or (_gl == 0 and _gt == 0))
    _geometry_ready = False

    def _screen_size():
        """Primary monitor size (w, h), or None.

        No screen API on Page in Flet 0.86, so read it from the platform.
        xrandr is the simplest reliable route that needs no new dependency
        (GDK_SCALE-style envs are wrong on multi-monitor): one process spawn,
        once per startup.
        """
        try:
            out = subprocess.run(
                ["xrandr", "--current"], capture_output=True, text=True,
                timeout=3).stdout
            # first connected monitor's "WxH+X+Y"
            m = re.search(r"(\d+)x(\d+)\+\d+\+\d+", out)
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass  # no xrandr / not X11: the WM picks a position - fine
        return None

    def _work_area():
        """Usable desktop rect (x, y, w, h), or None when unknowable.

        This is the screen MINUS the panels/docks - exactly the rectangle a
        window manager clamps its windows to. On Windows it is the same rect
        the shell reports as the work area. See _fit_geometry_to_work_area
        for why a window has to fit inside it.
        """
        if sys.platform == "win32":
            try:
                import ctypes

                class _RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

                r = _RECT()
                # SPI_GETWORKAREA = 0x0030
                if ctypes.windll.user32.SystemParametersInfoW(
                        0x0030, 0, ctypes.byref(r), 0):
                    w, h = r.right - r.left, r.bottom - r.top
                    if w > 0 and h > 0:
                        return r.left, r.top, w, h
            except Exception:
                pass
            return None
        try:
            out = subprocess.run(
                ["xprop", "-root", "-notype", "_NET_WORKAREA"],
                capture_output=True, text=True, timeout=3).stdout
            m = re.search(r"=\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", out)
            if m:
                x, y, w, h = (int(g) for g in m.groups())
                if w > 0 and h > 0:
                    return x, y, w, h
        except Exception:
            pass  # no xprop / not X11: fall back to the raw screen size
        return None

    def _fit_geometry_to_work_area():
        """Shrinks/relocates a saved geometry the window manager cannot grant.

        A window manager clamps every window to the WORK AREA (screen minus
        panels/docks), and a client that asked for MORE waits forever for an
        OpenGL frame at the size it requested, then dies before the finished
        UI paints:

            Timed out waiting for OpenGL frame of size 1900x1170 (have 1872x1170)

        (KDE reserves 48 px on this 1920-wide screen, so the window came back
        1872 wide and the client waited on a size that could never arrive.)
        That is the "if I size it too much it won't open on the second launch"
        report (2026-10-16): the saved size is only restored on the NEXT start,
        so the very window the user dragged large is the one that never
        appears. Fitting it to the work area keeps the request grantable, and
        the corrected size is what gets saved back on the next write.
        """
        nonlocal _gw, _gh, _gl, _gt
        _gw, _gh, _gl, _gt = fit_geometry_to_area(
            _gw, _gh, _gl, _gt, _work_area())

    def _apply_real_geometry():
        """Applies the user's saved window size/position to the HIDDEN window.

        Called right before the splash is revealed, and again on the finished
        UI where every value is already correct (an unchanged size is a no-op
        for the client, so nothing resizes). It must never be the first thing
        a VISIBLE window hears: resizing a visible flet window makes the
        desktop client wait for an OpenGL frame at the new size, and on some
        Mesa/GTK setups that wait times out - "Timed out waiting for OpenGL
        frame of size WxH (have WxH)" - and the client dies before the
        finished UI paints, so the launcher flashes and closes. It showed up
        most reliably on the SECOND launch, because by then the saved geometry
        is whatever (larger) size the user dragged the window to (user report
        2026-10-16).

        Same rationale as before for using plain left/top numbers instead of
        window.center() - center() fires an async GTK resize that crashed the
        Mesa/gallium driver mid first-frame (SIGSEGV coredumps, 2026-09-06).
        """
        _fit_geometry_to_work_area()
        page.window.min_width = min(980, int(_gw))
        page.window.min_height = min(640, int(_gh))
        page.window.resizable = True
        if _saved_maximized:
            # Do NOT ask for the saved rect as a window SIZE when the window
            # should be maximized. That rect is the MAXIMIZED one, and on a
            # scaled desktop it is expressed in X pixels while the flet client
            # works in logical pixels - asking for it made the client wait for
            # an OpenGL frame that could never arrive ("Timed out waiting for
            # OpenGL frame of size 1872x1172 (have 1440x900)", 2026-10-23),
            # so the launcher died before the finished UI painted. Maximize
            # alone lets the WM pick the real screen size; the saved rect is
            # only the restore size for the non-maximized path.
            page.window.maximized = True
        else:
            page.window.width = _gw
            page.window.height = _gh
            if not _needs_center:
                page.window.left = _gl
                page.window.top = _gt
            else:
                area = _work_area()
                if area:
                    _ax, _ay, _aw, _ah = area
                    page.window.left = max(0, _ax + (_aw - int(_gw)) // 2)
                    page.window.top = max(0, _ay + (_ah - int(_gh)) // 2)
                else:
                    size = _screen_size()
                    if size:
                        page.window.left = max(0, (size[0] - int(_gw)) // 2)
                        page.window.top = max(0, (size[1] - int(_gh)) // 2)
                # When screen probing fails, _reveal_window() awaits the native
                # async center method after mapping. This function is synchronous
                # and must not call Window.center() without awaiting it.
            page.window.maximized = False
        # Glass mode: translucent window + glass canvas. Only the BACKGROUND
        # goes translucent - panels/text keep full opacity, so contrast is
        # unchanged. A compositor that refuses alpha simply shows the colours
        # opaque (ARGB alpha is best-effort on every platform).
        _glass = bool(cfg.get("glass_mode_enabled", True))
        if _glass:
            page.window.bgcolor = BG_GLASS
            page.bgcolor = BG_GLASS
        nonlocal _geometry_ready
        _geometry_ready = True

    # App/taskbar/titlebar icon - falls back gracefully if not supported.
    # On Windows: window_manager requires .ico (e.g. icon.ico).
    # On Linux/macOS: window_manager requires .png (e.g. icon_256.png).
    try:
        _assets_folder = resolve_assets_dir()
        if sys.platform == "win32":
            _ico = os.path.join(_assets_folder, "icon.ico")
            if os.path.isfile(_ico):
                page.window.icon = _ico
            else:
                page.window.icon = "icon.ico"
        else:
            for _png_name in ("icon_256.png", "icon_512.png", "icon_128.png", "icon_64.png", "icon_32.png", "icon_16.png"):
                _png_path = os.path.join(_assets_folder, _png_name)
                if os.path.isfile(_png_path):
                    page.window.icon = _png_path
                    break
    except Exception:
        pass

    # --- Load bundled fonts from the local asset dir ---
    # Minecraftia + Inter ship inside assets/fonts (paths resolved against
    # assets_dir), so nothing is fetched from the web at startup - the window
    # can appear instantly and even fully offline. URLs live beside the family
    # names in cubeon/theme.py, so a font can't be referenced by name without
    # also being registered here.
    page.fonts = dict(FONT_URLS)
    # Install the full design system (rounded shapes + on-palette ColorScheme for
    # every default Flet control - dialogs, buttons, menus, scrollbars). See
    # cubeon/theme.apply_page_theme for the colour-theory rationale.
    theme.apply_page_theme(page)

    # --- Startup splash: something on screen while the UI builds ----------
    # The window process is created hidden (FLET_APP_HIDDEN at ft.run) and
    # this function used to build the entire control tree before revealing
    # anything, so a cold start was seconds of a desktop icon that looked
    # like it had done nothing. Instead the window now opens right away with
    # a "Loading Cubeon" card and the finished UI replaces it in one shot at
    # the end of main(). Built after the fonts/theme are applied so it uses
    # the real design tokens.
    #
    # Load the config first: it is a plain disk read (~1 ms) and it is what
    # lets the saved geometry + glass mode land on the still-hidden window
    # below. The splash is NOT a small window that grows - it is a card in
    # the window the app will keep, so nothing is ever resized while visible
    # (see _apply_real_geometry's docstring: that resize is what killed the
    # client on the second launch).
    cfg = core.load_config()  # returns a dict with keys like "username", "ram_mb", "last_version", etc.
    _startup_mark("config loaded")

    # Motion level (cubeon/motion.py): set before ANY widget exists, because
    # controls decide at build time whether they own a scale/opacity to animate
    # from (see motion's rule 2). The live level is re-read at event time too,
    # so the Settings dropdown can still change it mid-session.
    motion.set_level(cfg.get("motion_level", motion.DEFAULT_LEVEL))

    # --- Custom window frame (Windows-only prototype) ----------------------
    # The frameless window: the OS title bar is dropped and the app's OWN top
    # bar becomes the title bar (see the chrome block before _build_top_bar, the
    # WindowDragArea wrap where _app_root is assembled, and cubeon/winchrome.py
    # for the rationale - on Windows the native bar stacked a second,
    # off-design-system "Cubeon" header above the branded one).
    #
    # Set HERE, before _apply_real_geometry() and while the window is still
    # HIDDEN (view=FLET_APP_HIDDEN at ft.run): a frame toggled later would
    # re-map the window, and on this flet build every window write is a message
    # the desktop client has to be alive to process - the failure mode behind
    # "Cubeon.exe is running but no window ever appears" (see the Windows reveal
    # invariant in agents/docs/module-map.md). If the write fails the flag is
    # cleared, so the UI falls back to the native frame instead of drawing
    # buttons for a window that never went frameless.
    _custom_chrome = winchrome.custom_chrome_enabled(cfg)
    if _custom_chrome:
        try:
            page.window.frameless = True
        except Exception:
            _custom_chrome = False
    # Title-bar buttons + resize hot-zones: filled in when the top bar is built
    # and when the app root is assembled; kept here so the window-event handler
    # can restyle them.
    _chrome_ctl = {}
    _resize_edges = []

    _apply_real_geometry()

    # The "Shadow mark": the Cubeon logo sits on a rounded tile that casts a
    # soft accent shadow, so the splash reads as a branded card rather than a
    # bare icon on a flat panel. The progress ring is drawn client-side, so it
    # keeps spinning smoothly even while the synchronous build below blocks
    # Python's event loop - the splash never freezes or flickers.
    _splash = ft.Container(
        expand=True,
        bgcolor=BG,
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Image(
                        src=os.path.join(resolve_assets_dir(), "icon_256.png"),
                        width=72, height=72, fit=ft.BoxFit.CONTAIN),
                    border_radius=20,
                    shadow=ft.BoxShadow(
                        blur_radius=30, spread_radius=1,
                        color=ft.Colors.with_opacity(0.45, ACCENT),
                        offset=ft.Offset(0, 7),
                    ),
                ),
                ft.Text("Cubeon", size=22, color=TEXT, font_family=FONT_DISPLAY),
                ft.Text("Loading…", size=12, color=TEXT_DIM),
                ft.ProgressRing(width=18, height=18, stroke_width=2,
                                color=ACCENT),
            ],
            spacing=10, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
    )
    page.add(_splash)

    # One OS-level backstop per window session (both reveals call it). main()
    # is re-invoked per session, so a retry after a pre-paint crash gets a
    # fresh one.
    _window_backstop = {"armed": False}

    def _show_window():
        """Tell the desktop client to show its window.

        A bare ``page.window.visible = True`` is a NO-OP, and that is exactly
        how the launcher came to run with NO WINDOW on Windows (2026-10-15):
        ``Cubeon.exe`` sat in Task Manager, nothing appeared anywhere. Flet
        declares ``Window.visible`` with a default of True, and ``Prop.__set__``
        DROPS any write equal to the declared default - no value stored, no
        dirty flag, nothing sent. The client is created with
        ``AppView.FLET_APP_HIDDEN``, so once it honoured that flag it was never
        told to show anything.

        Writing False first stores a real state, which makes the True a genuine
        change; the emitted patch carries ``visible: true`` and the window
        appears. Where the hidden start is NOT honoured (Linux/GTK and Wine map
        the window anyway) the window is already visible, the patch is a
        no-op, and nothing flickers - which is why this looked fine during
        local and Wine testing. Do NOT "simplify" this back to one assignment;
        tools/test_ui_smoke.py pins it.
        """
        try:
            page.window.visible = False
            page.window.visible = True
        except Exception:
            return
        try:
            page.window.update()
        except Exception:
            pass

    async def _reveal_to_front():
        """The one reveal the client cannot skip.

        ``page.window.visible = True`` is a PROPERTY patch, and the desktop
        client only calls windowManager.show() when the value differs from its
        OWN cached window state - so on a build whose client already holds
        ``visible: true`` the patch is a no-op and the native window stays
        hidden (the reported "running with no window" on a current Windows
        build, 2026-10-16). ``to_front()`` is a METHOD call, and the client's
        implementation of it calls show() unconditionally, with no
        isVisible() guard. Bounded: a wedged client never answers.
        """
        try:
            await asyncio.wait_for(page.window.to_front(), timeout=5)
        except Exception:
            pass  # non-desktop, an old client, or one that never answers

    def _nudge_window_to_front():
        """Orders `_reveal_to_front` without waiting on it (see above)."""
        try:
            page.run_task(_reveal_to_front)
        except Exception:
            pass  # headless/test harness: nothing to schedule on

    def _backstop_window_visible():
        """Windows: make sure our own client window is really on screen.

        Every flet-level reveal above is a MESSAGE to the desktop client, and
        that client is started hidden (FLET_HIDE_WINDOW_ON_START, from
        ``view=FLET_APP_HIDDEN`` at ft.run). If a message is dropped, races the
        client's startup, or the client's UI thread never gets to it, the
        launcher lives on INVISIBLE - Cubeon.exe in Task Manager with no
        window anywhere, and nothing in cubeon.log, because a launcher that
        never shows a window cannot report anything. That is the user report
        this is here for (2026-10-15, and again on the shipped 1.1.2 build on
        2026-10-16).

        So ask the OS instead of the client: cubeon/winwindow.py finds OUR flet
        client's top-level window and ShowWindow()s it, then logs the outcome
        either way. On a daemon thread - it polls for up to 10s and must never
        sit on flet's event loop. A no-op off Windows.
        """
        if sys.platform != "win32" or _window_backstop["armed"]:
            return
        _window_backstop["armed"] = True

        def _work():
            try:
                from cubeon import winwindow
                winwindow.ensure_client_window_visible(resolve_assets_dir())
            except Exception:
                logging.getLogger(__name__).debug(
                    "window-visibility backstop failed", exc_info=True)

        threading.Thread(target=_work, name="cubeon-window-visible",
                         daemon=True).start()

    async def _reveal_splash():
        # Bounded: this is a handshake with the desktop client, and a client
        # that never answers (or a platform where it never resolves) must not
        # be allowed to keep a hidden window hidden forever. Showing the splash
        # late is a cosmetic loss; never showing it is the bug.
        try:
            await asyncio.wait_for(
                page.window.wait_until_ready_to_show(), timeout=5)
        except Exception:
            pass  # non-desktop, an odd runtime, or a slow client: visible still applies
        _show_window()
        # Belt: the property patch above. Braces: the method call that cannot
        # be skipped, and (on Windows) the OS-level ShowWindow. See each
        # helper's docstring - the window must never be left to one message.
        _nudge_window_to_front()
        _backstop_window_visible()

    # AWAIT the reveal instead of scheduling it. This is the whole fix: awaiting
    # hands control back to Flet's event loop, which flushes the queued splash
    # patches (page.add(_splash), the window settings above, the visible=True
    # patch) to the desktop client BEFORE the heavy synchronous control-tree
    # build further down. Previously this was scheduled with run_task - a task
    # that only ran once main() had already returned, i.e. AFTER the build - so
    # the splash was never painted and the window stayed hidden.
    try:
        await _reveal_splash()
    except Exception:
        # Belt-and-braces for an odd runtime: still try the synchronous show.
        _show_window()
    # Give the client a beat to paint the first splash frame while we still hold
    # the loop. Bounded and best-effort: a client that never answers must not
    # delay the build, and a fast client is only held for this long.
    try:
        await asyncio.sleep(0.12)
    except Exception:
        pass
    _startup_mark("splash revealed and flushed to the client")

    # cfg was loaded above, before the saved geometry was applied to the
    # window.

    # Now that cfg exists, evaluate the inspector gate (env var or
    # cfg["dev_inspector"]). Set here so the sidebar (built far below)
    # and the F12 hook both see the resolved value.
    from cubeon.inspector import inspector_enabled as _insp_enabled
    _inspector_enabled = _insp_enabled(cfg)

    # --- Disk hygiene: tidy Cubeon's own folders, off the UI thread ---
    # Idempotent and non-destructive (see cubeon/maintenance.py): it merges
    # stray game assets back into assets/objects/, drops superseded duplicates
    # from the global mod/content stores, archives foreign-launcher leftovers
    # to <game>/_legacy/ and clears .part/.tmp debris. It NEVER touches game
    # content (saves, versions, mods, packs, worlds). Turn it off by setting
    # auto_organize_files to false; the Settings button still runs it on demand.
    threading.Thread(
        target=maintenance_mod.run_at_startup, args=(cfg,),
        name="cubeon-maintenance", daemon=True,
    ).start()

    # --- Optional Discord Rich Presence ("Cubeon" on your Discord profile) ---
    # Only does anything if Discord is running AND the user has pasted a Discord
    # application id into config (discord_client_id). Every call is a silent
    # no-op otherwise, so a missing/misconfigured Discord never breaks the app.
    # See cubeon/discord_rpc.py for the two required Discord-side steps.
    #
    # Process-scoped: the process can be relaunched in place (Settings >
    # Restart, GPU-crash recovery) and a new DiscordPresence per session would
    # stack retry threads and sockets; instead the first session's instance is
    # kept for the whole process (its 10s replay loop reconnects by itself
    # after a close()).
    global _rpc
    if _rpc is None:
        _rpc = DiscordPresence(cfg.get("discord_client_id"),
                               enabled=cfg.get("discord_rpc_enabled", True))
    # The app's Discord art-asset image key (config), used as the big presence
    # icon. Empty string -> no icon.
    _discord_img = cfg.get("discord_large_image") or None
    _discord_img_text = cfg.get("discord_large_text") or "Cubeon"

    # Announce "in the launcher" off the UI thread: connecting to Discord's IPC
    # socket is a network-ish call, and we never want a missing/slow Discord to
    # delay the window appearing. All later updates are tiny and fast.
    threading.Thread(
        target=_rpc.set_activity,
        kwargs={
            "details": "Cubeon",
            "state": "In the launcher",
            "large_image": _discord_img,
            "large_text": _discord_img_text,
        },
        daemon=True,
    ).start()

    # --- Ensure the stable machine identity exists (auth_key.json) ---
    # A permanent random v4 UUID + owning secret, created once and self-healing.
    # This is what the game launches with and what the Friends/chat account is
    # anchored to, so changing the in-game username never resets player data,
    # cosmetics, or your friends list. Idempotent - a no-op once the key exists.
    core.ensure_auth_key()

    # --- Remove installs that never finished downloading (opt-out) ---------
    # A half-downloaded version cannot launch, and would otherwise sit in the
    # Play list forever wearing "(incomplete)". install_version() deletes its
    # own partial files when an install FAILS, so what is left is what a hard
    # kill (crash, power cut, full disk) stranded. Runs BEFORE the scan below
    # so the user never sees it, and only touches the narrow states that mean
    # "the bytes never arrived" - see cubeon/versions.py for the exclusions
    # and the mtime grace period that protects a download in flight. Turn it
    # off in Settings > Game versions (auto_delete_incomplete).
    if bool(cfg.get("auto_delete_incomplete", True)):
        try:
            _cleaned_up = core.cleanup_unfinished_installs()
            if _cleaned_up:
                logging.getLogger(__name__).info(
                    "startup: removed %d unfinished install(s): %s",
                    len(_cleaned_up),
                    ", ".join(c["id"] for c in _cleaned_up))
        except Exception:
            logging.getLogger(__name__).warning(
                "startup: unfinished-install cleanup failed", exc_info=True)

    # --- Get the list of already installed Minecraft versions ---
    _initial_versions = core.get_installed_versions()  # List of version info dicts

    # --- State dictionary to hold dynamic data that changes during the app's lifetime ---
    # We use this to track the selected version, installed versions, running processes, etc.
    state = {
        "selected_version": cfg.get("last_version"),        # The version currently selected in the dropdown (raw launch id)
        "selected_mc_version": core.extract_mc_version(cfg.get("last_version")) if cfg.get("last_version") else None,
        # ^ clean numeric version (e.g. "1.20.1") derived from the launch id - this is the
        # key used for mods profiles (get_profile_dir/list_mods/sync_mods_to_game). Kept
        # separate from "selected_version" because the raw id can be loader-tagged for
        # TLauncher or manually-installed versions (e.g. "1.20.1-forge-47.2.0"), and using
        # that raw id as a profile key pointed the Mods tab and the mods-sync-at-launch
        # step at a different, always-empty folder - see on_version_selected().
        "installed": {v["id"] for v in _initial_versions},  # Set of installed version IDs for quick lookup
        "installed_meta": {v["id"]: v for v in _initial_versions},  # Full info per installed version
        "process": None,                                     # Will hold the subprocess when game is running
        "mod_loader": "fabric",  # fabric | quilt | forge | neoforge - which mod loader is selected
        "running_version": None,  # launch id currently running, or None - guards instance delete
        "installing_version": None,  # launch id with a cancellable install in flight, or None
    }

    # -----------------------------------------------------------------
    # Shared small components - pixel_divider() and section_label() now live
    # in cubeon/theme.py next to the tokens they're built from, since the tab
    # modules take them as arguments and they were pure functions of the
    # palette anyway. Bound to locals here so the call sites below and the
    # `section_label=`/`pixel_divider=` arguments passed to the tab builders
    # keep working unchanged.
    # -----------------------------------------------------------------
    pixel_divider = theme.pixel_divider
    section_label = theme.section_label

    # -----------------------------------------------------------------
    # STATUS INDICATOR (headless)
    # There is deliberately no top bar and no visible "READY" chip under the
    # brand - both communicated almost nothing per pixel. The status widgets
    # still exist so set_status() keeps working everywhere (and any future
    # surface can mount them); they're just not displayed in the sidebar.
    # -----------------------------------------------------------------

    # -----------------------------------------------------------------
    # TOP NAVIGATION - the icon bar across the top (Play, Mods, Modpack,
    # Cosmetics, Servers), with Account and Settings docked on the right.
    # Replaces the old left sidebar: the content surface now spans the
    # whole window under one bar, matching the Cubeon layout mockup.
    # -----------------------------------------------------------------

    # A small colored dot that changes color to show status (ready, busy, error)
    status_dot = ft.Container(width=7, height=7, bgcolor=ACCENT, border_radius=RADIUS)
    status_text = ft.Text("READY", size=11, color=TEXT_DIM, font_family=FONT_MONO)

    # Flat nav items: (key, icon, label). The "profile" tab is the COSMETICS
    # view (skins, capes, hats) - the identity card moved behind the Account
    # icon on the right. The server keys share one top-bar icon and switch
    # between Console/Plugins/Settings through the chip row under the bar.
    top_nav_items = [
        ("play", ft.Icons.PLAY_ARROW_ROUNDED, "Play"),
        ("mods", ft.Icons.EXTENSION_ROUNDED, "Mods"),
        ("modpacks", ft.Icons.INVENTORY_2_ROUNDED, "Modpacks"),
        ("profile", ft.Icons.CHECKROOM_ROUNDED, "Cosmetics"),
        ("server", ft.Icons.DNS_ROUNDED, "Servers"),
        ("stats", ft.Icons.QUERY_STATS_ROUNDED, "Stats"),
    ]
    # The Chat tab only exists in builds that ship the social layer; a public
    # no-Friends build stays a plain launcher with no dead nav entry.
    if friends_enabled():
        top_nav_items.insert(3, ("chat", ft.Icons.CHAT_BUBBLE_ROUNDED, "Chat"))
    server_group_items = [
        ("server_console", ft.Icons.TERMINAL_ROUNDED, "Console"),
        ("server_browse", ft.Icons.TRAVEL_EXPLORE_ROUNDED, "Browse"),
        ("server_plugins", ft.Icons.EXTENSION_ROUNDED, "Plugins"),
        ("server_settings", ft.Icons.TUNE_ROUNDED, "Settings"),
    ]
    SERVER_TOP_KEY = "server"

    active_tab = {"value": "play"}  # We use a dict so we can mutate it inside nested functions
    nav_buttons = {}  # Will hold references to each navigation button container

    # The tab-switch choreography (2026-10-16): ONE curve and duration for the
    # underline growth, the icon lift and the tint fade, so the switch reads as
    # a single gesture rather than three separate jumps. See
    # build_top_nav_button (the resting values) and _style_nav_button (the
    # active ones).
    NAV_ANIM = ft.Animation(150, ft.AnimationCurve.EASE_OUT_CUBIC)
    # The CONTENT swap stays INSTANT. A 170ms cross-fade was tried here
    # (2026-10-16) and the verdict was immediate - "stucky buggy and not
    # smooth" - which is the SECOND time a faded cross-fade has been rejected
    # (see switch_tab's own note about a 220ms fade reading as "sloppy
    # rendering"). Two full tab trees animate at once and a live tab (Play's
    # ambient particles, the console) keeps repainting underneath it. What
    # people actually asked for is the top bar's motion, and that is where it
    # lives.
    TAB_FADE_MS = 0

    # The main content area on the right - it will be replaced when switching tabs.
    # tab_switcher (a single AnimatedSwitcher created once) is now a plain
    # pass-through: duration=0 makes the swap instant. It is kept as a
    # switcher (not a plain Container) only so the structure - and the
    # switch_tab code that assigns .content - stays unchanged.
    tab_switcher = ft.AnimatedSwitcher(
        content=ft.Container(expand=True),
        transition=ft.AnimatedSwitcherTransition.FADE,
        duration=TAB_FADE_MS,
        reverse_duration=TAB_FADE_MS,
    )
    content_area = ft.Container(content=tab_switcher, expand=True)

    def _style_nav_button(btn, is_active):
        """Restyles a nav button for the active/inactive state.

        Two shapes live in nav_buttons: top-bar ICON buttons (marker
        `cubeon_top_icon`: an icon over an underline bar) and the server
        sub-tab CHIPS (icon + label rows, the old sidebar style). The marker
        attribute is set at build time; Flet controls are plain Python
        objects, so a private attribute survives page.update() just fine.
        """
        if getattr(btn, "cubeon_top_icon", False):
            btn.data = is_active
            # A faint green wash behind the icon plus the underline - the
            # active tab reads at a glance without a bright slab. The width
            # (not just the colour) changes, which is what lets the bar GROW
            # out from under the icon instead of blinking: animate_size on the
            # underline, animate_scale on the icon, and the tint fades through
            # the button's own `animate`.
            btn.bgcolor = ACCENT_TINT if is_active else "transparent"
            icon_ctrl = btn.content.controls[0]
            underline = btn.content.controls[1]
            icon_ctrl.color = ACCENT if is_active else TEXT_DIM
            icon_ctrl.scale = 1.0 if is_active else 0.94
            underline.bgcolor = ACCENT if is_active else "transparent"
            # Grow/shrink from the middle. The width stays 24 (see
            # build_top_nav_button): a scale is a transform, so nothing
            # reflows and the nav row never shifts under the cursor.
            underline.scale = ft.Scale(scale_x=1 if is_active else 0,
                                       scale_y=1,
                                       alignment=ft.Alignment.CENTER)
            return
        # The active state is a *quiet* one: a faint green wash and a small
        # accent bar on the left edge - not a solid green slab.
        btn.bgcolor = ACCENT_TINT if is_active else "transparent"
        btn.data = is_active  # remembered so the hover handler knows the resting state
        row = btn.content
        row.controls[0].color = ACCENT if is_active else TEXT_DIM      # icon
        row.controls[1].color = TEXT if is_active else TEXT_DIM        # label
        row.controls[2].bgcolor = ACCENT if is_active else "transparent"  # indicator bar

    def _on_nav_hover(e):
        """Affordance: an inactive nav item lifts to a faint wash so the bar
        feels responsive instead of dead. The active item is left alone - it
        already reads as selected and shouldn't flicker under the cursor."""
        btn = e.control
        if btn.data:  # active tab - leave it as-is
            return
        hovering = e.data == "true"
        btn.bgcolor = ROW_HOVER if hovering else "transparent"
        btn.content.controls[0].color = TEXT if hovering else TEXT_DIM
        if not getattr(btn, "cubeon_top_icon", False):
            btn.content.controls[1].color = TEXT if hovering else TEXT_DIM
        btn.update()

    def build_top_nav_button(key, icon, label):
        """An icon-only top-bar button: the icon, and the small green
        underline that marks the active tab (the mockup's active affordance -
        a bar under the icon, not a filled slab).

        ALL THREE parts of the affordance animate rather than snapping
        (2026-10-16): the underline GROWS out from under the icon (its width
        changes, so `animate_size` has something to interpolate), the icon
        itself lifts a hair (`animate_scale`), and the tint behind the button
        fades (`animate`). One curve and one duration for all three, so the
        switch reads as a single gesture instead of three separate jumps."""
        is_active = key == active_tab["value"]
        btn = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=21, color=ACCENT if is_active else TEXT_DIM,
                            scale=1.0 if is_active else 0.94,
                            animate_scale=NAV_ANIM),
                    # The underline. ITS WIDTH IS ALWAYS 24: the bar grows via
                    # `scale_x` (0 -> 1, anchored at the icon's centre), which
                    # is a paint-only transform. Animating the real width was
                    # the first attempt and it was visibly janky - the column
                    # sizes to max(icon, underline), so a width that changes
                    # 0<->24 resized every button and shifted the whole centred
                    # nav row by a pixel or two every frame.
                    ft.Container(width=24, height=3, border_radius=RADIUS,
                                 bgcolor=ACCENT if is_active else "transparent",
                                 scale=ft.Scale(scale_x=1 if is_active else 0,
                                                scale_y=1,
                                                alignment=ft.Alignment.CENTER),
                                 animate_scale=NAV_ANIM),
                ],
                spacing=5,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            bgcolor=ACCENT_TINT if is_active else "transparent",
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=13, vertical=7),
            data=is_active,
            on_click=lambda e, k=key: switch_tab(k),
            on_hover=_on_nav_hover,
            animate=NAV_ANIM,
            # EXACTLY the label, no "· Ctrl+3" suffix: an icon-only nav button
            # has no visible Text, so every test/tool that navigates by name
            # reads THIS string as the button's label (tools/_fuzz_common.py
            # ctrl_text + goto, tools/ux_capture.py). Hints live in F1's list.
            tooltip=label,
        )
        btn.cubeon_top_icon = True
        nav_buttons[key] = btn
        return btn

    def build_nav_button(key, icon, label, *, icon_size=18, indent=0):
        """A labeled chip button - used for the server sub-tabs (Console /
        Plugins / Settings) shown under the bar while a server tab is active.
        Same visual language the old sidebar rows used."""
        is_active = key == active_tab["value"]
        btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=icon_size, color=ACCENT if is_active else TEXT_DIM),
                    ft.Text(label, size=13.5, weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_500,
                            color=TEXT if is_active else TEXT_DIM, expand=True),
                    # Small accent indicator on the leading edge - the whole
                    # active affordance is this bar plus the tint behind it.
                    ft.Container(width=3, height=16, bgcolor=ACCENT if is_active else "transparent",
                                 border_radius=RADIUS),
                ],
                spacing=12,
            ),
            bgcolor=ACCENT_TINT if is_active else "transparent",
            border_radius=RADIUS,
            padding=ft.padding.Padding.only(left=12 + indent, right=10, top=10, bottom=10),
            data=is_active,
            on_click=lambda e, k=key: switch_tab(k),
            on_hover=_on_nav_hover,
            animate=150,
        )
        nav_buttons[key] = btn
        return btn

    # The server sub-tab chips. switch_tab shows/hides the whole row
    # depending on whether a server tab is active.
    server_subnav = ft.Row(
        [build_nav_button(key, icon, label) for key, icon, label in server_group_items],
        spacing=8,
    )
    subnav_bar = ft.Container(
        content=ft.Row([ft.Container(width=16), server_subnav], spacing=0),
        visible=False,
        padding=ft.padding.Padding.only(left=12, top=10, bottom=2),
    )

    # -----------------------------------------------------------------
    # SEASONAL LAYER - the runtime half (see cubeon/seasonal.py).
    #
    # The PALETTE was decided while `cubeon` was being imported (the hook at the
    # bottom of cubeon/__init__.py), and `cubeon_seasonal.current()` returns
    # that very decision - cached, not re-detected - so the badge can never
    # advertise a season the window isn't actually wearing.
    #
    # The badge and the companion are built HERE, before the top bar, because
    # the bar mounts them. Their click handlers are late-bound lambdas (the
    # account button does the same): _open_seasonal_settings and _on_pet_clicked
    # are defined further down, next to the Settings tab they belong to.
    # -----------------------------------------------------------------
    season_info = cubeon_seasonal.current()
    # Built but NOT mounted in the top bar (user request: the chip cluttered
    # the row next to Account). It stays alive so _season_controls_sync can
    # keep it correct; the Seasonal pane in Settings is the way in.
    season_badge = build_season_badge(
        season_info, on_click=lambda e: _open_seasonal_settings())
    # The companion lives on a perch lane (a short clipped strip) so it can
    # WANDER - walk, pause, turn around - instead of hopping in place.
    # season_perch is what the bar mounts; season_pet_ctrl is the sprite
    # inside it (kept named for the click bounce and the visibility toggle);
    # season_pet is the state dict the animator's wander machine drives.
    season_perch, season_pet = build_season_perch(
        season_info, on_click=lambda e: _on_pet_clicked())
    season_pet_ctrl = season_pet["ctrl"]
    # Decoration must be off when the layer is off: "Seasonal look: off" plus a
    # seasonal fox in the bar would read as a bug.
    season_perch.visible = bool(cfg.get("season_pet", False)) and season_info.seasonal

    # -----------------------------------------------------------------
    # CUSTOM WINDOW FRAME (Windows prototype) - the title-bar buttons
    # -----------------------------------------------------------------
    # A frameless window has no OS buttons, so the app draws them. They are only
    # built when the frame is actually custom (Windows + the flag); otherwise
    # `chrome_row` is an empty placeholder and the native buttons do the job.
    # The widgets live in ui/window_chrome.py so the smoke test can build and
    # inspect them without a window (this branch never runs on the Linux dev box
    # or in CI).
    _chrome_state = {"maximized": False}
    # Fullscreen (F11) is a SEPARATE claim from maximized: fullscreen hides the
    # taskbar/panels and the frame, maximize keeps the frame. Both are tracked
    # because the resize hot-zones and the geometry save must treat them alike
    # (a fullscreen window has nothing to resize, and its screen-sized rect must
    # never be saved as the window's restored geometry).
    _fullscreen = {"active": False}

    # The flet client is a separate process, so the real window state has to
    # be read from the OS (Windows only - that is where the custom frame
    # lives). Cached pid; 0 means "look the window up by title".
    _client_pid = {"pid": None}

    def _native_maximized():
        """True/False from the real window, or None when it cannot be read.

        The Python-side `page.window.maximized` is the value we last WROTE,
        not what the window manager did. Trusting it is how "it says the
        window is maximized but it isn't - and I can't resize" happened
        (2026-10-23): the WM ignored the hidden-window maximize, the glyph and
        the resize hot-zones believed the write, and the first click only
        cleared the lie. See winchrome.native_maximized.
        """
        if sys.platform != "win32":
            return None
        try:
            if _client_pid["pid"] is None:
                pids = _live_flet_clients(resolve_assets_dir())
                _client_pid["pid"] = int(pids[0]) if pids else 0
            return winchrome.native_maximized(_client_pid["pid"] or None)
        except Exception:
            return None

    def _is_chrome_maximized():
        native = _native_maximized()
        return bool(_chrome_state["maximized"] if native is None else native)

    def _force_window_bool(name, value):
        """Write a window bool so the value ALWAYS reaches the client.

        Two flet facts make the naive write wrong (both verified in this build's
        source, not guessed):

        1. `flet/controls/value_types.py::Prop.__set__` DROPS a write that
           equals the value already stored - so `window.minimized = True` a
           second time sends nothing and the button goes dead.
        2. On the patch pass flet emits ONE "replace" per dirty field carrying
           the field's CURRENT value, so an intermediate write is never on the
           wire - which is exactly what lets the opposite-first write below
           double as the "always send" trick: the client only ever sees the
           target value.

        It is also why a bare `maximized = False` is not enough: `False` is the
        declared default, so on a window maximized by the drag area's
        double-click (which never touches the Python property) the write is
        dropped and Restore would do nothing.
        """
        setattr(page.window, name, not bool(value))
        setattr(page.window, name, bool(value))
        page.window.update()

    def _chrome_minimize(e=None):
        try:
            _force_window_bool("minimized", True)
        except Exception:
            pass  # a title-bar button must never take the UI down

    def _chrome_maximize(e=None):
        # Toggle the REAL state, not our last write. If the WM ignored an
        # earlier maximize (hidden-window restore), the button used to spend
        # its first click clearing that lie - the 2026-10-23 "click maximize
        # twice" report.
        target = not _is_chrome_maximized()
        try:
            _force_window_bool("maximized", target)
        except Exception:
            pass
        # Optimistic: the native MAXIMIZE/UNMAXIMIZE event corrects this a
        # moment later (see _on_window_event), so the glyph never lags a click.
        _set_chrome_maximized(target)

    def _chrome_close(e=None):
        # Window.close() is a COROUTINE on this build: schedule it with
        # page.run_task and never await it here. This handler runs on flet's
        # event loop, and a wedged client never answers - blocking here is how
        # the launcher used to end up alive with no window.
        try:
            page.run_task(page.window.close)
        except Exception:
            pass

    def _sync_resize_edges():
        """Show the resize hot-zones only while there is something to resize.

        A maximized OR fullscreen window cannot be resized, and a hot-zone left
        enabled along every edge swallows clicks meant for the UI underneath.
        One place derives that from both claims so a fullscreen toggle can never
        leave the handles on screen.
        """
        set_resize_edges_visible(
            _resize_edges,
            not (_is_chrome_maximized() or _fullscreen["active"]))
        for _e in _resize_edges:
            thread_safe_ui.refresh(_e)

    def _set_fullscreen(active):
        """Enter/leave native fullscreen (F11, Escape, or the WM).

        Two flet facts shape this, both already load-bearing elsewhere:

        * The write goes through `_force_window_bool`, NOT a bare assignment:
          `full_screen=False` is the declared default, and flet's Prop drops any
          write equal to the default - so a bare `... = False` would leave the
          window STUCK in fullscreen (same trap as `visible`/`maximized`, see
          _force_window_bool).
        * The resize hot-zones are parked while fullscreen, and geometry saving
          is suspended (see _save_geometry_now) - otherwise leaving fullscreen
          would restore a window whose "remembered" size is the whole screen.

        Best-effort by construction: a window-less harness or a client that
        ignores the flag must not raise out of a key handler.
        """
        active = bool(active)
        if _fullscreen["active"] == active:
            return
        try:
            _force_window_bool("full_screen", active)
        except Exception:
            return  # no window to toggle: leave our flag untouched
        _adopt_fullscreen_state(active)

    def _toggle_fullscreen():
        _set_fullscreen(not _fullscreen["active"])

    def _adopt_fullscreen_state(active):
        """Record a fullscreen state and re-sync what depends on it.

        Called both after our own write and from the native
        enter-full-screen / leave-full-screen events, so a change we did not
        make (the window manager, or a client-side Escape) can't leave the
        resize handles and the geometry save believing the wrong thing.
        """
        _fullscreen["active"] = bool(active)
        try:
            _sync_resize_edges()
        except Exception:
            pass

    def _set_chrome_maximized(maximized):
        """Swap the maximize glyph and park the resize hot-zones.

        Both matter: a maximized window cannot be resized, and hot-zones left
        enabled along every edge would swallow clicks meant for the UI.
        """
        _chrome_state["maximized"] = bool(maximized)
        if not _chrome_ctl:
            return
        try:
            set_maximized_glyph(_chrome_ctl, maximized)
            thread_safe_ui.refresh(_chrome_ctl["maximize"])
        except Exception:
            pass
        try:
            _sync_resize_edges()
        except Exception:
            pass

    def _on_resize_edge(edge):
        """Begin a native resize from a hot-zone, handed to the OS window loop.

        `Window.start_resizing()` is a coroutine on this build, so it is
        SCHEDULED and never awaited: this runs off a pan-start on flet's event
        loop and the client owns the mouse for the duration of the drag.
        """
        try:
            page.run_task(page.window.start_resizing, edge)
        except Exception:
            pass  # an un-resizable window is better than a broken one

    if _custom_chrome:
        try:
            _chrome_ctl = build_window_controls(
                on_minimize=_chrome_minimize,
                on_maximize=_chrome_maximize,
                on_close=_chrome_close,
                TEXT_DIM=TEXT_DIM, TEXT=TEXT, SURFACE_HI=SURFACE_HI,
                DANGER=DANGER, ON_DANGER=ON_DANGER,
            )
            chrome_row = _chrome_ctl["row"]
            # The window may ALREADY be maximized from the saved geometry - and
            # that maximize happens during _apply_real_geometry(), long before
            # page.window.on_event is wired (see the end of main), so no event
            # will ever tell us. Adopt the state we know instead of assuming
            # False: assuming wrong leaves the maximize button DEAD, because
            # flet drops a write equal to the state the client already has.
            _chrome_state["maximized"] = bool(
                getattr(page.window, "maximized", False))
            if _chrome_state["maximized"]:
                set_maximized_glyph(_chrome_ctl, True)
        except Exception:
            # Building our buttons failed. Hand the OS frame BACK rather than
            # strand the user in a title-bar-less window with no way to close
            # it - `frameless = False` is a change, so it does reach the client.
            _custom_chrome = False
            try:
                page.window.frameless = False
            except Exception:
                pass
            chrome_row = ft.Row([], spacing=0)
    else:
        # None (not an empty Row): an extra child would eat one of the row's 8px
        # gaps, so the native frame's layout stays byte-identical to before.
        chrome_row = None

    def _build_top_bar():
        """The bar itself: brand mark on the left, the five nav icons dead
        center, Account and Settings on the right. Account opens the identity
        card (avatar, username, profile picture) in a dialog - the click
        target is filled in later, once the card is built, via the
        _account_open holder defined just below."""
        nav_row = ft.Row(
            [build_top_nav_button(key, icon, label)
             for key, icon, label in top_nav_items],
            spacing=6,
        )
        account_btn = ft.IconButton(
            icon=ft.Icons.PERSON_ROUNDED, icon_size=22, icon_color=TEXT_DIM,
            tooltip="Account",
            # Late-bound on purpose: _open_account_panel is defined further
            # down (after its controls), and the click resolves it then.
            on_click=lambda e: _open_account_panel(),
            style=ft.ButtonStyle(color={ft.ControlState.HOVERED: TEXT}),
        )
        settings_btn = ft.IconButton(
            icon=ft.Icons.TUNE_ROUNDED, icon_size=22, icon_color=TEXT_DIM,
            tooltip="Settings",
            on_click=lambda e: switch_tab("settings"),
            style=ft.ButtonStyle(color={ft.ControlState.HOVERED: TEXT}),
        )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=8),
                    sidebar_brand,
                    # The companion's perch lane sits with the wordmark, like a
                    # mascot strolling a shop sign - not in the right-hand
                    # cluster where the account/settings icons live.
                    season_perch,
                    ft.Row([ft.Container(expand=True), nav_row,
                            ft.Container(expand=True)], expand=True),
                    account_btn,
                    settings_btn,
                    # Custom window frame (Windows): our own min/max/close,
                    # because a frameless window has no OS buttons. Absent
                    # entirely when the native frame is in charge.
                    *([chrome_row] if chrome_row is not None else []),
                    ft.Container(width=10),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.Padding.only(left=14, right=6, top=8, bottom=2),
        )

    # "Signed in as" widgets - pulled out as named variables so the
    # username field's on_change handler can update them live, since offline
    # accounts are keyed entirely off the username (new name = new account).
    # They are mounted in the top bar's brand mark (username) and shown in
    # the Account dialog (avatar).
    #
    # Avatar source resolution: an uploaded profile picture wins if present,
    # otherwise falls back to the skin-face render - so the account view
    # always shows *something* meaningful even before anyone uploads
    # their own picture.
    def _current_avatar_src(username: str) -> str:
        pfp_path = core.get_profile_picture_path(cfg)
        if pfp_path:
            try:
                with open(pfp_path, "rb") as f:
                    return f.read()
            except OSError:
                pass
        return core.get_skin_face_url(username)

    sidebar_avatar = ft.CircleAvatar(
        foreground_image_src=_current_avatar_src(cfg["username"]),
        radius=14,
        bgcolor=SURFACE_HI,
    )
    sidebar_username_text = ft.Text(
        cfg["username"], size=14, weight=ft.FontWeight.W_600,
        color=TEXT, font_family=FONT_MONO,
    )

    # --- Profile tab: bigger avatar, upload/remove picture, username ---

    profile_dialog_avatar = ft.CircleAvatar(
        foreground_image_src=_current_avatar_src(cfg["username"]),
        radius=48,
        bgcolor=SURFACE_HI,
    )
    # Little animated companion perched on the avatar's shoulder - pure
    # decoration, no state of its own, so it's just an Image placed via
    # Stack rather than threaded through refresh_avatars()/cfg like the
    # actual profile picture is.
    profile_parrot = ft.Image(
        src="parrot.gif", width=40, height=46, fit=ft.BoxFit.CONTAIN,
    )
    profile_avatar_with_parrot = ft.Stack(
        [
            ft.Container(content=profile_dialog_avatar, width=96, height=96),
            ft.Container(
                content=profile_parrot,
                left=62, top=-6,  # perched over the avatar's top-right edge
            ),
        ],
        width=104, height=100,
    )
    profile_dialog_username = ft.Text(
        cfg["username"], size=20, color=TEXT, font_family=FONT_DISPLAY,
    )
    profile_pfp_status = ft.Text("", size=12, color=TEXT_DIM)

    screenshot_gallery_tab, refresh_screenshot_gallery = \
        build_screenshot_gallery_tab(page)

    def refresh_avatars():
        """Called after upload/remove/username-change so the account dialog's
        avatar never falls out of sync with the current state."""
        src = _current_avatar_src(cfg["username"])
        sidebar_avatar.foreground_image_src = src
        profile_dialog_avatar.foreground_image_src = src
        sidebar_username_text.value = cfg["username"]
        profile_dialog_username.value = cfg["username"]

    def handle_pfp_files(files):
        if not files:
            return
        picked = files[0]
        profile_pfp_status.value = "Uploading..."
        profile_pfp_upload_btn.disabled = True
        profile_pfp_remove_btn.disabled = True
        page.update()

        def _work():
            # The upload runs OFF the UI thread: set_profile_picture decodes
            # and LANCZOS-resizes the chosen image, which is hundreds of ms
            # for a big photo - on the UI thread it froze typing/scrolling
            # for the whole resize.
            try:
                core.set_profile_picture(picked.path)
                cfg["profile_picture"] = "avatar.png"
                core.save_config(cfg)
                refresh_avatars()
                profile_pfp_status.value = "Profile picture updated."
            except ValueError as ve:
                profile_pfp_status.value = str(ve)
            except Exception as ex:
                profile_pfp_status.value = f"Upload failed: {ex}"
            finally:
                profile_pfp_upload_btn.disabled = False
                profile_pfp_remove_btn.disabled = False
                # Per-control diffs from this background thread - a
                # page.update() here would stomp on whatever the user is
                # doing in the foreground.
                thread_safe_ui.refresh(account_panel)
                thread_safe_ui.refresh(top_bar)

        threading.Thread(target=_work, daemon=True,
                         name="cubeon-pfp-upload").start()

    def on_pfp_picked(e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. Not type-hinted as
        # ft.FilePickerResultEvent - that class doesn't exist on every
        # Flet build (e.g. it's gone in 0.86.x, which is otherwise the
        # pinned/tested version), and a hard annotation on it would crash
        # this function's definition at import time on those builds. See
        # run_file_picker()'s docstring in cubeon/config.py for the same
        # version-spanning reasoning.
        handle_pfp_files(e.files)

    pfp_file_picker = ft.FilePicker()
    pfp_file_picker.on_result = on_pfp_picked

    # Same version-spanning registration dance used for the skin uploader's
    # FilePicker in skin_tab.py - newer Flet self-registers Services,
    # older Flet needs the explicit page.overlay append.
    _pfp_registered = False
    _services_list = getattr(page, "_services", None)
    _already_registered = (
        _services_list is not None
        and hasattr(_services_list, "_services")
        and pfp_file_picker in _services_list._services
    )
    _register_fn = getattr(page, "register_service", None)
    if _already_registered:
        _pfp_registered = True
    elif callable(_register_fn):
        try:
            _register_fn(pfp_file_picker)
            _pfp_registered = True
        except Exception:
            _pfp_registered = False
    if not _pfp_registered:
        try:
            if pfp_file_picker not in page.overlay:
                page.overlay.append(pfp_file_picker)
        except Exception:
            pass

    def open_pfp_picker(e=None):
        run_file_picker(
            page, pfp_file_picker,
            on_files=handle_pfp_files,
            dialog_title="Choose a profile picture",
            allow_multiple=False,
            allowed_extensions=["png", "jpg", "jpeg", "webp", "gif", "bmp"],
        )

    # Skin FilePicker - created and registered once here (same pattern as
    # pfp_file_picker above), then passed into build_skin_section() on every
    # rebuild instead of letting that function create its own each time.
    skin_file_picker = ft.FilePicker()

    _skin_registered = False
    _skin_services_list = getattr(page, "_services", None)
    _skin_already_registered = (
        _skin_services_list is not None
        and hasattr(_skin_services_list, "_services")
        and skin_file_picker in _skin_services_list._services
    )
    if _skin_already_registered:
        _skin_registered = True
    elif callable(_register_fn):
        try:
            _register_fn(skin_file_picker)
            _skin_registered = True
        except Exception:
            _skin_registered = False
    if not _skin_registered:
        try:
            if skin_file_picker not in page.overlay:
                page.overlay.append(skin_file_picker)
        except Exception:
            pass

    # Cape FilePicker - same create-and-register-once pattern as the skin
    # picker above. The skin section rebuilds on every Profile open, so the
    # cape uploader (like the skin one) must reuse a single shared, already-
    # registered picker rather than making a fresh one each rebuild (only the
    # first registration ever receives results - see build_skin_section()).
    cape_file_picker = ft.FilePicker()

    _cape_registered = False
    _cape_services_list = getattr(page, "_services", None)
    _cape_already_registered = (
        _cape_services_list is not None
        and hasattr(_cape_services_list, "_services")
        and cape_file_picker in _cape_services_list._services
    )
    if _cape_already_registered:
        _cape_registered = True
    elif callable(_register_fn):
        try:
            _register_fn(cape_file_picker)
            _cape_registered = True
        except Exception:
            _cape_registered = False
    if not _cape_registered:
        try:
            if cape_file_picker not in page.overlay:
                page.overlay.append(cape_file_picker)
        except Exception:
            pass

    def on_remove_pfp(e=None):
        if not cfg.get("profile_picture"):
            return  # nothing to remove - don't flash a pointless status
        try:
            core.clear_profile_picture(cfg)
        except Exception:
            logging.getLogger(__name__).warning("pfp removal failed", exc_info=True)
            profile_pfp_status.value = "Couldn't remove the profile picture."
            page.update()
            return
        refresh_avatars()
        profile_pfp_status.value = "Profile picture removed."
        page.update()

    # --- Username field (Profile tab's own copy) ---
    # Mirrors the Play tab's username field - offline accounts are keyed
    # entirely off the username, so editing it here changes the signed-in
    # account exactly the same way editing it on Play does. Both fields
    # stay in sync via the SHARED username publish machinery below (one
    # debounce slot, newest edit wins - see on_name_keystroke).

    profile_username_field = ft.TextField(
        value=cfg["username"],
        label="Username",
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM),
        text_style=ft.TextStyle(font_family=FONT_MONO),
        bgcolor=SURFACE_HI,
        border_radius=RADIUS,
        height=52,
        # Pencil affordance inside the field (right edge) - the field is
        # directly editable, the icon just signals "this is editable" the
        # way the target layout shows it.
        suffix_icon=ft.Icons.EDIT_ROUNDED,
    )

    # --- SHARED username publish machinery (Account + Play fields) ---
    # Both fields edit the same account name, so they share ONE debounce
    # slot. This fixes two real bugs the independent handlers had:
    #   1. the Account field ran the full pipeline (CSL sync x2, config
    #      save, avatar refresh, a 3s contest-check THREAD) on EVERY
    #      keystroke - the Play field was debounced, this one wasn't, so
    #      typing in the account panel read as laggy/chunky;
    #   2. two independent pending timers could race: an older pending name
    #      from one field could overwrite a newer one just published by the
    #      other. One slot means the newest edit always wins.
    _name_state = {"timer": None, "pending": None, "field": None, "generation": 0}
    _name_lock = threading.RLock()
    _name_sync_lock = threading.Lock()

    def _name_validate_into(field):
        name = field.value.strip()
        ok, err = core.validate_username(name)
        field.error_text = None if ok else err
        return ok, name

    def _publish_username(generation=None):
        with _name_lock:
            if generation is None:
                generation = _name_state["generation"]
            if generation != _name_state["generation"]:
                return
            field = _name_state.get("field")
            if field is None:
                return
            ok, name = _name_validate_into(field)
            if not ok or name == cfg.get("username"):
                thread_safe_ui.refresh(field)
                return
            cfg["username"] = name
            core.save_config(cfg)
            for other in (username_field, profile_username_field):
                if other is not field and other.value != name:
                    other.value = name
                thread_safe_ui.refresh(other)
            if friends_service is not None:
                try:
                    friends_service.reconcile_username()
                except Exception:
                    logging.getLogger(__name__).debug("username reconciliation failed", exc_info=True)
            refresh_avatars()
        with _name_sync_lock:
            with _name_lock:
                if generation != _name_state["generation"]:
                    return
                sync_cfg = dict(cfg)
            core.sync_local_skin_to_csl(sync_cfg)
            core.sync_local_cape_to_csl(sync_cfg)
            with _name_lock:
                if generation != _name_state["generation"]:
                    return
                for key in ("csl_synced_name", "csl_synced_cape_name"):
                    if key in sync_cfg:
                        cfg[key] = sync_cfg[key]
                core.save_config(cfg)

        def _warn_if_contested():
            time.sleep(3.0)
            try:
                with _name_lock:
                    if generation == _name_state["generation"] and core.name_contested():
                        set_status("Note: another Cubeon player recently used "
                                   "this name - others may see their skin on it.")
            except Exception:
                logging.getLogger(__name__).warning("background worker error", exc_info=True)
        threading.Thread(target=_warn_if_contested, daemon=True,
                         name="cubeon-name-contested-check").start()

    def _cancel_pending_name():
        with _name_lock:
            t = _name_state.get("timer")
            if t:
                t.cancel()
            _name_state["timer"] = None
            _name_state["pending"] = None
            _name_state["generation"] += 1

    def _fire_pending_name(e=None, generation=None):
        with _name_lock:
            if generation is not None and generation != _name_state["generation"]:
                return
            pub = _name_state.get("pending")
            if not pub:
                return
            generation = _name_state["generation"]
            t = _name_state.get("timer")
            if t:
                t.cancel()
            _name_state["pending"] = None
            _name_state["timer"] = None
        pub(generation)

    def on_name_keystroke(field):
        with _name_lock:
            _name_validate_into(field)
            _cancel_pending_name()
            _name_state["field"] = field
            generation = _name_state["generation"]
            t = threading.Timer(1.2, lambda: _fire_pending_name(generation=generation))
            t.daemon = True
            _name_state["timer"] = t
            _name_state["pending"] = _publish_username
            t.start()
        thread_safe_ui.refresh(field)

    profile_username_field.on_change = lambda e=None: on_name_keystroke(profile_username_field)
    profile_username_field.on_blur = _fire_pending_name

    # --- Skin section container. The section used to be rebuilt from
    # scratch on EVERY visit to the Cosmetics tab (~150 ms of control
    # construction plus a full subtree re-serialization to the client =
    # the "freeze for a moment when I open Cosmetics" bug). The rebuild
    # existed so the CustomSkinLoader-installed notice reflects whatever
    # version/mod loader is currently selected on the Play tab - so it is
    # now cached keyed on those two inputs and rebuilt only when they
    # change. The section's own handlers (upload/use/delete/refresh)
    # repaint their lists in place, so nothing on it goes stale in
    # between visits. ---

    skin_section_container = ft.Container()

    _skin_section_key = {"built": False, "version": None, "loader": None}

    def rebuild_skin_section():
        mc_version = version_dropdown.value or cfg.get("last_version")
        mc_loader = state.get("mod_loader")
        if (_skin_section_key["built"]
                and _skin_section_key["version"] == mc_version
                and _skin_section_key["loader"] == mc_loader):
            return
        _skin_section_key.update(built=True, version=mc_version,
                                 loader=mc_loader)
        skin_section_container.content = build_skin_section(
            page, cfg,
            section_label=section_label, pixel_divider=pixel_divider,
            **THEME,
            mc_version=version_dropdown.value or cfg.get("last_version"),
            mc_loader=state.get("mod_loader"),
            file_picker=skin_file_picker,
            cape_file_picker=cape_file_picker,
            screenshot_gallery=screenshot_gallery_tab,
            refresh_screenshot_gallery=refresh_screenshot_gallery,
        )

    # Profile tab content - a plain scrollable column like every other tab,
    # using the full content width instead of a fixed centered column.
    #
    # Layout: a header CARD laid out as one horizontal row -
    #   [ avatar ]  [ name + "Cubeon Profile" + username field ]  [ picture actions ]
    # then the in-game skin card below it. Left-aligned and side-by-side
    # rather than the old centered stack.
    profile_pfp_upload_btn = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.UPLOAD_ROUNDED, color=ON_ACCENT, size=16),
                ft.Text("Upload", color=ON_ACCENT, weight=ft.FontWeight.W_700, size=13),
            ],
            alignment=ft.MainAxisAlignment.CENTER, spacing=6, tight=True,
        ),
        bgcolor=ACCENT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=11, horizontal=18),
        ink=False, on_click=open_pfp_picker,
    )
    profile_pfp_remove_btn = ft.Container(
        content=ft.Text("Remove", color=DANGER, weight=ft.FontWeight.W_700, size=13),
        border=ft.border.Border.all(1, DANGER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=11, horizontal=18),
        ink=False, on_click=on_remove_pfp, alignment=ft.Alignment.CENTER,
    )

    # -----------------------------------------------------------------
    # COSMETICS TAB (the old Profile tab): skins, capes and hats. The
    # identity card (avatar, username, profile picture) moved out of here
    # into the Account dialog behind the top bar's person icon - cosmetics
    # and account are different questions and now get different surfaces.
    #
    # Like the Mods/Stats/Settings tabs, the tab is a plain padded column on
    # the page canvas - NOT wrapped in its own bordered SURFACE card. That
    # extra card was the outer half of the old "box in a box" look (every
    # stage/tile was then a second solid box); the panes now paint their own
    # translucent CARD_FILL wells, so the canvas is the only frame.
    # -----------------------------------------------------------------
    profile_tab = ft.Column(
        [skin_section_container],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    # -----------------------------------------------------------------
    # WEARING (2026-10-16 user ask: "show skin and cape" in the profile
    # sidebar). The Cosmetics tab is where you CHANGE them; this is the "what
    # am I wearing right now" answer inside the Account panel, which covers
    # the whole launcher and is therefore where people actually look.
    #
    # Same core renderers the Cosmetics tab uses, and the same rule: the PIL
    # work NEVER runs on the UI thread (it is a full body composite). The
    # previews are only re-rendered when the panel opens, which is exactly
    # when they can have gone stale.
    # -----------------------------------------------------------------
    wear_skin_img = ft.Image(src="icon.svg", width=62, height=100,
                             fit=ft.BoxFit.CONTAIN, opacity=0.35)
    wear_skin_name = ft.Text("Default skin", size=12.5, color=TEXT,
                             weight=ft.FontWeight.W_600)
    wear_skin_meta = ft.Text("Not wearing a custom skin", size=10,
                             color=TEXT_DIM)
    wear_cape_img = ft.Image(src=DEFAULT_CAPE_PREVIEW_SRC, width=62, height=100,
                             fit=ft.BoxFit.CONTAIN)
    wear_cape_name = ft.Text("Cubeon Cape", size=12.5, color=TEXT,
                             weight=ft.FontWeight.W_600)
    wear_cape_meta = ft.Text("Shared with other players", size=10,
                             color=TEXT_DIM)

    def _wearing_png(kind, filename):
        """Renders one preview and returns it as base64 - WORKER THREAD ONLY.

        Deliberately mirrors ui/skin_tab.py: src must be base64 bytes, because
        ft.Image.src resolves a relative string against assets_dir and these
        files live under ~/.cubeon_launcher, nowhere near the app's assets.
        """
        if kind == "skin":
            out_path = os.path.join(core.SKINS_DIR, "_account_panel_skin.png")
            core.render_local_skin_preview(filename, out_path, scale=6)
        else:
            out_path = os.path.join(core.CAPES_DIR, "_account_panel_cape.png")
            core.render_cape_preview(filename, out_path, scale=6)
        with open(out_path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")

    def refresh_wearing():
        """Repaint the two previews from the CURRENT config. Called when the
        Account panel opens, so a change made on the Cosmetics tab is already
        there by the time the panel finishes sliding in."""
        skin_fn = cfg.get("active_skin")
        cape_fn = cfg.get("active_cape")

        # Captions and the no-custom-fallbacks are decided synchronously (no
        # PIL), so the panel is never briefly wrong - only the images are late.
        wear_skin_name.value = "Custom skin" if skin_fn else "Default skin"
        wear_skin_meta.value = ("In use in-game" if skin_fn
                                else "Not wearing a custom skin")
        if not skin_fn:
            wear_skin_img.src = "icon.svg"
            wear_skin_img.opacity = 0.35
        wear_cape_name.value = "Custom cape" if cape_fn else "Cubeon Cape"
        wear_cape_meta.value = ("In use in-game" if cape_fn
                                else "Shared with other players")
        if not cape_fn:
            wear_cape_img.src = DEFAULT_CAPE_PREVIEW_SRC

        def _work():
            try:
                updates = []
                if skin_fn and os.path.exists(core.get_custom_skin_path(skin_fn)):
                    updates.append((wear_skin_img, _wearing_png("skin", skin_fn), 1))
                if cape_fn and os.path.exists(core.get_custom_cape_path(cape_fn)):
                    updates.append((wear_cape_img, _wearing_png("cape", cape_fn), None))
                for control, src, opacity in updates:
                    control.src = src
                    if opacity is not None:
                        control.opacity = opacity
                    thread_safe_ui.refresh(control)
            except Exception:
                # A missing/corrupt skin file must leave the placeholder,
                # never take the Account panel (or startup) down.
                logging.getLogger(__name__).debug(
                    "account panel wearing preview failed", exc_info=True)

        threading.Thread(target=_work, daemon=True,
                         name="ux-wearing-preview").start()

    # -----------------------------------------------------------------
    # ACCOUNT PANEL — slides in from the right edge over a dimmed scrim.
    #
    # Flet 0.86 has no Drawer control, so it is two overlay Containers:
    #   account_panel  animates `right` between -ACCOUNT_PANEL_W (parked
    #                  off-screen) and 0 (open)
    #   account_scrim  full-window dim that fades in/out and eats clicks
    #
    #   Open:  _open_account_panel()   (wired to the top bar's person icon)
    #   Close: _close_account_panel()  (scrim click and the ✕ button)
    #
    # Close detail: the scrim fades out (200ms) and is hidden by a timer
    # just after the fade ends. Hiding it instantly reads as a flicker;
    # leaving it visible at opacity 0 would keep it swallowing every click
    # on the launcher - so the timer matters. Its update goes through
    # thread_safe_ui because it fires on a timer thread.
    # -----------------------------------------------------------------
    ACCOUNT_PANEL_W = 390
    # The open/close choreography. ONE duration for the slide and the stretch:
    # two different durations end at visibly different times, which reads as
    # two things happening instead of one sheet being pulled out.
    ACCOUNT_ANIM_MS = 260
    # The resting squash. The panel is MOUNTED at this scale (see
    # account_panel's `scale=`), not squashed when it opens: Flet animates from
    # the value the client already holds, so setting the start value at open
    # time needs a second flush on a timer - the first attempt did exactly
    # that, and the extra frame was part of the "stucky" complaint.
    ACCOUNT_PANEL_SQUASH = 0.04

    def _close_account_panel(e=None):
        account_panel.right = -ACCOUNT_PANEL_W
        # Rolls back up on the way out, mirroring the open, and leaves the
        # panel in the exact state it is mounted in so the next open animates.
        account_panel.scale = ft.Scale(scale_x=1, scale_y=ACCOUNT_PANEL_SQUASH,
                                       alignment=ft.Alignment.TOP_RIGHT)
        account_scrim.opacity = 0

        def _retire_scrim():
            # BUG this fixes: this used to call final_update(page), which only
            # repaints when a THROTTLED update is pending - here nothing is,
            # so the visible=False below never reached the client. The scrim
            # (a full-window click-catcher) then stayed mounted at opacity 0
            # forever and swallowed every click on the launcher.
            #
            # Guard: if the panel was REOPENED inside the 0.25s window, the
            # scrim is legitimately visible again - hiding it now would leave
            # an open panel with no dim and no click-catcher.
            if account_panel.right != -ACCOUNT_PANEL_W:
                return
            try:
                account_scrim.visible = False
                thread_safe_ui.refresh(account_scrim)
            except Exception:
                pass  # a late scrim hide must never surface as an error

        threading.Timer(0.25, _retire_scrim).start()
        # Per-control diff, NOT page.update(): a whole-page update re-syncs
        # every control in the tree (all tabs, the console, everything) -
        # visually a full-app reload and the direct cause of the jank when
        # toggling the panel. Diffing just these two overlays paints the
        # slide/fade animation alone.
        thread_safe_ui.refresh(account_scrim)
        thread_safe_ui.refresh(account_panel)

    account_scrim = ft.Container(
        bgcolor=ft.Colors.with_opacity(0.55, "#000000"),
        left=0, top=0, right=0, bottom=0,
        opacity=0,
        visible=False,
        ink=False,
        on_click=_close_account_panel,
        animate_opacity=ft.Animation(200),
    )

    account_panel = ft.Container(
        bgcolor=SURFACE,
        width=ACCOUNT_PANEL_W,
        top=0,
        bottom=0,
        right=-ACCOUNT_PANEL_W,
        animate_position=ft.Animation(ACCOUNT_ANIM_MS, ft.AnimationCurve.EASE_OUT_CUBIC),
        # The "sheet of paper" half of the animation (2026-10-16 user ask:
        # "opens like a stretched sheet of paper"). Mounted SQUASHED - see
        # ACCOUNT_PANEL_SQUASH - so a single write inside _open_account_panel
        # both slides and unfurls it.
        animate_scale=ft.Animation(ACCOUNT_ANIM_MS, ft.AnimationCurve.EASE_OUT_CUBIC),
        scale=ft.Scale(scale_x=1, scale_y=ACCOUNT_PANEL_SQUASH,
                       alignment=ft.Alignment.TOP_RIGHT),
        # It is docked to the right edge, so only the free (left) edge is
        # rounded, and one soft shadow lifts it off the scrim - a sheet
        # resting on the window rather than a slab cut into it. The blur is
        # deliberately small: a wide blur is re-rasterised on every frame of
        # the unfurl.
        border_radius=ft.BorderRadius(top_left=RADIUS, top_right=0,
                                      bottom_left=RADIUS, bottom_right=0),
        shadow=ft.BoxShadow(
            blur_radius=16,
            color=ft.Colors.with_opacity(0.45, "#000000"),
            offset=ft.Offset(-8, 0),
        ),
        padding=ft.padding.Padding.only(left=24, right=24, top=28, bottom=24),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Account", size=22, color=TEXT, font_family=FONT_DISPLAY,
                                expand=True),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE_ROUNDED, icon_size=20,
                            icon_color=TEXT_DIM, tooltip="Close",
                            on_click=_close_account_panel,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=18),
                ft.Row([profile_avatar_with_parrot], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(height=14),
                profile_dialog_username,
                ft.Container(height=10),
                profile_username_field,
                ft.Container(height=18),
                pixel_divider(),
                ft.Container(height=10),
                section_label("Profile picture"),
                ft.Container(height=8),
                ft.Row([profile_pfp_upload_btn, profile_pfp_remove_btn], spacing=10),
                ft.Container(height=6),
                profile_pfp_status,
                ft.Container(height=18),
                pixel_divider(),
                ft.Container(height=10),
                section_label("Wearing"),
                ft.Container(height=12),
                # Skin beside cape, the way they sit on the player in-game.
                ft.Row(
                    [
                        ft.Column(
                            [wear_skin_img, wear_skin_name, wear_skin_meta],
                            spacing=4, tight=True,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Column(
                            [wear_cape_img, wear_cape_name, wear_cape_meta],
                            spacing=4, tight=True,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=24,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Container(height=8),
                ft.Text("Change them on the Cosmetics tab.", size=10.5,
                        color=TEXT_DIM),
            ],
            spacing=2,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )
    page.overlay.extend([account_scrim, account_panel])

    def _open_account_panel(e=None):
        # "Opens like a stretched sheet of paper" (user ask, 2026-10-16): the
        # panel is MOUNTED squashed, so this ONE write unfurls it - `right`
        # slides it in and `scale_y` stretches it down from the top-right
        # corner, on one shared duration. No timers, one flush.
        #
        # refresh_wearing() runs first so its caption changes ride the same
        # refresh (its image composites are a worker thread and land later).
        refresh_wearing()
        account_scrim.visible = True
        account_scrim.opacity = 1
        account_panel.right = 0
        account_panel.scale = ft.Scale(scale_x=1, scale_y=1,
                                       alignment=ft.Alignment.TOP_RIGHT)
        # Per-control diff (see _close_account_panel): a page.update() here
        # was the "whole app reloads" jank - it re-synced every mounted tab.
        thread_safe_ui.refresh(account_scrim)
        thread_safe_ui.refresh(account_panel)

    def refresh_profile_tab():
        """Called whenever the Profile tab becomes active, so its fields
        and the embedded skin section reflect current state (username,
        selected version/loader) rather than whatever was last built."""
        profile_pfp_status.value = ""
        profile_username_field.value = cfg["username"]
        profile_username_field.error_text = None
        rebuild_skin_section()

    # Brand mark - the cube icon and wordmark. Mounted at the left edge of
    # the top bar. (The Minecraft-style nametag that used to ride after the
    # wordmark is gone - the player's name lives in the Account dialog.)
    sidebar_brand = ft.Row(
        [
            ft.Image(src="cube.svg", width=32, height=32, fit=ft.BoxFit.CONTAIN),
            ft.Text("Cubeon", size=19, color=TEXT, font_family=FONT_DISPLAY),
        ],
        spacing=10,
    )

    # The sidebar is gone (top navigation now). The brand mark mounts in the
    # top bar; the dev-only UI inspector toggle keeps a home in the top bar's
    # right cluster via the same _inspector_enabled flag.
    top_bar = _build_top_bar()
    if _inspector_enabled:
        # Dev-only UI inspector toggle (CUBEON_INSPECT=1): opens the live
        # text/property editor. Sits left of the Account icon.
        try:
            top_bar.content.controls.insert(3, ft.IconButton(
                icon=ft.Icons.BUG_REPORT, icon_size=18, icon_color=TEXT_FAINT,
                tooltip="Inspect UI", on_click=lambda e: _open_inspector(),
            ))
        except Exception:
            pass  # a missing dev toggle must never break the layout

    # -----------------------------------------------------------------
    # PLAY TAB - the main "Play" tab content
    # -----------------------------------------------------------------

    # --- UI elements for the Play tab ---

    # Username input field - pre-filled with the stored username from config
    username_field = ft.TextField(
        value=cfg["username"],
        label="Username",
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM),
        text_style=ft.TextStyle(font_family=FONT_MONO),  # Use monospaced for usernames
        bgcolor=SURFACE_HI,
        border_radius=RADIUS,
        height=48,
    )

    # The Play tab's username field shares the Account field's single
    # debounce slot (defined up with the Account field): same account, one
    # publish path, newest edit wins. (The old code kept two independent
    # timers whose pending names could overwrite each other.)
    #
    # Why the name is safe to change at all: the username is purely a
    # display/impersonable name - the account's real UUID comes from the
    # stable auth_key.json identity (core.stable_uuid()), so a rename keeps
    # the same player UUID, cosmetics, and friends account; only the visible
    # name and the CustomSkinLoader <USERNAME>.png mirror move.

    # Debounce: 1.2s after the last keystroke, or immediately on blur.
    # (Flet events don't carry a type tag, so blur can't be told apart from
    # change here - the blur handler just fires whatever is pending.)
    username_field.on_change = lambda e=None: on_name_keystroke(username_field)
    username_field.on_blur = _fire_pending_name

    # Dropdown to select a Minecraft version (installed or available online)
    version_dropdown = ft.Dropdown(
        label="Version",
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM),
        bgcolor=SURFACE_HI,
        border_radius=RADIUS,
        height=48,
        options=[],  # Will be populated later
        on_select=lambda e: on_version_selected(),  # Called when user picks a version
    )

    # Ordered list of loader ids backing the segmented switcher below - Vanilla
    # plus every mod loader launcher_core knows how to install (Fabric, Quilt,
    # Forge, NeoForge). Index in this list == selected_index on the control.
    LOADER_IDS = list(core.SUPPORTED_LOADERS.keys())

    # Per-segment label controls, kept around so we can restyle them once we
    # actually know (installed / available / unsupported) for the currently
    # selected version, instead of a static row of plain text.
    loader_segment_labels = [
        ft.Text(core.SUPPORTED_LOADERS[lid], color=ACCENT if i == 0 else TEXT_DIM,
                 size=12.5, weight=ft.FontWeight.W_600)
        for i, lid in enumerate(LOADER_IDS)
    ]
    # Small dot under each label - green once we've confirmed that loader is
    # already installed for the selected version, hollow/dim otherwise.
    loader_segment_dots = [
        ft.Container(width=5, height=5, border_radius=RADIUS, bgcolor=ft.Colors.with_opacity(0, ACCENT))
        for _ in LOADER_IDS
    ]
    loader_segment_columns = [
        ft.Column([loader_segment_labels[i], loader_segment_dots[i]],
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3, tight=True)
        for i in range(len(LOADER_IDS))
    ]

    loader_status_text = ft.Text("", size=11, color=TEXT_DIM, visible=False)

    # FPS boost: the Play-menu toggle (moved out of Settings on 2026-10-15).
    # ON = the launcher sets Minecraft's own speed-only graphics options at
    # launch (Fast graphics, minimal particles, no entity shadows, biome
    # blend 0, chunk writes off the render thread) - the big FPS win. OFF =
    # those same keys are written back to Minecraft's defaults at launch, so
    # an install that ran boosted actually looks vanilla again. The player's
    # own visual choices (render distance etc.) are never rewritten either
    # way. Built here so both the Play card and any future surface share it.
    fps_boost_switch = ft.Switch(
        value=bool(cfg.get("fps_boost_enabled", True)),
        active_color=ACCENT,
    )

    def on_fps_boost_change(e):
        cfg["fps_boost_enabled"] = bool(fps_boost_switch.value)
        core.save_config(cfg)
        set_status("FPS boost " +
                   ("on - max FPS at launch" if fps_boost_switch.value
                    else "off - vanilla graphics restored at launch"))

    fps_boost_switch.on_change = on_fps_boost_change

    # Switcher between Vanilla and each supported mod loader. The selected
    # segment is marked by a subtle green wash behind it plus green, semibold
    # label text; the inactive segments stay clearly readable (TEXT_DIM). The
    # small dot under a label is NOT the selection marker - it only records
    # "already installed for this version".
    loader_toggle = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,  # index into LOADER_IDS
        thumb_color=ACCENT_DEEP,  # near-black green - selected background
        bgcolor=SURFACE_HI,
        padding=4,
        controls=loader_segment_columns,
        on_change=lambda e: on_loader_toggle_change(e.control.selected_index),
    )

    # Cache of the last support/installed check, keyed by version id, so
    # re-visiting a version you've already checked this session doesn't
    # re-hit the network every time.
    loader_check_cache: dict[str, dict[str, tuple[bool, bool]]] = {}

    def style_loader_segments(support: "dict[str, tuple[bool, bool]] | None"):
        """Repaints each segment's label/dot based on a support map of
        {loader_id: (supported, installed)}. A None map means "not checked
        yet" - every segment is shown at full opacity with no dot, since we
        don't yet know better and shouldn't guess.

        Dimming rule (one rule, no special cases): a segment is dimmed ONLY
        when it's actually unusable - either the loader isn't supported for
        this version, or it's unsupported-and-uninstalled. A version being
        installed does NOT dim the other segments: the switcher stays
        clickable (on_loader_toggle_change allows switching loaders for an
        installed version - it just re-launches under that loader), so
        painting them as if disabled made the whole pill look broken.
        Selected segment always reads bright on the thumb."""
        for i, lid in enumerate(LOADER_IDS):
            label = loader_segment_labels[i]
            dot = loader_segment_dots[i]
            is_selected = (i == loader_toggle.selected_index)
            base_color = ACCENT if is_selected else TEXT_DIM
            label.color = base_color
            if support is None or lid == "vanilla":
                label.opacity = 1
                dot.bgcolor = ft.Colors.with_opacity(0, ACCENT)
                continue
            supported, installed = support.get(lid, (True, False))
            label.opacity = 1 if (supported or installed) else 0.45
            # Green dot = already installed for this version, so switching
            # to it will jump straight to Play instead of downloading.
            dot_color = ACCENT if is_selected else ACCENT_DIM
            dot.bgcolor = ft.Colors.with_opacity(1 if installed else 0, dot_color)
        page.update()

    def refresh_loader_support(version_id):
        """Runs in the background: checks every loader's support + installed
        status for version_id, then repaints the switcher. This is what makes
        the switcher "real" - it reflects the actual state of the selected
        version instead of always looking the same regardless of context.

        The loader is only a choice at install time: once version_id is
        already installed, we detect which loader (if any) it was installed
        with, snap the switcher to it. For a not-yet-installed version, the
        switcher stays free to pick from.

        The four network checks run in PARALLEL (one thread per loader):
        serially they take ~4s of "Checking..." with the toggle disabled,
        which read as the launcher being stuck. In parallel the whole check
        is as fast as the slowest loader (~1-2s), and repeats are served
        from the session cache instantly."""
        if not version_id:
            style_loader_segments(None)
            loader_status_text.visible = False
            page.update()
            return

        already_installed = version_id in state["installed"]

        cached = loader_check_cache.get(version_id)
        if cached:
            if already_installed:
                lock_loader_to_installed(version_id, cached)
            else:
                loader_toggle.disabled = False
            style_loader_segments(cached)
            loader_status_text.visible = False
            page.update()
            return

        loader_toggle.disabled = True
        loader_status_text.value = "Checking loader availability..."
        loader_status_text.visible = True
        page.update()

        # Loader support/installed checks key off the numeric MC version, not
        # the raw dropdown id: when the selection is a loader-install row
        # ("fabric-loader-0.19.3-1.21.1"), the raw id would make every
        # installed-loader lookup miss and every support check answer
        # "unsupported" (same trap the launch path documents for itself).
        base_version = core.extract_mc_version(version_id) or version_id

        def worker():
            support: dict[str, tuple[bool, bool]] = {}
            results: dict[str, bool] = {}
            lock = threading.Lock()

            def check(lid):
                try:
                    supported = core.is_loader_supported(lid, base_version)
                except Exception:
                    supported = False
                with lock:
                    results[lid] = supported

            threads = [threading.Thread(target=check, args=(lid,), daemon=True)
                       for lid in LOADER_IDS if lid != "vanilla"]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # If the user already moved on to a different version while this
            # was running, don't paint stale results over the new selection.
            # The cache is still written: the results are true for this
            # version regardless of what's selected now, and a later
            # re-selection gets them for free.
            stale = version_dropdown.value != version_id
            if stale:
                with lock:
                    loader_check_cache[version_id] = {
                        lid: (results.get(lid, False),
                              bool(core.find_installed_loader_version(state["installed"], lid, base_version)))
                        for lid in LOADER_IDS if lid != "vanilla"
                    }
                return

            support = {
                lid: (results.get(lid, False),
                      bool(core.find_installed_loader_version(state["installed"], lid, base_version)))
                for lid in LOADER_IDS if lid != "vanilla"
            }
            loader_check_cache[version_id] = support

            loader_status_text.visible = False
            if already_installed:
                # Already installed - the loader was decided at install time.
                # Detect which one and lock the switcher to it.
                lock_loader_to_installed(version_id, support)
                style_loader_segments(support)
                page.update()
                return

            loader_toggle.disabled = False
            style_loader_segments(support)
            # If the currently-selected loader turned out to be unsupported
            # for this version, fall back to the first supported one rather
            # than silently letting the user hit "unsupported" at launch.
            selected_id = LOADER_IDS[loader_toggle.selected_index]
            if not support.get(selected_id, (True, False))[0]:
                fallback = next((lid for lid in LOADER_IDS
                                 if support.get(lid, (False, False))[0]), None)
                if fallback and fallback != selected_id:
                    loader_status_text.value = (
                        f"{core.SUPPORTED_LOADERS[selected_id]} isn't available "
                        f"for this version, switched to {core.SUPPORTED_LOADERS[fallback]}.")
                    loader_status_text.visible = True
                    loader_toggle.selected_index = LOADER_IDS.index(fallback)
                    state["mod_loader"] = fallback
                    style_loader_segments(support)
                    refresh_mods_list()
                    refresh_browse_for_new_profile()
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    def lock_loader_to_installed(version_id, support):
        """For a version that's already installed, figure out which loader
        (if any) it was installed with and snap the switcher to it. The
        switcher stays clickable (the handler allows a switch to Vanilla and
        a re-switch): only the SELECTION is pinned to the install truth, not
        the whole control. See on_loader_toggle_change."""
        # Prefer the loader that's already selected when it's genuinely
        # installed for this version. A version can have more than one loader
        # installed at once (e.g. a modpack's Fabric install plus a manual
        # Forge one), and blindly taking the first installed loader in list
        # order would then lock to the wrong one - clobbering the loader a
        # modpack handoff just set. Falling back to first-installed only when
        # the current pick isn't installed keeps old single-loader behaviour.
        current = state.get("mod_loader")
        detected = None
        # A PENDING loader install (user armed Play to add Fabric/Quilt/Forge
        # to an installed vanilla version) outranks the on-disk truth: snap
        # to it so the re-run of refresh_loader_support doesn't undo the
        # choice, and let do_install_and_launch act on it.
        pending = state.get("pending_loader_install") or {}
        if (pending.get("version_id") == version_id
                and pending.get("loader") in LOADER_IDS):
            detected = pending["loader"]
        if detected is None and current and support.get(current, (False, False))[1]:
            detected = current
        # Also check vanilla: a bare mc_version in installed_ids means
        # a vanilla (loader-less) install. Vanilla is always supported
        # and appears in LOADER_IDS, so check it explicitly if no mod
        # loader was detected above.
        if detected is None and "vanilla" in LOADER_IDS:
            if core.find_installed_loader_version(state["installed"], "vanilla", version_id):
                detected = "vanilla"
        if detected is None:
            for lid in LOADER_IDS:
                if lid == "vanilla":
                    continue
                if support.get(lid, (False, False))[1]:
                    detected = lid
                    break
        if detected in LOADER_IDS:
            loader_toggle.selected_index = LOADER_IDS.index(detected)
        else:
            # Fallback: keep the switcher on the first option.
            loader_toggle.selected_index = 0
        state["mod_loader"] = detected
        # Keep the switcher clickable: the handler allows a one-way switch
        # back to Vanilla for an installed version, and snaps anything else.
        loader_toggle.disabled = False
        update_hero()
        update_pack_badge()

    def on_loader_toggle_change(idx):
        """Updates the state when the loader switcher changes, and refreshes
        everything that depends on it (mod list is per version+loader profile,
        and the play button availability can change since the loader may not
        be installed for the currently selected version)."""
        version_id = version_dropdown.value
        new_loader = LOADER_IDS[idx] if 0 <= idx < len(LOADER_IDS) else LOADER_IDS[0]
        if version_id and version_id in state["installed"]:
            # The loader choice was made at install time, but the switcher
            # isn't a trap: Vanilla is always allowed (the plain version is
            # on disk; launching it just skips the mods folder), and so is
            # any loader that's actually INSTALLED for this version (the
            # launch finds it and plays it - no reinstall). A loader that
            # would have to be installed fresh is ALSO allowed now - it just
            # arms the Play button to install it (mode "install_loader"),
            # exactly like picking a not-yet-downloaded version arms it to
            # download. The old code snapped the pill back with "pick it
            # before installing", which was a dead end: there was nothing to
            # pick, so a vanilla install could never gain Fabric.
            if new_loader == "vanilla":
                state["pending_loader_install"] = None
                if state["mod_loader"] != "vanilla":
                    state["mod_loader"] = "vanilla"
                    loader_status_text.value = "Switched to Vanilla - mods won't load for this version."
                    loader_status_text.visible = True
                    style_loader_segments(loader_check_cache.get(version_id))
                    refresh_mods_list()
                    on_version_selected()
                    page.update()
                return
            cached_support = loader_check_cache.get(version_id)
            installed_loader = core.find_installed_loader_version(
                state["installed"], new_loader,
                core.extract_mc_version(version_id) or version_id)
            if installed_loader:
                state["pending_loader_install"] = None
                state["mod_loader"] = new_loader
                loader_status_text.visible = False
                style_loader_segments(cached_support)
                refresh_mods_list()
                on_version_selected()
                update_hero()
                page.update()
                return
            # Supported but not installed: select it and arm Play to install.
            # lock_loader_to_installed (re-run on every version re-selection)
            # would otherwise snap straight back to the installed truth, so the
            # choice is recorded as a PENDING install it knows to respect.
            supported = True
            if cached_support is not None:
                supported = cached_support.get(new_loader, (True, False))[0]
            if not supported:
                loader_toggle.selected_index = max(0, LOADER_IDS.index(state["mod_loader"])) \
                    if state["mod_loader"] in LOADER_IDS else 0
                loader_status_text.value = f"{core.SUPPORTED_LOADERS[new_loader]} isn't available for this version."
                loader_status_text.visible = True
                page.update()
                return
            state["pending_loader_install"] = {"version_id": version_id,
                                               "loader": new_loader}
            state["mod_loader"] = new_loader
            loader_status_text.value = (f"{core.SUPPORTED_LOADERS[new_loader]} will be "
                                        f"installed when you press Play.")
            loader_status_text.visible = True
            style_loader_segments(cached_support)
            refresh_mods_list()
            on_version_selected()   # recomputes the button (-> install_loader)
            update_hero()
            page.update()
            return
        state["pending_loader_install"] = None
        cached = loader_check_cache.get(version_id) if version_id else None
        if cached and not cached.get(new_loader, (True, False))[0]:
            # Block the switch outright - snap back and explain, rather than
            # letting the user pick something that will only fail later.
            loader_toggle.selected_index = max(0, LOADER_IDS.index(state["mod_loader"])) \
                if state["mod_loader"] in LOADER_IDS else 0
            loader_status_text.value = f"{core.SUPPORTED_LOADERS[new_loader]} isn't available for this version."
            loader_status_text.visible = True
            page.update()
            return
        loader_status_text.visible = False
        state["mod_loader"] = new_loader
        style_loader_segments(cached)
        refresh_mods_list()
        on_version_selected()

    # A row for the "Show snapshots" checkbox - lives in the Settings tab's
    # Game versions card now (always visible there; it only affects what the
    # online fetch includes, and toggling it re-fetches immediately).
    browse_online_row = ft.Row(
        [
            ft.Checkbox(
                label="Show snapshots", value=False, check_color=BG, active_color=ACCENT,
                label_style=ft.TextStyle(color=TEXT_DIM, size=12),
                on_change=lambda e: refresh_version_list(online=True),  # Reload versions when toggled
            ),
        ],
    )
    show_snapshots = browse_online_row.controls[0]  # Reference to the checkbox

    # --- Legacy versions + one-click version update ----------------------
    #
    # Everything below 1.20 is LEGACY for Cubeon: the in-game client mod's
    # jar matrix (mod/brackets.json) starts at 1.20.1, so on an older version
    # there is no Friends button, no skins/capes sync, no Cubeon anything -
    # vanilla with extra steps. Rather than pretending otherwise, those
    # versions are hidden behind an explicit "Legacy" opt-in that says exactly
    # that. The opt-in persists in config ("legacy_versions"): off for new
    # users, kept for returning ones.
    state.setdefault("legacy_ok", bool(cfg.get("legacy_versions", False)))

    def _is_legacy_version(version_id):
        """True for versions below 1.20 (numeric MC versions only - snapshots
        and unparseable ids are left alone; gating what we can't classify
        would hide playable versions on a parsing bug)."""
        mc = core.extract_mc_version(version_id) if version_id else None
        if not mc:
            return False
        try:
            parts = tuple(int(p) for p in mc.split(".")[:3])
        except ValueError:
            return False
        while len(parts) < 3:
            parts += (0,)
        return parts < (1, 20, 0)

    legacy_note = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.HISTORY_ROUNDED, size=14, color=TEXT_DIM),
                ft.Text(
                    "These old versions run plain vanilla - no mods, skins "
                    "or friends.",
                    size=12, color=TEXT_DIM, expand=True,
                ),
            ],
            spacing=8,
        ),
        visible=False,
    )

    legacy_btn_label = ft.Text(
        "Legacy: on" if state.get("legacy_ok") else "Legacy",
        size=12, color=ACCENT if state.get("legacy_ok") else TEXT_DIM,
        weight=ft.FontWeight.W_600)

    def _set_legacy_ui(on):
        """One place for the Legacy toggle's visible state. Persisted so the
        choice survives a restart (a user who enabled legacy once shouldn't
        watch the versions vanish again on next launch)."""
        state["legacy_ok"] = on
        cfg["legacy_versions"] = on
        try:
            core.save_config(cfg)
        except Exception:
            pass  # a failed save keeps working for this session
        legacy_note.visible = on
        legacy_btn_label.value = "Legacy: on" if on else "Legacy"
        legacy_btn_label.color = ACCENT if on else TEXT_DIM

    def _do_enable_legacy(e=None, dlg=None):
        _set_legacy_ui(True)
        if dlg is not None:
            _close_dialog(dlg)
        # Synchronous, like the browse-online link: refresh_version_list ends
        # in page.update(), which must stay on the UI thread.
        refresh_version_list(online=True)
        set_status("Legacy versions enabled")

    def on_enable_legacy(e=None):
        """The opt-in dialog. One clear sentence about what legacy costs,
        then it never nags again this session (the note stays visible)."""
        if state.get("legacy_ok"):
            # Already on: clicking again hides legacy versions again.
            _set_legacy_ui(False)
            refresh_version_list()
            set_status("Legacy versions hidden")
            return
        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Text("Enable legacy versions?", color=TEXT, weight=ft.FontWeight.W_800),
            content=ft.Container(
                content=ft.Text(
                    "Versions below 1.20 run plain vanilla - no mods, skins "
                    "or friends.\n\n"
                    "Show legacy versions in the list?",
                    size=13, color=TEXT,
                ),
                width=380,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: _close_dialog(dlg)),
                ft.TextButton("Enable legacy", on_click=lambda e: _do_enable_legacy(dlg=dlg),
                              style=ft.ButtonStyle(color=ACCENT)),
            ],
        )
        _open_dialog(dlg)

    legacy_btn = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.HISTORY_ROUNDED, color=TEXT_DIM, size=14),
                legacy_btn_label,
            ],
            spacing=6,
        ),
        on_click=on_enable_legacy,
        ink=False,
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=10, vertical=6),
        tooltip="Show or hide versions below 1.20",
    )

    # -----------------------------------------------------------------
    # THE VERSION PICKER - the dropdown's face and its search dialog.
    #
    # Online mode pulls in every release Mojang has ever shipped (600+
    # entries), so the raw dropdown became a wall of text nobody could scan.
    # The ft.Dropdown itself stays the source of truth (value/options - dozens
    # of code paths read and write it) but it is NOT mounted: a plain dropdown
    # can't hold a search box. Instead the compact button below opens a dialog
    # that filters its OWN snapshot of the list and only commits via a row
    # click - typing in the search box must never move the live selection or
    # kick off a download. The whole thing (rows grouped Installed / Available,
    # each tagged with its loader and release date) lives in ui/versions.py.
    # -----------------------------------------------------------------

    def _dropdown_label(val):
        """The friendly text for `val` - the option's own label when it has
        one, otherwise a readable name built from the id (never None while a
        value is set).

        An installed loader row ("fabric-loader-0.19.5-26.1.2") is a real
        instance the user can select from "Jump back in", but it is not always
        in the dropdown's option list - the online list is Mojang's, and a
        version installed after that list was built is missing from it too.
        Neither Flet nor the picker's label has a label to render then, so both
        fell back to the raw launch id: that is the "technical stuff like
        fabric loader 0.x" the user saw (2026-10-16).
        """
        for o in version_dropdown.options or []:
            if o.key == val:
                return (o.text or o.key).strip() or val
        if not val:
            return None
        # "fabric-loader-0.19.5-26.1.2" -> "26.1.2 (Fabric)"; already-friendly
        # ids ("1.20.1") come back unchanged.
        return core.suggest_friendly_name(str(val), str(val))

    def _ensure_version_option(version_id):
        """Make sure `version_id` is an option of its own dropdown.

        Flet renders a Dropdown whose value matches no option with the raw
        value as its text, so selecting a just-installed instance from "Jump
        back in" could show its technical launch id until some later refresh
        rebuilt the list. Adding the missing option keeps .value inside
        .options, which is the invariant the label and picker code assume.
        """
        if not version_id:
            return
        if any(o.key == version_id for o in (version_dropdown.options or [])):
            return
        meta = (state.get("installed_meta") or {}).get(version_id) or {}
        name = meta.get("display_name") or core.suggest_friendly_name(
            str(version_id), str(version_id))
        mark = "⚠" if meta.get("incomplete") else "●"
        version_dropdown.options = list(version_dropdown.options or []) + [
            ft.dropdown.Option(key=version_id, text=f"{name}  {mark}")]
        thread_safe_ui.refresh(version_dropdown)

    def _pick_version(key):
        """A click on a row in the picker dialog: select it and apply it."""
        _ensure_version_option(key)
        version_dropdown.value = key
        picker.sync_label()
        on_version_selected()

    picker = VersionPicker(
        page,
        get_selected=lambda: version_dropdown.value,
        label_for=_dropdown_label,
        on_pick=_pick_version,
        on_browse_online=lambda: refresh_version_list(online=True),
        # Bound lazily: instances_manager is built further down, and this only
        # runs on a click. "Manage installed versions" lives in the picker now,
        # not in the Jump back in header.
        on_manage=lambda: instances_manager.open(),
    )
    version_dropdown_button = picker.button

    # Progress bar and label shown during installation/launch
    progress_bar = ft.ProgressBar(
        value=0, bgcolor=SURFACE_HI, color=ACCENT, bar_height=6, border_radius=RADIUS,
        visible=False,
    )
    progress_label = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO, visible=False)

    # Small native spinner next to the progress label during installs/launches
    # - a crisp, animated ProgressRing (no image asset), so "something's
    # working" has one consistent visual instead of a bare progress bar with
    # no motion of its own while a step (e.g. extracting) sits at a static
    # percentage.
    progress_spinner = ft.ProgressRing(
        width=16, height=16, stroke_width=2, color=ACCENT, visible=False,
    )
    # The main play button doubles as the stop control: while an install is
    # in flight it shows CANCEL, and while a game is live it shows QUIT GAME
    # (see set_button_mode / _main_action_click). A separate little Cancel
    # pill next to the progress bar used to compete with the big button and
    # was easy to miss - the row now carries only progress.
    progress_row = ft.Row(
        [progress_spinner, progress_label], spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # The main play button - its appearance changes based on state (play/download/busy)
    play_button_icon = ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED, color=ON_ACCENT, size=18)
    play_button_text = ft.Text("PLAY", size=15, color=ON_ACCENT,
                               weight=ft.FontWeight.W_700,
                               style=ft.TextStyle(letter_spacing=0.5))

    # Soft red fill for the button's stop meanings (CANCEL / QUIT GAME): a
    # redstone tint over the dark surface, quiet enough to sit in the card
    # but unmistakably not a green "go" action.
    _STOP_BG = ft.Colors.with_opacity(0.16, DANGER)
    _STOP_BG_HI = ft.Colors.with_opacity(0.28, DANGER)

    def _main_action_click(e=None):
        """The one big button, three meanings: while an install is in flight
        it is Cancel, while a game is live it is Quit Game, otherwise it
        starts the normal play/download flow. Defined before play_button (it
        is its on_click); every name it touches resolves at click time."""
        if state.get("installing_version"):
            on_cancel_install()
            return
        if state.get("running_version"):
            _quit_running_game()
            return
        on_play_click()

    def _on_play_hover(hovering: bool):
        """Brighten the hero button on hover so it reads as the obvious next
        step. Only the live fills react; the disabled states (launching,
        cancelling, ending, incomplete) must not appear clickable.

        motion.polish (below the button) calls this with the hover flag, and
        that is also what supplies the lift, the press dip and the glass hover.
        The FILL stays the button's own business because it depends on what the
        button means right now (play / cancel / quit / installing), and the
        sheen's own sweep is fired from here too - it is the one bit of the
        button's response that is decoration rather than state.
        """
        if play_button.disabled:
            return
        if hovering:
            play_sheen.run()
        else:
            play_sheen.reset()
        value = play_button_text.value
        if value == "PLAY":
            play_button.bgcolor = ACCENT_HI if hovering else ACCENT
        elif value in ("CANCEL", "QUIT GAME"):
            play_button.bgcolor = _STOP_BG_HI if hovering else _STOP_BG
        else:  # download / install loader
            play_button.bgcolor = "#63C7D8" if hovering else INFO

    play_button = ft.Container(
        content=ft.Row(
            [play_button_icon, play_button_text],
            alignment=ft.MainAxisAlignment.CENTER, spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=ACCENT,
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=14, horizontal=20),
        alignment=ft.Alignment.CENTER,
        ink=False,
        on_click=_main_action_click,  # play / cancel / quit, by state
    )
    # The launcher's one primary action gets the full affordance: the fill
    # callback above, plus motion's hover lift, press dip and glass hover
    # (Settings > Display > Motion turns the movement down). `active` is what
    # stops a disabled button - launching, cancelling, incomplete - from lifting
    # or dipping.
    motion.polish(play_button, on_hover_fill=_on_play_hover,
                  active=lambda: not play_button.disabled,
                  glass=theme.glass_hover())
    # ... and the specular sheen that sweeps across it every time the pointer
    # arrives (cubeon/motion.py's Sheen).
    #
    # HIT-TEST RULE (2026-10-19, this is why PLAY "didn't work"): the sheen
    # must live INSIDE the button, never as a Stack sibling painted on top of
    # it. As a sibling, the sweeping band is a full-size painted layer exactly
    # over the button whenever the pointer is inside it (hover = opacity 1),
    # and in a real window it absorbs the tap - the click never reached
    # on_click (the session log showed ZERO handler activity while the user
    # hammered PLAY; headless can't see it because there is no pointer). A
    # descendant of the button's content is painted over the row too, but taps
    # still belong to the widget that owns on_click. motion.Sheen's own doc
    # says "under the content" for the same reason.
    play_sheen = motion.sheen(radius=RADIUS)
    play_button.content = ft.Stack(
        [
            ft.Row(
                [play_button_icon, play_button_text],
                alignment=ft.MainAxisAlignment.CENTER, spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            play_sheen.control,
        ],
        expand=True,
    )

    # Text to show any issues with the selected version (e.g., incomplete install)
    version_issue_text = ft.Text("", size=12, color=DANGER, visible=False)

    # When the selected version+loader is one an installed modpack owns, show
    # the pack's real name here. Without it a pack reads only as its bare MC
    # version + loader (e.g. "1.20.1 (Fabric)"), so the user can't tell which
    # pack they're about to launch - see go_to_pack / update_pack_badge.
    pack_name_text = ft.Text("", size=12, color=ACCENT, weight=ft.FontWeight.W_600,
                             font_family=FONT_MONO)
    pack_name_badge = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=ACCENT, size=15), pack_name_text],
            spacing=6,
        ),
        visible=False,
    )

    # --- Helper functions for the Play tab ---

    def _fixing_selected():
        """Is Cubeon's background mod repair working on the selected profile?

        The claim is the version id the doctor was started for, so a repair
        running for ANOTHER instance never freezes this button.
        """
        claim = state.get("fixing_mods")
        return bool(claim) and claim == version_dropdown.value

    def _pack_installing_selected():
        """Is a modpack install writing the selected version right now?

        The claim comes from cubeon.modpacks' in-flight registry, not a UI
        flag, so it is true whichever surface started the install (Modpacks
        tab, Settings > Import). Keyed by the BASE Minecraft version: a pack
        install rewrites versions/<mc> and its (mc, loader) profile, so every
        instance on that version is unsafe to launch until it finishes. Never
        raises - a transient backend hiccup must not wedge the button.
        """
        try:
            vid = version_dropdown.value
            return bool(vid and core.pack_install_for(
                core.extract_mc_version(vid)))
        except Exception:
            return False

    def set_button_mode(mode):
        """
        Changes the play button's appearance based on the current state.
        Modes:
          - 'play': ready to launch (green)
          - 'download': version not installed, offer download (cyan)
          - 'busy': install in flight - the button IS Cancel (red, active)
          - 'launching' / 'cancelling' / 'ending': transient, non-stoppable
            waits (disabled, hourglass)
          - 'running': the game process is currently open - the button IS
            Quit Game (red, active)
          - 'working': a live game session and an install in flight outrank
            play/download; 'working' is the post-install doctor/mod repair
            (nothing to cancel, so it is disabled rather than a stop button)
          - 'installing': a modpack install (Modpacks tab or Settings >
            Import) is still writing THIS instance. Disabled, not a Cancel -
            that install owns its own progress bar and cancel button.
          - 'incomplete': installed but broken (disabled, error icon)

        Foreground colour is set per-mode alongside the fill, not just once at
        creation: the play/download fills are light (green/cyan) so they take
        dark ON_ACCENT text, but the disabled busy/running/incomplete fills are
        dark (SURFACE_HI) - leaving the text dark there rendered it nearly
        invisible (dark-on-dark). Each disabled state now also carries a
        *semantic* colour so the button's meaning reads at a glance: dim = a
        transient wait, green = the game is live, red = a broken install.
        """
        def paint(bg, fg):
            play_button.bgcolor = bg
            play_button_icon.color = fg
            play_button_text.color = fg

        # Two claims outrank "ready to play", and they are enforced HERE rather
        # than at every caller, because a stray paint is exactly how the user
        # ended up staring at PLAY while the game was running (2026-10-16) and
        # while Cubeon was still installing mods / running the doctor. Any
        # selection refresh, a prefetch finishing, or an exit-path reset for a
        # version nobody is looking at could repaint "play" over a live claim.
        # Clicking that button QUITS the running game - the click routes on
        # running_version - so the lie is expensive, not cosmetic.
        if mode in ("play", "download", "install_loader"):
            if state.get("running_version"):
                mode = "running"
            elif state.get("installing_version"):
                mode = "busy"
            elif _pack_installing_selected():
                mode = "installing"
            elif _fixing_selected():
                mode = "working"

        if mode == "play":
            paint(ACCENT, ON_ACCENT)
            play_button_icon.name = ft.Icons.PLAY_ARROW_ROUNDED
            play_button_text.value = "PLAY"
            play_button.disabled = False
        elif mode == "download":
            paint(INFO, ON_ACCENT)  # diamond cyan = download, not play (on-palette)
            play_button_icon.name = ft.Icons.DOWNLOAD_ROUNDED
            play_button_text.value = "DOWNLOAD & PLAY"
            play_button.disabled = False
        elif mode == "install_loader":
            # Same cyan as download: this arm's Play to fetch something new
            # (a mod loader) rather than relaunch what's already on disk.
            paint(INFO, ON_ACCENT)
            play_button_icon.name = ft.Icons.DOWNLOAD_ROUNDED
            _ldr_label = core.SUPPORTED_LOADERS.get(
                state.get("mod_loader") or "", "loader").upper()
            play_button_text.value = f"INSTALL {_ldr_label} & PLAY"
            play_button.disabled = False
        elif mode == "busy":
            # While an install runs the main button IS the cancel button -
            # the old separate Cancel pill next to the progress bar competed
            # with the big button and was easy to miss.
            paint(_STOP_BG, DANGER)
            play_button_icon.name = ft.Icons.CANCEL_ROUNDED
            play_button_text.value = "CANCEL"
            play_button.disabled = False
        elif mode in ("launching", "cancelling", "ending"):
            # Transient waits where stopping is no longer (or not yet)
            # possible: the install phase is over and the game is spawning
            # (launching), a cancel has been requested and the worker is
            # aborting (cancelling), a quit was requested and the process is
            # going down (ending). Disabled, quiet, honest.
            paint(SURFACE_HI, TEXT_DIM)
            play_button_icon.name = ft.Icons.HOURGLASS_TOP_ROUNDED
            play_button_text.value = {
                "launching": "LAUNCHING...",
                "cancelling": "CANCELLING...",
                "ending": "ENDING...",
            }[mode]
            play_button.disabled = True
        elif mode == "running":
            # The main button IS the quit button while the game is live.
            # The old disabled "GAME RUNNING..." left the user with no way
            # to end the game from the launcher at all.
            paint(_STOP_BG, DANGER)
            play_button_icon.name = ft.Icons.STOP_CIRCLE_ROUNDED
            play_button_text.value = "QUIT GAME"
            play_button.disabled = False
            play_button.tooltip = ("Close Minecraft now. Unsaved progress "
                                   "since the game's last autosave is lost.")
        elif mode == "working":
            # Cubeon is still busy with this profile (the post-install doctor /
            # mod repair, cubeon/doctor.py). Nothing to cancel here - unlike an
            # install - but the button must not claim PLAY until the work is
            # done: that is the "PLAY came very early, while it was installing
            # mods and fixing with the doctor" report (2026-10-16). Disabled,
            # with the reason in the tooltip.
            # NOT disabled (2026-10-18). This used to grey the button out for as
            # long as the doctor ran, which is a repair pass over every mod, pack
            # and shader on the profile WITH a network check per item - and one
            # that, before the packformat temp-file fix, could fail on a broken
            # resource pack and leave the claim up until the 120s ceiling. The
            # live report was "I cannot click the play button": a disabled
            # Container swallows clicks silently, so the user got no launch, no
            # error, no clue. Repair is housekeeping, not a lock: the click is
            # accepted and launch_game runs its own verify pass, which is the
            # same doctor work on the critical path anyway. The button keeps
            # saying PLAY and simply explains what else is happening.
            paint(ACCENT, ON_ACCENT)
            play_button_icon.name = ft.Icons.PLAY_ARROW_ROUNDED
            play_button_text.value = "PLAY"
            play_button.disabled = False
            play_button.tooltip = ("Cubeon is also checking this profile's "
                                   "mods in the background - Play launches "
                                   "anyway.")
        elif mode == "installing":
            # A pack install is still writing this instance (base version,
            # loader, then every mod into its profile). It is NOT cancellable
            # from here - the Modpacks tab / Import owns that progress and its
            # Cancel - so this is a disabled wait, never a lying CANCEL. Play
            # returns the moment the installer's listener clears the claim.
            paint(SURFACE_HI, TEXT_DIM)
            play_button_icon.name = ft.Icons.HOURGLASS_TOP_ROUNDED
            play_button_text.value = "INSTALLING..."
            play_button.disabled = True
            play_button.tooltip = ("Cubeon is still installing this instance - "
                                   "Play unlocks when it finishes.")
        else:  # incomplete
            paint(SURFACE_HI, DANGER)
            play_button_icon.name = ft.Icons.ERROR_OUTLINE_ROUNDED
            play_button_text.value = "INCOMPLETE INSTALL"
            play_button.disabled = True
        if mode not in ("running", "working", "installing"):
            play_button.tooltip = None
        # Scoped repaint: every icon/text/fill mutated above lives inside
        # play_button, so diffing just its subtree (~3 controls) paints the
        # change instead of page.update()'s whole-page diff (~hundreds of
        # controls re-sent over the websocket on every selection change).
        # Same visibility guarantee: refresh() routes through the loop like
        # the patched page.update() does, from any thread.
        thread_safe_ui.refresh(play_button)  # Refresh UI to show changes

    def _sync_play_button():
        """Repaint the big button from the live state - one authority.

        The callers that used to hand-pick a mode ("play" if installed, else
        "download") could paint a mode the state did not support, which is how
        a finishing prefetch or an exit-path reset repainted PLAY over a live
        claim - a running game, an install in flight, or the post-install
        doctor still fixing mods (both reported 2026-10-16). This recomputes
        from the same state those claims live in, and set_button_mode()
        re-checks the claims anyway, so the two can only agree.
        """
        vid = version_dropdown.value
        if state.get("running_version"):
            set_button_mode("running")
            return
        if state.get("installing_version"):
            set_button_mode("busy")
            return
        if _pack_installing_selected():
            # A pack install owns this instance's disk. The guard inside
            # set_button_mode enforces it for every paint; this early return
            # just keeps the intent visible here too.
            set_button_mode("installing")
            return
        if _fixing_selected():
            set_button_mode("working")
            return
        meta = (state.get("installed_meta") or {}).get(vid) if vid else None
        if meta and meta.get("incomplete"):
            set_button_mode("incomplete")
        elif vid and vid in state["installed"]:
            pending = state.get("pending_loader_install") or {}
            if pending.get("version_id") == vid and pending.get("loader"):
                set_button_mode("install_loader")
            else:
                set_button_mode("play")
        elif vid:
            set_button_mode("download")
        else:
            set_button_mode("play")

    def _refresh_pack_index():
        """Rebuild the (mc_version, loader) -> modpack-name lookup from disk.
        Cheap (reads a handful of small _modpack.json files); called whenever
        the version list is rebuilt so the Play tab can name an installed pack.
        """
        try:
            packs = core.list_installed_modpacks()
        except Exception:
            packs = []
        state["pack_index"] = {
            (p.get("mc_version"), p.get("loader")): p.get("name")
            for p in packs if p.get("mc_version")
        }

    def _rescan_installed():
        """Re-read what is on disk into the shared state and repaint the
        surfaces that render it.

        The install worker adds each stage to ``state["installed"]`` as it
        lands, but "Jump back in", the Instances manager and the hero's meta
        chips render ``state["installed_meta"]`` - a different mapping that
        only a full refresh_version_list() rebuilt. So a version that was just
        installed did not show up as an instance card until something
        unrelated refreshed the list (reported 2026-10-16: "after install the
        instance doesn't come inside jump back in"). Deliberately NOT
        refresh_version_list(): that also re-runs the selection, the mods /
        server refreshes and the doctor, which would fight the install worker
        mid-flight. This is one directory listing plus a restyle of the
        existing cards (InstanceCards.rebuild builds only what is new).
        """
        try:
            versions = core.get_installed_versions()
        except Exception:
            # Leave state as the worker left it - a failed scan must not be
            # able to un-install something in the UI.
            logging.getLogger(__name__).warning("installed scan failed",
                                               exc_info=True)
            return
        state["installed"] = {v["id"] for v in versions}
        state["installed_meta"] = {v["id"]: v for v in versions}
        _refresh_pack_index()
        try:
            update_hero()   # rebuilds the "Jump back in" cards (new ones included)
        except Exception:
            logging.getLogger(__name__).warning("instance repaint failed",
                                               exc_info=True)

    def update_pack_badge():
        """Show the pack name badge iff the current version+loader is a modpack
        install. Keyed on (version, loader) because that pair is the profile a
        pack's mods live in - the same identity launch uses."""
        name = state.get("pack_index", {}).get(
            (state.get("selected_mc_version"), state.get("mod_loader")))
        if name:
            pack_name_text.value = name
            pack_name_badge.visible = True
        else:
            pack_name_badge.visible = False
        page.update()

    _install_locks: dict[str, threading.Lock] = {}

    def _install_lock(version_id: str) -> threading.Lock:
        """One lock per version id so a background prefetch and an actual
        Play click can never run Mojang's installer for the same version
        concurrently (duplicated downloads, interleaved writes)."""
        lock = _install_locks.get(version_id)
        if lock is None:
            lock = threading.Lock()
            _install_locks[version_id] = lock
        return lock

    _prefetched: set[str] = set()

    # Live progress of the invisible prefetch, per version id. A Play click has
    # to wait for that prefetch (they share the per-version install lock), and
    # it used to wait behind a frozen "Preparing" for however long the
    # invisible download had left. It paints from here instead, so the bar and
    # the label keep moving while it waits. Keys: status / value / max.
    _prefetch_view: dict[str, dict] = {}

    class _InstallCancelled(Exception):
        """Raised from an install progress callback to abort a cancelled
        install. mll's own installer does stop when a callback raises, so this
        is the actual cancellation mechanism - but install_version() re-wraps
        callback exceptions as a generic RuntimeError, so callers must decide
        "cancelled vs failed" from the event, never the exception type."""

    _install_cancels: dict[str, threading.Event] = {}

    def _cancel_event(version_id: str) -> threading.Event:
        """One cancellation flag per version id, shared by the background
        prefetch and the Play-click install so cancelling reaches whichever
        of the two is actually running."""
        ev = _install_cancels.get(version_id)
        if ev is None:
            ev = threading.Event()
            _install_cancels[version_id] = ev
        return ev

    def prefetch_version(version_id: str | None) -> None:
        """Starts downloading the selected version in the background the
        moment it's chosen, so by the time the user clicks Play the assets,
        libraries and jar are already on disk and the launch begins
        immediately instead of behind a progress bar. Safe to call often:
        each version is prefetched at most once per session, and the per-
        version install lock keeps it from racing the real installer."""
        if not version_id or version_id in _prefetched:
            return
        _prefetched.add(version_id)

        def _work():
            cancel = _cancel_event(version_id)
            cancel.clear()  # a fresh attempt always starts uncancelled
            try:
                with _install_lock(version_id):
                    if version_id in state["installed"]:
                        return  # someone beat us to it

                    # A pack install is writing this same version folder (it
                    # installs the base version itself). Two mll installers on
                    # one folder race on the same jars, so stand down - the
                    # pack install leaves the version ready anyway, so there is
                    # nothing left for the prefetch to do.
                    _prefetch_mc = core.extract_mc_version(version_id)
                    if core.pack_install_for(_prefetch_mc):
                        return

                    def _guard(*_a):
                        # A prefetch is invisible, but a Play click can block on
                        # access to the install lock while it runs - so the
                        # prefetch has to honor the same cancel flag or a
                        # cancelled click would just hang behind it. It also
                        # stands down the moment a pack install claims this
                        # version mid-flight (its per-file callbacks land here).
                        if cancel.is_set() or core.pack_install_for(_prefetch_mc):
                            raise _InstallCancelled()

                    # Publish progress into the shared view as well as honoring
                    # cancel: a click waiting on the lock paints from it.
                    view = _prefetch_view.setdefault(version_id, {})
                    view.clear()

                    def _note_status(text):
                        _guard()
                        view["status"] = text

                    def _note_progress(value):
                        _guard()
                        view["value"] = value

                    def _note_max(value):
                        _guard()
                        view["max"] = value

                    core.install_version(
                        version_id,
                        progress_cb=_note_progress,
                        status_cb=_note_status,
                        max_cb=_note_max,
                        cancel_event=cancel,
                        explicit_java=bool(cfg.get("java_path")),
                    )
                    state["installed"].add(version_id)
                    _rescan_installed()  # the new instance must show up in the row
                    # Phase 7: an OS toast, because this install is INVISIBLE -
                    # it runs in the background while the user browses, and
                    # without this the only evidence it ever happened is the
                    # hero button quietly changing from DOWNLOAD to PLAY.
                    # Best-effort by construction (see cubeon/osnotify.py).
                    try:
                        from cubeon import osnotify
                        osnotify.install_finished("instance", version_id, cfg=cfg)
                    except Exception:
                        pass
                    try:
                        # The version is on disk now, so the hero button must
                        # stop saying DOWNLOAD. page.update() alone repaints
                        # the old label - the mode has to be recomputed.
                        # Never steal the button from an install in flight -
                        # it is the cancel affordance then (clicks route by
                        # installing_version, so a PLAY paint here would lie).
                        if (version_dropdown.value == version_id
                                and not state.get("installing_version")):
                            _sync_play_button()
                        page.update()
                    except Exception:
                        pass
            except Exception:
                _prefetched.discard(version_id)  # allow a retry

        threading.Thread(target=_work, name="version-prefetch", daemon=True).start()

    def on_version_selected():
        """
        Called when the user selects a version from the dropdown.
        It checks if the version is installed, and if it's complete or incomplete.
        Then it updates the play button mode accordingly.
        """
        picker.sync_label()   # the compact button mirrors the real dropdown
        version_id = version_dropdown.value
        state["selected_version"] = version_id  # keep Mods/Servers tabs in sync with the dropdown
        # A pending loader install is armed against one specific version. If
        # the user switches versions, that arm no longer applies - clear it so
        # lock_loader_to_installed / the Play button don't advertise installing
        # Fabric (etc.) onto whatever version is now selected.
        if (state.get("pending_loader_install") or {}).get("version_id") != version_id:
            state["pending_loader_install"] = None
        # Separate "clean" numeric version for anything that keys off a mods
        # profile folder. version_id is the raw launch id and for
        # TLauncher/manually-installed instances that's frequently something
        # like "1.20.1-forge-47.2.0" rather than a bare "1.20.1" - using it
        # directly as a profile key silently pointed the Mods tab and
        # sync_mods_to_game() at an empty folder that nothing else ever
        # wrote to, which is why installed mods didn't show up or apply.
        state["selected_mc_version"] = core.extract_mc_version(version_id) if version_id else None
        # Rename/Delete only apply to a version that's actually installed
        # (an online-only entry has nothing on disk to manage yet).
        _sync_instance_actions(version_id)
        refresh_mods_list()
        refresh_browse_for_new_profile()
        refresh_loader_support(version_id)
        refresh_server_status_panel()
        update_pack_badge()
        update_hero()               # hero title/meta follow the selection
        if active_tab["value"] in {"server_console", "server_plugins", "server_settings"}:
            refresh_server_tab()
        meta = state["installed_meta"].get(version_id)
        if meta and meta.get("incomplete"):
            # The version exists but is missing files - show error and disable play
            version_issue_text.value = meta.get("issue", "This install is missing files.")
            version_issue_text.visible = True
            set_button_mode("incomplete")
        elif version_id and version_id in state["installed"]:
            # Installed and complete - ready to play, unless a loader install
            # is armed for this exact version (pending), in which case Play
            # must advertise the install it's about to perform.
            version_issue_text.visible = False
            pending = state.get("pending_loader_install") or {}
            if pending.get("version_id") == version_id and pending.get("loader"):
                set_button_mode("install_loader")
            else:
                set_button_mode("play")
        else:
            # Not installed - offer to download, and quietly start the
            # download in the background so Play is instant when clicked.
            version_issue_text.visible = False
            if version_id:
                set_button_mode("download")
                prefetch_version(version_id)
            else:
                # No instance at all ("No versions installed yet"): there is
                # nothing to download, so keep the neutral PLAY the empty
                # startup state mounts. on_play_click is already a no-op with
                # no selection.
                set_button_mode("play")
        # Mirror a live game: re-selecting the version that is currently
        # running must show QUIT GAME, not PLAY (the old code happily
        # offered a second launch of the same instance). One in-process dict
        # read - no psutil, no disk - so it adds nothing to the selection path.
        # The `version_id and` guard is LOAD-BEARING: with nothing installed
        # the dropdown value is None and state["running_version"] is None too,
        # so a bare == matched None == None and painted QUIT GAME out of
        # nowhere - most visibly right after changing the mod loader, which
        # re-runs this whole selection path (on_loader_toggle_change).
        if version_id and state.get("running_version") == version_id:
            set_button_mode("running")
        # The button IS the cancel affordance while an install is in flight
        # (even for a different version - the click routes by installing_
        # version, so a repainted PLAY here would click as CANCEL and lie).
        # Keep the honest state until the worker's own repaint.
        if state.get("installing_version"):
            set_button_mode("busy")

        # Fix any existing mod problems for this profile in the background now,
        # rather than waiting for the launch-time pass (which is filesystem-only
        # for speed). Best-effort and off the critical path.
        _proactive_mod_repair(version_id)

    def refresh_version_list(online=False):
        """
        Populates the version dropdown with available versions.

        If online=False (default): shows only locally installed versions.
        If online=True: fetches the full list from Mojang (may take a moment).

        This function is called at startup, when the user clicks "Browse online versions",
        or when the "Show snapshots" checkbox changes.
        """
        # First, get the currently installed versions (might have changed since last time)
        installed = core.get_installed_versions()
        state["installed"] = {v["id"] for v in installed}
        state["installed_meta"] = {v["id"]: v for v in installed}
        _refresh_pack_index()  # keep the version+loader -> pack-name map current

        if not online:
            # Offline mode: only installed versions. Legacy (below 1.20)
            # entries stay hidden until the user opts in via the Legacy
            # button - same rule as the online list.
            _labels = cfg.get("version_labels") or {}
            options = []
            entries = []
            for v in installed:
                vid = v["id"]
                if not state.get("legacy_ok") and _is_legacy_version(vid):
                    continue
                # The dropdown option keeps the plain "name ⚠/●" text (other
                # code mirrors it onto the button label); the picker gets the
                # richer descriptor it groups and tags rows with.
                info = instance_info.describe(vid, v, _labels.get(vid), with_mods=False)
                mark = "⚠" if info["incomplete"] else "●"
                options.append(ft.dropdown.Option(key=vid, text=f"{info['display_name']}  {mark}"))
                entries.append({
                    "id": vid, "text": info["display_name"], "installed": True,
                    "loader": info["loader"], "loader_label": info["loader_label"],
                    "incomplete": info["incomplete"], "type": "", "release_time": None,
                })
            version_dropdown.options = options
            picker.set_source(entries, online=False)
            legacy_note.visible = state.get("legacy_ok", False)

            # Select the first option or the previously selected version
            if options:
                if state["selected_version"] and any(o.key == state["selected_version"] for o in options):
                    version_dropdown.value = state["selected_version"]
                else:
                    version_dropdown.value = options[0].key
                on_version_selected()
            else:
                version_dropdown.value = None
                version_dropdown.hint_text = "No versions installed yet"
                # Nothing is selectable, so there is no instance - clear the
                # stale selection in state too. It was primed from
                # config["last_version"] at startup, and leaving it set points
                # the Mods tab / sync at the OLD version's profile folder
                # (whose mods are still on disk), so it would show "X installed"
                # and mark browse rows as already downloaded with no instance
                # actually selected.
                state["selected_version"] = None
                state["selected_mc_version"] = None
                # Everything that drew the version that just went away has to be
                # reset too - this branch is reached when the LAST installed
                # instance is deleted, and it used to only redraw the mods /
                # hero parts. The compact Game-version button kept reading
                # "1.21.11  ●" after that version was gone (it mirrors the
                # dropdown, and nothing re-labelled it here), the rename/delete
                # pair stayed lit and clickable, and a pack badge / issue note
                # belonging to the deleted install could stay on screen.
                picker.sync_label()
                _sync_instance_actions(None)
                version_issue_text.visible = False
                update_pack_badge()
                refresh_mods_list()
                refresh_browse_for_new_profile()
                update_hero()
            page.update()
            return

        # Online mode: fetch versions from Mojang
        set_status("Checking for versions", busy=True)
        try:
            versions = core.get_available_versions(include_snapshots=show_snapshots.value)
        except Exception:
            # If network fails, show the offline notice
            picker.set_offline()
            set_status("Offline")
            page.update()
            return

        # Build options: show installed versions with a "●" marker. Legacy
        # (below 1.20) entries are skipped unless the user opted in. The
        # picker additionally gets the loader / snapshot / release-date tags.
        _labels = cfg.get("version_labels") or {}
        options = []
        entries = []
        for v in versions:
            vid = v["id"]
            if not state.get("legacy_ok") and _is_legacy_version(vid):
                continue
            is_installed = vid in state["installed"]
            tag = "  ●" if is_installed else ""
            # A renamed instance keeps its nickname in the online list too, so
            # it reads the same in both places. Installed entries also fall
            # back to the friendly display name ("1.21.11 (Fabric)") instead
            # of the raw launch id.
            label = _labels.get(vid) if is_installed else None
            if not label and is_installed:
                label = (state.get("installed_meta") or {}).get(vid, {}).get("display_name")
            options.append(ft.dropdown.Option(key=vid, text=f"{label or vid}{tag}"))
            info = instance_info.describe(vid, v, _labels.get(vid), with_mods=False)
            entries.append({
                "id": vid, "text": label or vid, "installed": is_installed,
                "loader": info["loader"], "loader_label": info["loader_label"],
                "incomplete": info["incomplete"], "type": v.get("type") or "",
                "release_time": v.get("releaseTime"),
            })
        version_dropdown.options = options
        try:
            latest = core.get_latest_release()
        except Exception:
            latest = None
        picker.set_source(entries, online=True, latest=latest)
        legacy_note.visible = state.get("legacy_ok", False)

        # Set the dropdown value to either the previously selected, the latest release, or the first
        if state["selected_version"] and any(o.key == state["selected_version"] for o in options):
            version_dropdown.value = state["selected_version"]
        elif options:
            try:
                latest = core.get_latest_release()
                version_dropdown.value = latest if any(o.key == latest for o in options) else options[0].key
            except Exception:
                version_dropdown.value = options[0].key
        on_version_selected()
        set_status("Ready")
        page.update()

    def set_status(text, busy=False):
        """Updates the status text and dot in the sidebar's brand block.

        The dot colour is derived from the text rather than passed in, because
        every failure path already calls set_status("Crashed") / ("Error") and
        none of them knew to ask for a different colour - so a crashed launcher
        showed the word CRASHED next to the same healthy green dot as READY.
        Deriving it means the indicator can't disagree with the label.
        """
        label = text.upper()
        status_text.value = label
        if label in ("CRASHED", "ERROR"):
            status_dot.bgcolor = DANGER
        elif busy:
            status_dot.bgcolor = ACCENT_DIM
        else:
            status_dot.bgcolor = ACCENT
        # Two tiny controls in the sidebar's brand block; repaint just them.
        thread_safe_ui.refresh(status_text)
        thread_safe_ui.refresh(status_dot)

    def on_cancel_install():
        """Requests cancellation of the install the main button (in CANCEL
        mode) refers to.

        This only flips the flag - the installing worker notices it between
        download steps AND mid-file (versions.install_version patches mll's
        downloader with a per-chunk check when a cancel event is armed), so
        the request lands within a second or two instead of at the next file
        boundary. Launching is deliberately NOT cancellable; by then the flag
        is disarmed and the button is in the honest 'launching' state.
        """
        vid = state.get("installing_version")
        ev = _install_cancels.get(vid) if vid else None
        if ev is None:
            return
        ev.set()
        # The button is the cancel affordance: flip it to a disabled
        # "CANCELLING..." so a second click can't re-arm; the worker repaints
        # the honest mode once the abort lands.
        set_button_mode("cancelling")
        progress_label.value = "Cancelling..."
        thread_safe_ui.refresh(progress_row)
        thread_safe_ui.refresh(progress_bar)

    def _quit_running_game():
        """Ends the live game from the QUIT GAME button.

        The watchdog's terminate() is graceful first (SIGTERM, SIGKILL after
        2s) and identity-checked, so it can never hit the wrong process. The
        call blocks for up to ~4s, so it runs on a daemon thread; the normal
        on_exit path repaints the button when the game is actually down. If
        termination is refused (stale record), the button self-heals instead
        of pretending.
        """
        try:
            from cubeon import watchdog as _watchdog
            rec = _watchdog.stale_session()
        except Exception:
            rec = None
        if rec is None:
            _reconcile_running_button()
            return
        set_button_mode("ending")
        set_status("Stopping", busy=True)
        page.update()

        def _work():
            try:
                stopped = _watchdog.terminate(rec["pid"], rec.get("session_id"))
            except Exception:
                stopped = False
            if not stopped:
                # The game died between the probe and the terminate (or the
                # record went stale): on_exit won't fire for it, so heal.
                _reconcile_running_button()

        threading.Thread(target=_work, daemon=True, name="quit-game").start()

    def _begin_install_and_launch(version_id, username, ensure_java_major=None):
        """Paints the busy state and hands off to the install worker.

        Split out of on_play_click so the Java prompt can run FIRST and still
        end up in exactly this state once the user answers - otherwise the
        button would paint "busy" for a question the user has not been asked
        yet, and declining would leave it stuck on a spinner.

        `ensure_java_major` makes the worker install a managed runtime before
        anything else; None means Java is already known to be fine.
        """
        # Claim the install slot for this version before painting anything
        # busy. This is the single funnel for both ways in - a direct click
        # and the Java prompt's "Install Java" answer - so a second press for
        # the SAME version lands here too: the button can repaint itself
        # enabled out from under a click (a prefetch finishing, or
        # on_version_selected firing from the picker, a toggle, a rename, a
        # delete or a modpack handoff), and without this the second press
        # starts a second worker that races the first on the install lock,
        # double-downloads, and repaints over the first one's progress.
        #
        # Different versions are deliberately NOT refused: they are separate
        # folders and the install lock already serialises the disk work. This
        # only refuses the exact same instance twice, and it claims under the
        # launch lock so two clicks in the same instant cannot both win.
        with _launch_state_lock:
            if state.get("installing_version") == version_id:
                _show_snack("That version is already installing", duration=4000)
                return
            # A pack install (Modpacks tab / Import) is writing this version
            # right now. This is the second way in - on_play_click checks it
            # too, but the Java prompt calls this function directly, so the
            # guard has to live here as well (and under the same lock as the
            # claim, so the two can't interleave).
            _pack_name = None
            try:
                _pack_name = core.pack_install_for(
                    core.extract_mc_version(version_id))
            except Exception:
                pass
            if _pack_name:
                _show_snack(f"{_pack_name} is still installing - wait for it "
                            "to finish, then press Play", duration=5000)
                return
            state["installing_version"] = version_id

        # Update UI to "busy" state. progress_label is reset explicitly: it may
        # still be holding the previous launch's crash message, and leaving a
        # stale "Crashed: ..." line under a new progress bar reads as though the
        # new attempt failed instantly.
        set_button_mode("busy")
        progress_bar.visible = True
        # Reset the bar itself, not just its label. It carries state from the
        # previous run (the last launch ended on value=None, the indeterminate
        # "running" pulse) and its `data` still holds that run's phase maximum.
        # Start indeterminate on purpose: "Preparing" may involve no measurable
        # work at all - an already-installed version reports no progress. A
        # determinate bar pinned at 0% through that reads as frozen; the pulse
        # says "working", and the first real progress_cb makes it determinate.
        # A click that has to wait for a background prefetch gets there the same
        # way - see _adopt_prefetch, which paints that prefetch's own progress
        # instead of leaving the pulse up for the whole download.
        progress_bar.value = None
        progress_bar.data = 1
        progress_label.value = "Preparing"
        progress_label.visible = True
        progress_spinner.visible = True
        set_status("Preparing", busy=True)
        page.update()

        # Start the installation/launch in a background thread. If the thread
        # cannot even be created, release the claim made above: the worker's
        # finally is what normally clears it, and it will never run here, which
        # would otherwise leave that version permanently un-launchable.
        try:
            threading.Thread(
                target=lambda: do_install_and_launch(version_id, username,
                                                     ensure_java_major),
                daemon=True).start()
        except Exception:
            if state.get("installing_version") == version_id:
                state["installing_version"] = None
            raise

    def _prompt_for_java(version_id, username, mc_version, jstatus):
        """Asks whether Cubeon may download the Java this version needs.

        Three answers, and each one must leave the launcher in a sane state:
        Install goes ahead with the runtime fetched first, Not now cancels the
        whole install (the user did not ask to install Minecraft, so installing
        it anyway and then failing on Java would be worse), and a dismissed
        dialog is treated exactly like Not now - an unanswered question is a
        "no", never an implicit consent to a 50 MB download.
        """
        required = jstatus.get("required") or 17
        found = jstatus.get("found")
        if found:
            why = (f"This version needs Java {required} or newer, and the only "
                   f"Java on this computer is {found}.")
        else:
            why = (f"This version needs Java {required} or newer, and no Java "
                   f"was found on this computer.")
        approx = "50-100 MB" if required >= 17 else "around 40 MB"
        body = (f"{why}\n\n"
                f"Cubeon can download a Java {required} runtime from Eclipse "
                f"Adoptium ({approx}) and keep it alongside the launcher. It "
                f"won't touch any Java you already have installed.")

        def _install(dlg):
            _close_dialog(dlg=dlg)
            _begin_install_and_launch(version_id, username,
                                      ensure_java_major=required)

        def _not_now(dlg):
            _close_dialog(dlg=dlg)
            set_button_mode("play" if version_id in state["installed"]
                            else "download")
            set_status("Ready")
            page.update()

        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Text("Java isn't installed", color=TEXT,
                          weight=ft.FontWeight.W_800),
            content=ft.Container(
                content=ft.Text(body, size=13, color=TEXT),
                width=400,
            ),
            actions=[
                ft.TextButton("Not now", on_click=lambda e: _not_now(dlg)),
                ft.TextButton(f"Install Java {required}", on_click=lambda e: _install(dlg),
                              style=ft.ButtonStyle(color=ACCENT)),
            ],
        )
        _open_dialog(dlg)

    def on_play_click():
        """
        This is called when the user clicks the main play/download button.
        It validates the username, saves config, and then starts the installation/launch process
        in a background thread so the UI stays responsive.
        """
        # Validate username
        username = username_field.value.strip()
        ok, err = core.validate_username(username)
        if not ok:
            username_field.error_text = err
            page.update()
            return
        username_field.error_text = None

        version_id = version_dropdown.value
        if not version_id:
            return

        # A pack install (Modpacks tab / Settings > Import) is writing this
        # version's folder and its (mc, loader) profile right now. Its disk
        # state only LOOKS complete - the base version and loader land first,
        # the mods come after - so launching here is the reported "it said
        # installed while it was still installing mods, and that broke
        # everything". Refuse, and repaint the button to say so rather than
        # leaving a PLAY that silently does nothing.
        _installing_pack = None
        try:
            _installing_pack = core.pack_install_for(
                core.extract_mc_version(version_id))
        except Exception:
            pass
        if _installing_pack:
            _sync_play_button()
            _show_snack(f"{_installing_pack} is still installing - wait for "
                        "it to finish, then press Play", duration=5000)
            return

        # Bulletproof double-launch guard. The button's "running" paint can in
        # principle be stale for a beat (a background repaint racing this
        # click), so the click itself re-verifies the claim against the
        # watchdog before committing. Exceptions count as "maybe alive" -
        # refusing a launch is recoverable, launching a second copy of the
        # same instance (profile lock contention, double playtime) is not.
        if state.get("running_version") == version_id:
            try:
                from cubeon import watchdog as _watchdog
                live = _watchdog.stale_session()
            except Exception:
                live = {"session_id": "?"}   # cannot prove it dead: stay safe
            if live is not None:
                set_button_mode("running")
                _show_snack("That version is already running", duration=4000)
                return
            state["running_version"] = None  # stale claim - clear and proceed

        # Save config with current username and last selected version
        cfg["username"] = username
        cfg["last_version"] = version_id
        core.save_config(cfg)
        if friends_service is not None:
            try:
                friends_service.reconcile_username()
            except Exception:
                logging.getLogger(__name__).debug("username reconciliation failed", exc_info=True)

        # --- Java check, BEFORE anything is painted busy --------------------
        # Minecraft needs a Java new enough for the SELECTED version, and
        # before this existed a machine with no JDK just got an error banner
        # and a link to read. So ask instead, and offer to fetch a Temurin
        # runtime. The check is skipped when the game is already installed and
        # we are only relaunching it: that machine demonstrably ran this
        # version before, so re-asking on every launch would be noise.
        #
        # `version_id` can be a loader row ("fabric-loader-0.19.5-26.1.2"), so
        # the numeric base is what the Java requirement is keyed off - same
        # reason the loader checks further down use it.
        mc_version = core.extract_mc_version(version_id)
        try:
            needs_install = version_id not in state["installed"]
        except Exception:
            needs_install = True
        # A pending loader install (e.g. adding Fabric to an already-installed
        # vanilla version) still needs the Java check: the loader installer
        # runs even though the base Minecraft version is present.
        if not needs_install:
            pending = state.get("pending_loader_install") or {}
            if pending.get("version_id") == version_id and pending.get("loader"):
                needs_install = True
        if needs_install:
            try:
                jstatus = core.jre.java_status(mc_version, cfg.get("java_path"))
            except Exception:
                jstatus = {"ok": True, "required": 0, "found": None}
            if not jstatus.get("ok") and jstatus.get("required"):
                _prompt_for_java(version_id, username, mc_version, jstatus)
                return  # the dialog's action calls back into the install
        _begin_install_and_launch(version_id, username)

    _launch_state_lock = threading.RLock()

    def _reset_button_after_worker(version_id):
        """Repaint the main button after an install worker ends in cancel or
        error. The old code always painted for the worker's version - but the
        user may have selected a DIFFERENT version mid-install (the guard in
        on_version_selected keeps the button honest meanwhile), and then the
        reset painted a mode for a version nobody is looking at. Selection
        unchanged: the simple recompute; changed: the full selection refresh
        (which also re-arms prefetch for the newly-selected version)."""
        if version_dropdown.value == version_id:
            _sync_play_button()
        else:
            try:
                on_version_selected()
            except Exception:
                _sync_play_button()

    def do_install_and_launch(version_id, username, ensure_java_major=None):
        """
        This runs in a background thread. It handles:
          - Installing a managed Java runtime first, if the user agreed to one
          - Installing the version if not already present
          - Installing Fabric if selected and supported
          - Launching the game with the chosen version
        It uses callbacks to update the UI (progress, status).
        """
        # Cancellation wiring, set up BEFORE the try so the finally block can
        # always clean it up. Registered on state so on_cancel_install finds
        # the right version even if the user changes the dropdown mid-install.
        cancel = _cancel_event(version_id)
        cancel.clear()
        was_installed = version_id in state["installed"]
        cancellable = {"on": True}  # disarmed once the launch phase begins

        def _check_cancel():
            """Abort the install at the next step boundary. During the install
            itself the progress callbacks call this per file, which is what
            actually stops mll; the explicit calls below cover the step
            boundaries where no callback would otherwise fire."""
            if cancellable["on"] and cancel.is_set():
                raise _InstallCancelled()

        state["installing_version"] = version_id

        try:
            target_version = version_id

            # Define callback functions that update UI elements from the
            # background thread. Progress repaints are control-level:
            # install progress arrives once per FILE (a version is ~4000
            # files), so each repaint diffs just the progress row instead
            # of the full mounted tree. They are rate-limited as well: 4000
            # marshalled repaints is enough queued work to keep the window
            # from answering input for the whole download (the "it freezes"
            # report), and a progress bar cannot be read at 4000 fps anyway.
            # Anything that ends a phase paints with force=True, so the last
            # state is never the one that got coalesced away.
            _REPAINT_INTERVAL = 0.1  # seconds; 10 fps
            _repaint_at = {"t": 0.0}

            def _paint_progress(force=False):
                now = time.monotonic()
                if not force and now - _repaint_at["t"] < _REPAINT_INTERVAL:
                    return
                _repaint_at["t"] = now
                thread_safe_ui.refresh(progress_row)
                thread_safe_ui.refresh(progress_bar)

            # "Time left" is measured, never assumed: the estimator watches how
            # fast the fraction has actually moved (see cubeon/eta.py). The
            # label is always rebuilt from the LAST raw status text, so the
            # per-file name mll sends stays visible beside the estimate.
            _eta = cubeon_eta.EtaEstimator()
            _status_line = {"text": "Preparing"}

            def _status_text():
                eta = _eta.text()
                return f"{_status_line['text']} · {eta}" if eta else _status_line["text"]

            def status_cb(text):
                _check_cancel()
                # Third-party status text can carry an object repr (requests
                # does - see cubeon/status_text.py); it never reaches the UI.
                _status_line["text"] = cubeon_status.human(text)
                progress_label.value = _status_text()
                _paint_progress()

            def progress_cb(val):
                _check_cancel()
                mx = progress_bar.data or 1
                # Clamped: each install phase reports its own max, and a phase
                # that emits progress before its setMax lands would otherwise
                # divide by the previous phase's (smaller) max and overshoot.
                progress_bar.value = min(1.0, max(0.0, val / mx)) if mx else 0
                _eta.note(val, mx)
                progress_label.value = _status_text()
                _paint_progress()

            def max_cb(val):
                _check_cancel()
                progress_bar.data = val
                _paint_progress()

            # --- The Java the user agreed to have fetched ---------------------
            # Runs before anything else so the failure mode is the honest one
            # ("couldn't install Java") rather than a half-downloaded Minecraft
            # followed by a WinError 2 from the loader installer. The progress
            # callbacks are reused, so this shows up in the same bar with the
            # same cancel button. A JreError carries a message written for the
            # user, so it is re-raised as-is and lands in the normal error path
            # with that text instead of a traceback.
            if ensure_java_major:
                _check_cancel()
                progress_bar.data = 1
                core.jre.install_jre(
                    int(ensure_java_major),
                    progress_cb=lambda done, total: progress_cb(
                        done / (total or 1)),
                    status_cb=status_cb)

            def _adopt_prefetch(version_id):
                """Paint the waiting click with the prefetch's own progress.

                The version selected before the click is prefetched in the
                background, invisibly, and both share one install lock - so a
                click can wait seconds to minutes on that lock. Painting from
                the prefetch's live view means the user watches the download
                they are actually waiting for instead of a frozen "Preparing".
                """
                view = _prefetch_view.get(version_id)
                if not view:
                    return
                if view.get("status"):
                    _status_line["text"] = cubeon_status.human(view["status"])
                mx = view.get("max")
                if mx:
                    val = view.get("value") or 0
                    progress_bar.data = mx
                    progress_bar.value = min(1.0, max(0.0, val / mx))
                    _eta.note(val, mx)
                progress_label.value = _status_text()
                _paint_progress()

            # If the version is not installed, install it. The per-version
            # lock also covers the background prefetch (on_version_selected),
            # so a click during a prefetch waits for it instead of racing it,
            # and an install completed by the prefetch is not repeated.
            _check_cancel()
            if version_id not in state["installed"]:
                lock = _install_lock(version_id)
                # Acquire in short slices rather than blocking outright: while
                # the prefetch holds the lock this loop keeps the progress row
                # showing ITS progress (see _adopt_prefetch), and it keeps
                # honoring Cancel - the prefetch checks the same flag, so
                # cancelling here stops whichever of the two is running.
                while not lock.acquire(timeout=0.25):
                    _check_cancel()
                    _adopt_prefetch(version_id)
                try:
                    # Re-check after the lock: a cancel can land while waiting
                    # behind the background prefetch (which honors the same
                    # flag), and starting a fresh install then would ignore it.
                    _check_cancel()
                    if version_id not in state["installed"]:
                        core.install_version(version_id, progress_cb, status_cb,
                                             max_cb, cancel_event=cancel,
                                             # The launch passes cfg's java path
                                             # as executablePath, so mll's own
                                             # runtime copy is dead weight -
                                             # see versions.install_version.
                                             explicit_java=bool(
                                                 cfg.get("java_path")))
                        state["installed"].add(version_id)
                        # Publish it immediately: a fresh install is a new
                        # instance, and "Jump back in" is keyed on the full
                        # metadata map, not on state["installed"].
                        _rescan_installed()
                        _paint_progress(force=True)  # never coalesce the end
                finally:
                    lock.release()

            # If a mod loader is selected, install it if supported - but only
            # if it isn't already installed for this version, otherwise every
            # single launch re-downloads/reinstalls it for no reason.
            loader_id = state["mod_loader"]
            launch_mc = core.extract_mc_version(version_id)
            try:
                for pack in core.list_installed_modpacks():
                    if pack.get("version_id") == version_id:
                        launch_mc = pack.get("mc_version") or launch_mc
                        loader_id = pack.get("loader") or loader_id
                        break
            except Exception:
                pass
            # Loader support is a property of the *Minecraft version*, not of
            # the raw launch id. version_id can be a loader install row like
            # "fabric-loader-0.19.5-26.1.2" (or a TLauncher-style renamed id);
            # asking is_loader_supported/find_installed_loader_version with
            # that raw id would report "unsupported" and point the existing-
            # install lookup at an empty profile even though the loader is
            # right there. The numeric base is what those checks mean.
            base_version = core.extract_mc_version(version_id)
            if loader_id != "vanilla":
                loader_label = core.SUPPORTED_LOADERS.get(loader_id, loader_id)
                if core.is_loader_supported(loader_id, base_version):
                    existing_id = core.find_installed_loader_version(state["installed"], loader_id, base_version)
                    if existing_id:
                        target_version = existing_id
                    else:
                        status_cb(f"Installing {loader_label} loader")
                        target_version = core.install_mod_loader(loader_id, base_version, progress_cb, status_cb, max_cb)
                        state["installed"].add(target_version)
                        # The loader install is its own launchable instance row
                        # (e.g. "fabric-loader-0.19.5-26.1.2") - without this it
                        # only appeared after some later full list refresh.
                        _rescan_installed()
                        _paint_progress(force=True)  # never coalesce the end
                else:
                    status_cb(f"{loader_label} unsupported for this version, using vanilla")

            # The loader install is done (or was skipped) - the pending arm
            # that put Play into "INSTALL FABRIC & PLAY" mode has served its
            # purpose and must be cleared, so the button returns to a normal
            # "play"/"running" state and lock_loader_to_installed doesn't
            # keep re-arming it on the next version re-selection.
            if (state.get("pending_loader_install") or {}).get("version_id") == version_id:
                state["pending_loader_install"] = None

            # Now that the version (and loader, if any) is installed, the
            # loader choice is locked in - refresh the cached support map and
            # re-lock the switcher so it can't be changed after the fact.
            # (No coalesced-progress flush needed anymore: the progress
            # callbacks repaint their own controls directly.)
            support = dict(loader_check_cache.get(version_id, {}))
            for lid in LOADER_IDS:
                if lid == "vanilla":
                    continue
                installed_now = bool(core.find_installed_loader_version(state["installed"], lid, base_version))
                supported_prev = support.get(lid, (True, False))[0]
                support[lid] = (supported_prev, installed_now)
            loader_check_cache[version_id] = support
            if version_dropdown.value == version_id:
                lock_loader_to_installed(version_id, support)
                style_loader_segments(support)

            # Everything installable is on disk now. From here on the work is
            # local setup + spawning the game, which cannot be interrupted
            # safely - disarm cancellation and flip the button to the honest
            # disabled state so it stops promising an abort that is no longer
            # possible.
            cancellable["on"] = False
            state["installing_version"] = None
            set_button_mode("launching")

            # Launch the game
            progress_label.value = "Launching"
            page.update()
            set_status("Running", busy=True)

            # Has the game already exited? launch_game() is non-blocking, so a
            # process that dies immediately reaches on_exit() while this thread
            # is still mid-launch. Both writers check this under the lock so the
            # last word about the run belongs to whichever event really happened
            # last - see the guarded block after launch_game() returns.
            exited = {"done": False}
            _exit_lock = threading.Lock()

            # Define callback when game process exits - this is the only place
            # that should put the button back to "play", since launch_game()
            # itself is non-blocking (it spawns the process and returns right
            # away on a background watcher thread).
            def _show_crash_report(reason, lines, session_id):
                """Surface the game's own log instead of one line of text.

                The full log is on disk (cubeon/launch.py tails it); read the
                tail of it so the dialog can show what the game actually said.
                Bounded read: a mod that spams a stack trace every tick can
                produce megabytes, and the dialog only renders ~60k chars.
                """
                try:
                    from cubeon.paths import CUBEON_HOME
                except Exception:
                    CUBEON_HOME = None
                log_text = "\n".join(lines or [])
                log_path = None
                if CUBEON_HOME and session_id:
                    candidate = os.path.join(
                        CUBEON_HOME, f"game-{session_id}.log")
                    if os.path.isfile(candidate):
                        log_path = candidate
                        try:
                            size = os.path.getsize(candidate)
                            with open(candidate, "r", encoding="utf-8",
                                      errors="replace") as fh:
                                if size > 300_000:
                                    fh.seek(size - 300_000)
                                    fh.readline()  # drop the partial line
                                full = fh.read()
                            if full.strip():
                                log_text = full
                        except OSError:
                            pass  # keep the in-memory tail
                label = f"Minecraft {core.extract_mc_version(version_id) or version_id}"

                def _open():
                    show_crash_dialog(
                        page, reason=reason, log_text=log_text,
                        version_label=label, log_path=log_path,
                        show_snack=_show_snack)

                # Mounting a dialog from the watcher thread must happen on the
                # UI loop; fall back to a direct call on harnesses without one
                # (show_crash_dialog swallows its own failures).
                async def _open_async():
                    _open()

                try:
                    page.run_task(_open_async)
                except Exception:
                    _open()

            def on_exit(code, lines=None, session_id=None):
                # Mark the game as finished BEFORE touching any UI, so the
                # post-launch "Minecraft is running" block below can see that
                # this launch is already over and leave the result alone.
                with _exit_lock:
                    exited["done"] = True
                # Credit THIS session's playtime (clamped inside). Session-keyed:
                # an older game's exit must not end a newer one's record.
                try:
                    core.milestones_end_play_session(session_id=session_id)
                except Exception:
                    pass  # cosmetic - never let it break the exit path
                # A newer game may still be live (overlapping launches): only
                # the latest live session may clear the shared running state.
                try:
                    from cubeon import watchdog as _watchdog
                    latest = _watchdog.stale_session()
                except Exception:
                    latest = None
                if latest is not None and latest.get("session_id") != session_id:
                    return
                # Bulletproof: everything below is UI + presence teardown. A
                # failure here must never strand the running claim - the
                # fallback guarantees the state is cleared and the button
                # returns to its honest mode even if the pretty path dies.
                def _exit_fallback_reset():
                    try:
                        with _launch_state_lock:
                            state["running_version"] = None
                        if version_dropdown.value == version_id:
                            _sync_play_button()
                        page.update()
                    except Exception:
                        pass  # window gone or repaint machinery dead - nothing left

                try:
                    # Tell friends this user stopped playing (presence -> online).
                    with _launch_state_lock:
                        if friends_service is not None:
                            friends_service.set_version(None)
                        # Discord presence: back to just "in the launcher".
                        _rpc.set_activity(details="Cubeon", state="In the launcher",
                                          large_image=_discord_img, large_text=_discord_img_text)
                        state["running_version"] = None  # version is safe to delete again
                        progress_bar.visible = False
                        crashed = bool(code)
                    if crashed:
                        # A non-zero exit is a crash or a refused launch. Saying so
                        # matters: the old code hid this entirely, so a failed
                        # launch looked identical to a normal quit and the user was
                        # left staring at a Play button with no idea what happened.
                        reason = _explain_exit(code, lines)
                        progress_label.value = reason
                        progress_label.visible = True
                        progress_spinner.visible = False
                        set_status("Crashed")
                        # The one-line reason stays under the button; the log
                        # and a way to ask for help open on top (2026-10-23).
                        try:
                            _show_crash_report(reason, lines, session_id)
                        except Exception:
                            pass  # the reason line is still there
                    else:
                        progress_bar.visible = False
                        progress_label.visible = False
                        progress_spinner.visible = False
                        set_status("Ready")
                    # Put the play button back: on_exit is the ONLY place that
                    # owns the "running" mode, but it never reset it - a closed
                    # game left the button stuck on GAME RUNNING... until some
                    # unrelated selection forced a recompute. Reset only when
                    # the user is still looking at this launch's version
                    # (otherwise the selection handler owns the button).
                    if version_dropdown.value == version_id:
                        _sync_play_button()
                    page.update()
                except Exception:
                    # Never let a repaint/presence hiccup strand the "running"
                    # claim or the button: the fallback is the minimal honest
                    # reset and is itself exception-proof.
                    traceback.print_exc()
                    _exit_fallback_reset()

            # launch_game() returns as soon as the process has *started* - it
            # does not wait for the game to close. So the button must switch
            # to "running" right here, not after this call returns.
            # mc_version/loader are passed explicitly (not left to default)
            # so the right profile's mods actually get synced before this
            # launch - see cubeon/launch.py and cubeon/mods.py for why that
            # used to silently fail. cfg is passed so the launch also
            # installs CustomSkinLoader and re-mirrors the active skin under
            # the current username - without that mod, offline players see
            # Steve/Alex and no Cubeon cape (see cubeon/csl.py).
            # Switch to "running" BEFORE spawning, not after. on_exit fires from
            # a watcher thread, and a game that dies immediately (bad Java, mod
            # conflict) can reach it before this line would otherwise run -
            # which would overwrite the crash message with a "running" state.
            # NOTE: we do NOT set the "Minecraft is running" text here on
            # purpose - launch_game() below calls status_cb (e.g. "Installing
            # CustomSkinLoader...") while it sets up, and its status calls
            # would overwrite it. The running indicator is set only after
            # launch_game() returns, once the game process has actually
            # started (see below).
            with _exit_lock:
                if exited["done"]:
                    return
            set_button_mode("running")
            state["running_version"] = version_id  # block deleting it mid-game
            page.update()

            # Belt-and-braces liveness watch: on_exit() is the normal path,
            # but a single callback must never be a single point of failure -
            # if its thread dies, or the game is killed in a way the watcher
            # misses, the button would sit on GAME RUNNING... forever. This
            # daemon polls the watchdog every 5s ONLY while this launch's
            # claim is live (a psutil probe, no disk, no network) and
            # self-heals via the same reconcile the Play tab uses if the
            # game dies without on_exit ever clearing the claim. At most one
            # such thread exists per process.
            if not any(t.name == "running-liveness" and t.is_alive()
                       for t in threading.enumerate()):
                def _liveness_watch():
                    while True:
                        time.sleep(5)
                        claimed = state.get("running_version")
                        if claimed != version_id:
                            return  # on_exit handled this launch (or a newer one)
                        try:
                            from cubeon import watchdog as _watchdog
                            if _watchdog.stale_session() is not None:
                                # Still alive - keep the claim visible. This
                                # loop is the only watcher while the game runs,
                                # so it is also the last line of defence against
                                # a stray repaint leaving PLAY on screen (the
                                # 2026-10-16 "game is running but it shows the
                                # play button" report): clicking that button
                                # QUITS the live game, not starts one.
                                if play_button_text.value != "QUIT GAME":
                                    set_button_mode("running")
                                continue  # still alive
                        except Exception:
                            return  # watchdog unavailable: on_exit stays the owner
                        _reconcile_running_button()
                        return
                threading.Thread(target=_liveness_watch,
                                 name="running-liveness", daemon=True).start()

            # The pack lookup above may have changed the resolved loader; carry
            # that SAME loader into launch_game so a vanilla fallback or pack
            # override cannot stage one loader and launch with another.
            launch_loader = loader_id

            # Watch the live game log for an offline-session kick. Cubeon hands
            # the game accessToken "0", so any server that actually verifies the
            # session kicks the player. Two shapes show up in the log:
            #   * the vanilla key `disconnect.loginFailedInfo.invalidSession`
            #     (client gave up, or a strict online-mode server), and
            #   * Velocity's own "You are not logged into your Minecraft
            #     account..." (a cracked-enabled proxy that forwarded the login
            #     but rejected it server-side after hasJoined returned 204).
            # Both are meaningless to a player who thinks the server allows
            # cracked. Translate into a plain-English toast that names the
            # server AND - the confusing case - says when the username itself is
            # a real Minecraft account (cracked servers block premium names to
            # stop impersonation, so the fix is a different username). The
            # premium check is a quick Mojang lookup run on a daemon thread so
            # the log tail never blocks; _show_snack is thread-safe. Server name
            # comes from the game's own most-recent "Connecting to X" line.
            _session_watch = {"server": None, "shown": False}

            def _explain_offline_kick(server, name):
                def _worker():
                    try:
                        from cubeon import remotes as _remotes
                        premium = _remotes.resolve_ign(name) is not None
                    except Exception:  # noqa: BLE001 - network/parse: unknown
                        premium = None
                    if premium:
                        msg = (f"{server} treats your username '{name}' as "
                               f"premium-only, because '{name}' is a real "
                               f"Minecraft account name. Cracked-enabled "
                               f"servers still block premium names to stop "
                               f"impersonation. In the launcher, switch to a "
                               f"non-premium username (Account) and rejoin.")
                    elif premium is False:
                        msg = (f"{server} requires a premium Minecraft "
                               f"account, or wants cracked players to "
                               f"register first. Cubeon is offline-only, so a "
                               f"strict online-mode server can't be joined - "
                               f"but cracked-enabled servers (like mazer.club) "
                               f"work fine.")
                    else:
                        msg = (f"{server} rejected the offline login. Cubeon "
                               f"is offline-only, so it can't join strict "
                               f"online-mode servers; cracked-enabled servers "
                               f"may work.")
                    _show_snack(msg, duration=13000)

                threading.Thread(target=_worker, daemon=True).start()

            def _game_log_cb(line):
                if "Connecting to " in line:
                    try:
                        _session_watch["server"] = \
                            line.split("Connecting to ", 1)[1].split(",")[0].strip()
                    except Exception:
                        pass
                kicked = ("loginFailedInfo.invalidSession" in line
                          or "not logged into your Minecraft account" in line)
                if kicked and not _session_watch["shown"]:
                    _session_watch["shown"] = True
                    server = _session_watch["server"] or "That server"
                    _explain_offline_kick(server, username)

            game = core.launch_game(
                target_version, username, cfg["ram_mb"], cfg["width"], cfg["height"],
                cfg.get("java_path"), on_exit=on_exit,
                # Clean numeric version, not the raw launch id - this is the
                # same profile key the Mods tab and modpack installer use.
                # Passing version_id here (as before) meant a TLauncher-style
                # id like "1.20.1-forge-47.2.0" synced from a different,
                # always-empty profile every launch, so mods never applied.
                mc_version=launch_mc, loader=launch_loader,
                cfg=cfg, status_cb=status_cb, log_cb=_game_log_cb,
            )

            # Remember this launch for the Play tab's "last played" label (see
            # cubeon/instances.py). Best-effort - never blocks the launch.
            instance_info.mark_played(version_id)

            # Session id from the watchdog record (mirrored on the Popen
            # object): on_exit compares against the live session so an older
            # game's exit cannot clear a newer game's presence/indicator.
            session_id = getattr(game, "session_id", None)

            # Broadcast presence to friends: "playing <version>". Safe no-op if
            # the user hasn't claimed a Cubeon name / isn't connected. version_id
            # is the human MC version (not the loader-specific target id), which
            # is what a friend wants to see in their list. Guarded like the
            # on_exit path above: public builds have no Friends service.
            with _launch_state_lock:
                if friends_service is not None and not exited["done"]:
                    friends_service.set_version(version_id)

            # Discord Rich Presence: show the game as being played, with an
            # elapsed timer. Best-effort - no-op if Discord isn't running.
            with _launch_state_lock:
                if not exited["done"]:
                    _rpc.set_activity(
                        details="Cubeon",
                        state=f"Playing Minecraft {core.extract_mc_version(version_id) or version_id}",
                        start=int(time.time() * 1000),
                        large_image=_discord_img,
                        large_text=_discord_img_text,
                    )

            # launch_game() has returned, so the game process is up and any
            # setup (incl. CustomSkinLoader install) is done. The loading bar
            # is now gone - only a quiet status line remains, until on_exit
            # clears it when the game closes.
            #
            # Guarded: if the game already exited (a crash-on-start - bad Java,
            # a mod conflict, a broken pack), on_exit has ALREADY written the
            # real reason. Overwriting it with "Minecraft is running" would
            # strand a wrong status forever and destroy the only explanation
            # the user ever gets.
            with _exit_lock:
                if not exited["done"]:
                    progress_bar.visible = False  # loading is over - no more bar
                    progress_bar.value = 0
                    progress_label.value = "Minecraft is running - this launcher stays open"
                    progress_label.visible = True
                    progress_spinner.visible = False
                    page.update()

        except Exception as ex:
            # A cancel arrives here as a generic error: install_version wraps
            # whatever its callbacks raise, so the event - not the exception
            # type - is the source of truth for "user chose to stop". A cancel
            # is a choice, not a failure, so it gets its own message and no
            # scary traceback.
            if cancel.is_set():
                # Remove a version folder this attempt created from scratch so
                # it can't resurface as a puzzling "(incomplete)" entry. A
                # pre-existing install is left alone - install_version already
                # dropped only the jars it clobbered.
                if not was_installed:
                    try:
                        core.delete_version(version_id)
                    except Exception:
                        pass  # never created, or already gone - nothing to undo
                progress_label.value = "Install cancelled"
                progress_label.visible = True
                progress_spinner.visible = False
                progress_bar.visible = False
                _reset_button_after_worker(version_id)
                set_status("Ready")
                page.update()
                return
            # If anything goes wrong, show error and reset button. The message
            # has to stay on screen - this is the only report the user ever
            # gets, and it used to be lost whenever the repaint didn't land.
            if isinstance(ex, FileNotFoundError):
                # The mod-loader installers are the one place we execute
                # another program. A Java that was moved/removed between the
                # resolution in mod_loaders.loader_java() and the exec used to
                # land here as the bare "FileNotFoundError: [WinError 2] The
                # system cannot find the file specified" (the 2026-09-24
                # report), which says nothing about what to do.
                progress_label.value = (
                    "Couldn't start the mod loader installer - the Java it "
                    "needs has moved or been removed. Reinstall Java, or point "
                    "Cubeon at it in Settings, then try again.")[:180]
            else:
                progress_label.value = f"Error: {type(ex).__name__}: {ex}"[:180]
            progress_label.visible = True
            progress_spinner.visible = False
            progress_bar.visible = False
            _reset_button_after_worker(version_id)
            set_status("Error")
            page.update()
            traceback.print_exc()  # full trace to the console for bug reports
        finally:
            # Whatever happened - success, crash, cancel, or the early return
            # after a launch that died instantly - no install is in flight
            # any more. The button's paint is owned by the paths above (the
            # cancel/error resets, or the running state on success).
            cancellable["on"] = False
            if state.get("installing_version") == version_id:
                state["installing_version"] = None

    # --- Server status panel - the right column below the grass block was
    # dead space, and "is my server running" is a genuinely useful thing to
    # surface right here: it's the same version selector Console uses
    # (state["selected_version"]), so this reads live server state without
    # needing its own separate polling loop. ---

    server_status_dot = ft.Container(width=9, height=9, border_radius=RADIUS, bgcolor=TEXT_DIM)
    server_status_text = ft.Text("No server for this version", size=13, color=TEXT_DIM,
                                 font_family=FONT_MONO, weight=ft.FontWeight.W_600)
    server_status_open_console = ft.Container(
        content=ft.Text("Open Console →", size=12, color=ACCENT, weight=ft.FontWeight.W_600),
        ink=False, visible=False,
        on_click=lambda e: switch_tab("server_console"),
    )

    def refresh_server_status_panel():
        version_id = state.get("selected_version")
        try:
            running = bool(version_id) and core.is_server_running(version_id)
        except Exception:
            running = False
        if not version_id:
            server_status_dot.bgcolor = TEXT_DIM
            server_status_text.value = "Pick a version to see server status"
            server_status_open_console.visible = False
        elif running:
            server_status_dot.bgcolor = ACCENT
            server_status_text.value = "Server running for this version"
            server_status_open_console.visible = True
        else:
            server_status_dot.bgcolor = TEXT_DIM
            server_status_text.value = "Server not running"
            server_status_open_console.visible = True
        page.update()

    server_status_panel = ft.Container(
        content=ft.Column(
            [
                section_label("Server status"),
                ft.Row([server_status_dot, server_status_text], spacing=8,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                server_status_open_console,
            ],
            spacing=10,
        ),
        bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS, padding=20, width=280,
    )

    # -----------------------------------------------------------------
    # MANAGE INSTANCE - rename (nickname) or delete the selected version.
    # "Instance" here == an installed Minecraft version (the dropdown above).
    # Rename stores a per-id label in config (version_labels) instead of
    # renaming the on-disk folder, so it can never break a launch or the
    # loader detection that parses the id. Delete removes only that version's
    # own folder; shared mod profiles, skins, and worlds are left alone.
    # -----------------------------------------------------------------
    def _open_dialog(dlg):
        # Shared cross-Flet dialog plumbing (see cubeon/dialogs.py) - Flet
        # 0.86 exposes show_dialog()/pop_dialog(), not the older open/close.
        cubeon_dialogs.open_dialog(page, dlg)

    def _close_dialog(dlg):
        cubeon_dialogs.close_dialog(page, dlg)

    def _show_snack(msg, *, duration=4000, action=None, action_label=None):
        """Toast popup used everywhere (thread-safe, never raises).

        text_color is TEXT, never ON_ACCENT: ON_ACCENT is designed to sit on
        the bright ACCENT fill, and on the dark SURFACE_HI toast its contrast
        was 1.06:1 - invisible text, the exact bug that motivates the WCAG-AA
        checks in tools/test_seasonal.py. TEXT on SURFACE_HI is 15.7:1.
        """
        cubeon_dialogs.show_snack(page, msg, duration=duration, action=action,
                                  action_label=action_label,
                                  bgcolor=SURFACE_HI, text_color=TEXT)

    def _selected_installed_id():
        """The selected version id iff it's actually installed, else None -
        renaming or deleting an online-only entry that isn't downloaded yet
        is meaningless."""
        vid = version_dropdown.value
        return vid if (vid and vid in state["installed"]) else None

    def on_rename_instance(e=None, vid=None):
        vid = vid or _selected_installed_id()
        if not vid:
            set_status("Install this version before renaming it")
            return
        meta = state["installed_meta"].get(vid, {})
        default_name = meta.get("display_name", vid)
        current = (cfg.get("version_labels") or {}).get(vid) or default_name
        name_field = ft.TextField(
            value=current, label="Instance name", autofocus=True,
            border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
            label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI,
            border_radius=RADIUS, max_length=48,
        )

        def save(e=None):
            new_name = (name_field.value or "").strip()
            labels = dict(cfg.get("version_labels") or {})
            if new_name and new_name != default_name:
                labels[vid] = new_name
            else:
                # Blank, or the same as the default, clears any custom label.
                labels.pop(vid, None)
            cfg["version_labels"] = labels
            core.save_config(cfg)
            _close_dialog(dlg)
            refresh_version_list()
            # The rename may have come from a row of the open Instances
            # manager - re-draw its rows so the new name shows there too.
            instances_manager.refresh()
            set_status("Instance renamed")

        name_field.on_submit = save
        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Text("Rename instance", color=TEXT, weight=ft.FontWeight.W_800),
            content=ft.Container(
                content=ft.Column(
                    [
                        name_field,
                        ft.Text("Just a nickname - leave blank to reset it.",
                                size=12, color=TEXT_DIM),
                    ],
                    spacing=8, tight=True,
                ),
                width=380,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: _close_dialog(dlg)),
                ft.TextButton("Save", on_click=save, style=ft.ButtonStyle(color=ACCENT)),
            ],
        )
        _open_dialog(dlg)

    def on_delete_instance(e=None, vid=None):
        vid = vid or _selected_installed_id()
        if not vid:
            set_status("Install this version before deleting it")
            return
        if state.get("running_version") == vid:
            set_status("Can't delete a version while it's running")
            return
        meta = state["installed_meta"].get(vid, {})
        label = (cfg.get("version_labels") or {}).get(vid) or meta.get("display_name", vid)

        def confirm(e=None):
            _close_dialog(dlg)
            try:
                core.delete_version(vid)
            except ValueError as ve:
                set_status(str(ve))
                return
            # If this version was a modpack install, stop the Modpacks tab
            # from still listing it as installed. Only removes the small
            # tracking record (_modpack.json) - the mod profile itself
            # (mod_profiles/<mc_version>-<loader>) is left alone, same as
            # delete_version() already leaves it alone, since mod profiles
            # are shared/reusable across reinstalls by design. Without
            # this, "Installed packs" kept showing packs whose version had
            # already been deleted here, with a Play button that led
            # nowhere useful.
            try:
                core.forget_modpack_for_version(vid)
                refresh_installed_packs()
            except Exception:
                pass
            # Forget any nickname and stop last_version/selection pointing at it.
            labels = dict(cfg.get("version_labels") or {})
            if labels.pop(vid, None) is not None:
                cfg["version_labels"] = labels
            if cfg.get("last_version") == vid:
                cfg["last_version"] = None
            if state.get("selected_version") == vid:
                state["selected_version"] = None
            core.save_config(cfg)
            refresh_version_list()
            # A delete performed from a row of the open Instances manager: the
            # dialog stays mounted across the action, so re-draw its rows or it
            # keeps listing the instance that was just deleted.
            instances_manager.refresh()
            set_status(f"Deleted {label}")

        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Text("Delete instance?", color=TEXT, weight=ft.FontWeight.W_800),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(f"This permanently deletes '{label}' and its files from "
                                "your versions folder.", size=13, color=TEXT),
                        ft.Text("Your mods, skins, and worlds are not affected.",
                                size=12, color=TEXT_DIM),
                    ],
                    spacing=8, tight=True,
                ),
                width=380,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: _close_dialog(dlg)),
                ft.TextButton("Delete", on_click=confirm, style=ft.ButtonStyle(color=DANGER)),
            ],
        )
        _open_dialog(dlg)

    rename_instance_btn = ft.IconButton(
        ft.Icons.DRIVE_FILE_RENAME_OUTLINE_ROUNDED, icon_color=TEXT_DIM, icon_size=18,
        tooltip="Rename instance", on_click=on_rename_instance,
        style=ft.ButtonStyle(color={ft.ControlState.HOVERED: TEXT}),
    )
    delete_instance_btn = ft.IconButton(
        ft.Icons.DELETE_OUTLINE_ROUNDED,
        # A quiet red (not the full DANGER flood) so the destructive affordance
        # reads as destructive before anyone hovers it.
        icon_color=ft.Colors.with_opacity(0.7, DANGER),
        icon_size=18,
        tooltip="Delete instance", on_click=on_delete_instance,
        # Secondary until the pointer is on it - the destructive action then
        # reads red without the row looking alarming at rest.
        style=ft.ButtonStyle(color={ft.ControlState.HOVERED: DANGER}),
    )

    def _sync_instance_actions(version_id):
        """Rename/Delete only apply to a version that's actually installed.

        ONE owner for the pair's enabled/dimmed state, because both the
        selection path (on_version_selected) and the "nothing is installed
        anymore" path (refresh_version_list's empty branch) have to paint it -
        and the empty path is exactly the DELETE-last-instance case, where the
        buttons used to stay lit after their target was gone.
        """
        installed_sel = bool(version_id and version_id in state["installed"])
        rename_instance_btn.disabled = not installed_sel
        delete_instance_btn.disabled = not installed_sel
        rename_instance_btn.opacity = 1 if installed_sel else 0.4
        delete_instance_btn.opacity = 1 if installed_sel else 0.4

    # "Folder" on the hero card: the answer to "where is my Minecraft folder"
    # without leaving the Play tab (2026-10-23). Opens the game directory
    # (not the Cubeon data dir) and always stays clickable - it is harmless
    # when nothing is installed and is still the right folder to tidy up.
    def _open_minecraft_folder(e=None):
        from cubeon.paths import MINECRAFT_DIR
        _open_any_folder(MINECRAFT_DIR, "Minecraft folder")

    folder_instance_btn = theme.attach_hover(
        ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED, size=15,
                            color=TEXT_DIM),
                    ft.Text("Folder", size=12, color=TEXT_DIM),
                ],
                spacing=6,
            ),
            bgcolor=ft.Colors.with_opacity(0.35, SURFACE_HI),
            border=ft.border.Border.all(1, CARD_BORDER),
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=10, vertical=6),
            tooltip=("Open the Minecraft game folder "
                     "(versions, mods, saves, screenshots)"),
        ),
        ft.Colors.with_opacity(0.35, SURFACE_HI), ROW_HOVER,
    )
    folder_instance_btn.on_click = _open_minecraft_folder

    # -----------------------------------------------------------------
    # PLAY TAB LAYOUT
    #
    # Structure (top to bottom):
    #   PLAY title
    #   HERO PANEL  - the launcher proper: big instance title + meta line,
    #                 account/version controls side by side, loader switcher
    #                 left and a right-aligned PLAY button (~340px) so the
    #                 primary action has weight without becoming a runway.
    #   JUMP BACK IN / INSTALLED VERSIONS - real content under the hero so
    #                 the page doesn't end a third of the way down.
    # -----------------------------------------------------------------

    # Hero panel widgets -----------------------------------------------------
    hero_title = ft.Text("Minecraft", size=22, color=TEXT, font_family=FONT_DISPLAY)
    hero_version_text = ft.Text("", size=11, color=TEXT_FAINT, font_family=FONT_MONO)
    hero_loader_chip_text = ft.Text("Vanilla", size=10.5, color=ACCENT,
                                    weight=ft.FontWeight.W_700, font_family=FONT_MONO)
    hero_loader_chip = ft.Container(
        content=hero_loader_chip_text,
        bgcolor=ACCENT_TINT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=8, vertical=3),
    )

    # -----------------------------------------------------------------
    # VERSION ART - the Play tab's visual identity.
    #
    # version_art fetches each release's OFFICIAL Mojang key art (the same
    # launcher-content feed the real Minecraft Launcher uses), falling back to
    # the fan wiki only for versions Mojang's feed doesn't carry (pre-1.13
    # releases, week-numbered snapshots). ft.Image can't read an absolute path,
    # so cached art is fed back base64-encoded (see version_art.src). Until a
    # version has art, the bundled OG key art (titleimg.jpg) stands in, so the
    # page is never a blank box.
    #
    # The banner tracks the SELECTED version; the "Jump back in" cards give
    # each INSTALLED version its own art. Both download off the UI thread and
    # repaint via thread_safe_ui, and both guard against a late download
    # landing after the user already switched away.
    #
    # One fetch per version serves every interested control (_art_watchers), so
    # update_hero running on every selection change doesn't re-spawn the fetch.
    # -----------------------------------------------------------------
    # The version art IS the hero panel's background (2026-10-23): the old
    # layout kept it in a separate "spotlight" card under the launcher, which
    # read as a second, unrelated card. Now the selected version's official
    # key art fills the main card behind a scrim, so the panel has a visual
    # identity instead of a flat glass fill.
    hero_art = ft.Image(src="titleimg.jpg", fit=ft.BoxFit.COVER, expand=True)
    hero_art_scrim = ft.Container(
        left=0, top=0, right=0, bottom=0,
        # Dark at the bottom where the controls live, lighter at the top so
        # the art is still visible behind the instance header.
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_CENTER,
            end=ft.Alignment.BOTTOM_CENTER,
            colors=[
                ft.Colors.with_opacity(0.34, BG),
                ft.Colors.with_opacity(0.78, BG),
                ft.Colors.with_opacity(0.96, BG),
            ],
            stops=[0.0, 0.34, 1.0],
        ),
    )
    hero_art_layer = ft.Container(
        content=hero_art,
        left=0, top=0, right=0, bottom=0,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )
    _hero_art_uid = {"value": None}
    # Multiple controls can want the same version's art (the hero spotlight and
    # that version's card). Each registers a callback; one fetch serves them
    # all - a per-base "already requested" flag would leave the second caller
    # stuck on the placeholder forever.
    _art_watchers: dict = {}
    _art_inflight: set = set()

    def _request_art(base, apply_fn):
        """Ensure the best available art for `base` lands in `apply_fn(value)`
        (an ft.Image.src-safe base64 string, or None). Fires immediately when
        the official art is already cached; otherwise downloads off-thread and
        notifies every waiting caller when it lands."""
        if not base:
            return
        if version_art.has_official(base):
            apply_fn(version_art.src(base))
            return
        _art_watchers.setdefault(base, []).append(apply_fn)
        if base in _art_inflight:
            return
        _art_inflight.add(base)

        def _done(value):
            _art_inflight.discard(base)
            for fn in _art_watchers.pop(base, []):
                fn(value)

        version_art.prefetch(base, _done)

    def _refresh_hero_banner(version):
        base = core.extract_mc_version(version) or version
        _hero_art_uid["value"] = version

        cached = version_art.src(base) if base else None
        if hero_art.src != (cached or "titleimg.jpg"):
            hero_art.src = cached or "titleimg.jpg"
            thread_safe_ui.refresh(hero_art)
        uid = version

        def _ready(value):
            # A download that finished after the user switched versions is
            # stale - drop it rather than flash the wrong art.
            if uid != _hero_art_uid["value"]:
                return
            art = value or "titleimg.jpg"
            if hero_art.src != art:
                hero_art.src = art
                thread_safe_ui.refresh(hero_art)

        _request_art(base, _ready)

    # "Jump back in": one art card per installed version. The row lives in
    # ui/versions.py (InstanceCards) - it builds each card ONCE and afterwards
    # only restyles the selection / refreshes the (imageless) chip row, so Flet
    # never re-sends a card's base64 thumbnail payload on a selection change
    # (the invariant tools/test_version_art_cache.py pins).
    def _select_instance(version_id):
        if version_id not in state["installed"]:
            return
        _ensure_version_option(version_id)
        version_dropdown.value = version_id
        on_version_selected()

    instance_cards = InstanceCards(
        page,
        get_metas=lambda: state.get("installed_meta") or {},
        get_labels=lambda: cfg.get("version_labels") or {},
        get_selected=lambda: version_dropdown.value,
        on_select=_select_instance,
        art_src=version_art.src,
        request_art=_request_art,
    )
    instance_cards_row = instance_cards.row
    instance_cards_empty = instance_cards.empty

    def _play_instance(version_id):
        """Play one specific installed instance (from the Instances manager)."""
        if version_id not in state["installed"]:
            set_status("That version isn't installed")
            return
        if state.get("installing_version"):
            set_status("Wait for the current install to finish")
            return
        if core.pack_install_for(core.extract_mc_version(version_id)):
            # A pack install is still writing this very instance (base
            # version + its profile). Launching now is the half-installed
            # "everything broke" path - refuse until it finishes.
            set_status("Wait for this instance to finish installing")
            return
        if state.get("running_version"):
            set_status("A game is already running")
            return
        _ensure_version_option(version_id)
        version_dropdown.value = version_id
        on_version_selected()
        on_play_click()

    # Repaint the big button the moment a pack install claims or releases an
    # instance (Modpacks tab / Import). Without this a disabled "INSTALLING..."
    # could outlive a cancelled install, or a finished one would keep saying it
    # until some unrelated repaint. The handler is thread-safe (see
    # thread_safe_ui) and reads live state, so it is correct from any caller.
    try:
        core.add_pack_install_listener(_sync_play_button)
    except Exception:
        logging.getLogger(__name__).warning("pack install listener not wired",
                                            exc_info=True)

    # Instances manager - one dialog to see and manage every install (see
    # ui/versions.py). It re-reads the live installed set on each open.
    instances_manager = InstancesManager(
        page,
        get_instances=lambda: instance_info.list_installed(
            list((state.get("installed_meta") or {}).values()),
            cfg.get("version_labels") or {}),
        get_selected=lambda: version_dropdown.value,
        on_play=_play_instance,
        on_rename=lambda vid: on_rename_instance(vid=vid),
        on_delete=lambda vid: on_delete_instance(vid=vid),
    )

    def update_hero():
        """Syncs the hero's big title / meta chips with the current version +
        loader selection. Called wherever those change (version pick, loader
        lock-in after install detection, manual loader switch)."""
        vid = version_dropdown.value
        meta = state["installed_meta"].get(vid) if vid else None
        custom = (cfg.get("version_labels") or {}).get(vid) if vid else None
        display = (meta or {}).get("display_name")
        # A renamed/customised instance leads with its own name; otherwise the
        # title is the game itself: "Minecraft 1.21.11".
        if custom or (display and display != vid):
            hero_title.value = custom or display
        elif vid:
            hero_title.value = f"Minecraft {core.extract_mc_version(vid) or vid}"
        else:
            hero_title.value = "Minecraft"
        hero_version_text.value = vid or "no version selected"
        hero_loader_chip_text.value = core.SUPPORTED_LOADERS.get(
            LOADER_IDS[loader_toggle.selected_index], "Vanilla")
        _refresh_hero_banner(vid)
        instance_cards.rebuild()

    # Now assemble the actual Play tab UI. Hierarchy is deliberate:
    #   PAGE HEADING  -> INSTANCE CARD
    #     INSTANCE HEADER  (emblem, name, meta, rename/delete)
    #     CONFIGURATION    (game version + account, then mod loader)
    #     ACTION FOOTER    (PLAY)
    # The card is compact and top-aligned; it is never stretched to fill the
    # viewport just because there is room below it.

    play_tab = ft.Column(
        [
            ft.Column(
                [
                    ft.Text("Play", size=24, color=TEXT, font_family=FONT_DISPLAY),
                    ft.Text("Launch Minecraft your way.", size=13, color=TEXT_DIM),
                ],
                spacing=2,
                tight=True,
            ),
            ft.Container(height=16),  # heading -> card

            # --- HERO PANEL: the instance card ---
            # The selected version's art is the card's BACKGROUND (see
            # hero_art above), under a bottom-heavy scrim so every control and
            # label stays readable. The old version-spotlight card below the
            # hero is gone - the art now belongs to the main card itself.
            ft.Container(
                content=ft.Stack(
                    [
                        hero_art_layer,
                        hero_art_scrim,
                        ft.Container(
                            content=ft.Column(
                                [
                                    # INSTANCE HEADER: emblem, instance name + meta line,
                                    # contextual rename/delete.
                                    ft.Row(
                                        [
                                            # Rotating grass-block GIF (assets/grass_block.gif),
                                            # generated in-house - the instance's emblem.
                                            ft.Image(src="grass_block.gif", width=56, height=56, fit=ft.BoxFit.CONTAIN),
                                            ft.Container(width=12),
                                            ft.Column(
                                                [
                                                    ft.Row(
                                                        [
                                                            hero_title,
                                                            ft.Container(width=4),
                                                            ft.Container(expand=True),
                                                            folder_instance_btn,
                                                            rename_instance_btn,
                                                            delete_instance_btn,
                                                        ],
                                                        spacing=4,
                                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                                    ),
                                                    ft.Row(
                                                        [
                                                            hero_loader_chip,
                                                            pack_name_badge,
                                                            hero_version_text,
                                                        ],
                                                        spacing=10,
                                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                                    ),
                                                    version_issue_text,
                                                ],
                                                spacing=6,
                                                expand=True,
                                            ),
                                        ],
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),

                                    ft.Container(height=16),

                                    # CONFIGURATION: two related fields on one row - game
                                    # version (a dropdown) and account (an account field) -
                                    # then the mod loader choice below them.
                                    ft.Row(
                                        [
                                            ft.Column(
                                                [
                                                    section_label("Game version"),
                                                    ft.Container(height=6),
                                                    version_dropdown_button,
                                                ],
                                                spacing=0,
                                                expand=True,
                                            ),
                                            ft.Container(width=16),
                                            ft.Column(
                                                [
                                                    section_label("Account"),
                                                    ft.Container(height=6),
                                                    username_field,
                                                ],
                                                spacing=0,
                                                expand=True,
                                            ),
                                        ],
                                    ),
                                    ft.Container(height=14),
                                    ft.Column(
                                        [
                                            section_label("Mod loader"),
                                            ft.Container(height=6),
                                            loader_toggle,
                                            loader_status_text,
                                        ],
                                        spacing=0,
                                    ),

                                    ft.Container(height=18),

                                    # FPS BOOST: the toggle that actually helps. Sits in
                                    # the Play menu (not Settings) because it changes what
                                    # THIS launch looks and feels like, right next to the
                                    # loader choice it rides on. See the fps_boost_switch
                                    # builder above.
                                    ft.Row(
                                        [
                                            ft.Column(
                                                [
                                                    section_label("FPS boost"),
                                                    ft.Container(height=2),
                                                    ft.Text(
                                                        "Max FPS at launch. Off restores vanilla graphics "
                                                        "(fancy, smooth lighting, shadows) on the next launch.",
                                                        size=11, color=TEXT_DIM,
                                                    ),
                                                ],
                                                spacing=0,
                                                expand=True,
                                            ),
                                            fps_boost_switch,
                                        ],
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),

                                    ft.Container(height=18),

                                    # ACTION FOOTER: the primary PLAY action on the
                                    # right. No aura/glow behind it (user ask,
                                    # 2026-10-23): the seasonal accent made the
                                    # bloom read as a red halo around QUIT GAME.
                                    # The sheen stays INSIDE play_button (see its
                                    # creation) - as a sibling it absorbed every
                                    # real-window tap that followed a hover.
                                    ft.Row(
                                        [
                                            ft.Container(expand=True),
                                            ft.Container(width=280, content=play_button),
                                        ],
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),

                                    ft.Container(height=12),
                                    progress_row,
                                    progress_bar,
                                ],
                                spacing=0,
                            ),
                            padding=20,
                        ),
                    ],
                ),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                **glass_card(hero=True, padding=0),
            ),

            ft.Container(height=24),

            # JUMP BACK IN - one art-headed card per installed version, so
            # the page has real content under the hero instead of ending a
            # third of the way down. Clicking a card selects that instance.
            # (The old "Manage" button that sat here is gone - the instances
            # manager now opens from the version picker's manage link.)
            theme.section_label("Jump back in"),
            ft.Container(height=10),
            instance_cards_row,
            instance_cards_empty,
        ],
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
    )

    # -----------------------------------------------------------------
    # (The skin section now lives inside the Profile dialog - see the
    # "Signed in as" click target near the top of main(), which builds it
    # via build_skin_section() from skin_tab.py.)
    # -----------------------------------------------------------------

    # -----------------------------------------------------------------
    # MODS TAB - manage installed mods and browse/download new ones (see mods_tab.py)
    # -----------------------------------------------------------------
    # -----------------------------------------------------------------
    # MODS / MODPACKS / SERVERS - BUILT ON FIRST VISIT
    #
    # These three modules are 4,287 lines of control construction between
    # them, and building them here at startup made every launch pay for tabs
    # most sessions never open. server_tab's build even starts a watcher
    # thread that then polls is_server_running() every 2 seconds forever,
    # whether or not you ever host anything.
    #
    # Each tab is now an empty Container that goes into the tabs map right
    # away - so switch_tab, the layout and the nav are all unchanged - and
    # gets its real content the first time it is shown.
    #
    # The builders' refresh callbacks are wrapped so a call before the tab
    # exists is a no-op. That is correct rather than merely safe: building
    # the tab renders current data, so there is nothing an early refresh
    # could add.
    # -----------------------------------------------------------------
    _tab_cbs: dict = {}   # tab key -> the builder's callbacks, once built
    mods_tab = ft.Container(expand=True)
    modpacks_tab = ft.Container(expand=True)
    server_console_tab = ft.Container(expand=True)
    server_browse_tab = ft.Container(expand=True)
    server_plugins_tab = ft.Container(expand=True)
    server_settings_tab = ft.Container(expand=True)
    stats_tab_host = ft.Container(expand=True)
    chat_tab_host = ft.Container(expand=True)

    def _cb(key, name):
        """A builder callback that stays a no-op until its tab is built."""
        def call(*a, **k):
            cbs = _tab_cbs.get(key)
            if cbs:
                return cbs[name](*a, **k)
        return call

    refresh_mods_list = _cb("mods", "refresh")
    load_recommended_mods = _cb("mods", "recommend")
    refresh_browse_for_new_profile = _cb("mods", "browse")
    refresh_installed_packs = _cb("modpacks", "installed")
    load_popular_modpacks = _cb("modpacks", "popular")
    refresh_server_tab = _cb("server", "refresh")

    # Proactive, best-effort mod repair. When the user settles on an
    # (mc_version, loader) profile we run the FULL doctor in the background -
    # including the network-dependent dependency and loader/version passes the
    # launch-time check skips for speed - so leftover duplicate copies, missing
    # dependencies and version clashes are fixed before Play is ever clicked.
    # Once per profile per session; silent unless it actually changed
    # something. Never blocks or raises into the UI.
    _repair_state = {"done": set(), "lock": threading.Lock()}
    # Hard ceiling on how long the repair claim (see _fixing_selected) may keep
    # the Play button in "FIXING MODS...". The doctor's own calls are all
    # timeout-bounded, so this only ever fires if something truly wedges - and
    # then the button must come back rather than stay disabled forever.
    _REPAIR_CLAIM_MAX = 120.0

    def _proactive_mod_repair(version_id):
        if not version_id or state["mod_loader"] == "vanilla":
            return
        mc = state.get("selected_mc_version")
        loader = state["mod_loader"]
        if not mc or loader not in core.MOD_CAPABLE_LOADERS:
            return
        key = (mc, loader)
        if core.pack_install_for(mc):
            # A pack install owns this profile right now and is still writing
            # mods into it. Running the doctor here would race those downloads
            # (auto_fix can prune jars it can't verify yet). Skip WITHOUT
            # marking the profile done, so the repair still happens on the
            # next selection/launch after the install has finished.
            return
        with _repair_state["lock"]:
            if key in _repair_state["done"]:
                return
            _repair_state["done"].add(key)

        def worker():
            # Publish a busy claim for this profile while the doctor runs. The
            # big button reads it (see _fixing_selected / set_button_mode's
            # "working" mode) so it cannot claim PLAY while Cubeon is still
            # repairing mods - the user reported PLAY showing up during exactly
            # that phase (2026-10-16). Released by the finally, and by a timer,
            # so a wedged doctor can never leave the button stuck disabled.
            def _release_claim():
                try:
                    if state.get("fixing_mods") == version_id:
                        state["fixing_mods"] = None
                    _sync_play_button()
                except Exception:
                    logging.getLogger(__name__).warning("background worker error",
                                                        exc_info=True)

            state["fixing_mods"] = version_id
            _sync_play_button()
            guard = threading.Timer(_REPAIR_CLAIM_MAX, _release_claim)
            guard.daemon = True
            guard.start()
            try:
                # The full doctor: mods + resource packs + shaders + modpacks +
                # server plugins (cubeon/doctor.py). This runs after an install,
                # which is exactly when new content lands on disk and needs to
                # be verified against the versions that will read it.
                report = core.run_doctor(mc, loader, auto_fix=True,
                                         check_online=True)
            except Exception:
                return
            finally:
                guard.cancel()
                _release_claim()
            if not (report.get("fixed") or []):
                return
            fixed = len(report["fixed"])
            try:
                set_status(f"Fixed {fixed} mod problem(s)")
            except Exception:
                logging.getLogger(__name__).warning("background worker error", exc_info=True)
            refresh = (_tab_cbs.get("mods") or {}).get("refresh")
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    logging.getLogger(__name__).warning("background worker error", exc_info=True)

        threading.Thread(target=worker, name="mod-repair", daemon=True).start()

    def _build_mods_tab():
        content, refresh, recommend, browse = build_mods_tab(
            page, cfg, state, version_dropdown,
            section_label=section_label,
            **THEME,
        )
        mods_tab.content = content
        _tab_cbs["mods"] = {"refresh": refresh, "recommend": recommend,
                            "browse": browse}

    # -----------------------------------------------------------------
    # STATS TAB - one clean screen of counters (playtime, library,
    # cosmetics). Read-only scans of state that already exists; see
    # ui/stats_tab.py.
    # -----------------------------------------------------------------
    def _build_stats_tab():
        content, refresh = build_stats_tab(
            page, cfg, state,
            section_label=section_label,
            go_to_tab=switch_tab,
            **THEME,
        )
        stats_tab_host.content = content
        _tab_cbs["stats"] = {"refresh": refresh}

    # -----------------------------------------------------------------
    # CHAT TAB - the launcher's social surface: automatic Cubeon identity,
    # friend roster + requests, and encrypted DMs. Talks straight to the
    # process-scoped FriendsService (the same object the in-game mod reaches
    # through the local bridge); see ui/chat_tab.py. Built lazily so no poll
    # thread starts until the user opens the tab.
    # -----------------------------------------------------------------
    def _build_chat_tab():
        content, refresh = build_chat_tab(
            page, cfg, state, friends_service,
            section_label=section_label,
            **THEME,
        )
        chat_tab_host.content = content
        _tab_cbs["chat"] = {"refresh": refresh}
        # First run: the identity was just minted and startup deliberately
        # didn't connect yet. Opening Chat is the natural moment to bring the
        # connection up (and publish the E2EE key) so the roster populates.
        if (friends_client is not None and friends_client.is_available
                and not friends_client.is_connected):
            try:
                friends.ensure_identity()
                friends_client.connect()
            except Exception:
                traceback.print_exc()

    # -----------------------------------------------------------------
    # MODPACKS TAB - install a whole Modrinth .mrpack (version + loader +
    # mods + config) in one click (see modpacks_tab.py / cubeon/modpacks.py).
    # -----------------------------------------------------------------
    def go_to_pack(meta):
        """Handoff from the Modpacks tab: after a pack installs (or when the
        user taps an installed pack's Play), make it the active version on the
        Play tab and jump there.

        Once installed, a modpack is just a normal (mc_version, loader) install:
        its mods live in mod_profiles/<mc_version>-<loader> - the exact folder
        CustomSkinLoader is installed into and sync_mods_to_game copies from at
        launch. So we select the pack's NUMERIC mc_version (e.g. "1.20.1") and
        flip the loader toggle to the pack's loader, precisely as if the user
        had chosen them by hand. That makes the launch pass
        mc_version="1.20.1"/loader="fabric", so the pack's mods AND the skin/cape
        mod actually load, and the version reads as "1.20.1 (Fabric)" instead of
        a bare loader id.

        (The old code selected the launchable "fabric-loader-...-1.20.1" id, which
        launch then forwarded verbatim as the mc_version - pointing the sync and
        CSL install at an empty "fabric_loader_..." profile: no mods, no skin, and
        a "Fabric Loader" label instead of the pack's name.)"""
        refresh_version_list()
        mc = meta.get("mc_version")
        loader = meta.get("loader") or "vanilla"
        # Prime the loader BEFORE selecting the version: on_version_selected ->
        # refresh_loader_support -> lock_loader_to_installed reads
        # state["mod_loader"] and keeps it when installed, so a version carrying
        # more than one loader still locks to this pack's loader.
        if loader in LOADER_IDS:
            state["mod_loader"] = loader
            loader_toggle.selected_index = LOADER_IDS.index(loader)
        # Prefer the numeric MC version; fall back to the launchable id only if
        # the base version somehow isn't listed (e.g. user deleted it).
        target = mc if (mc and any(o.key == mc for o in (version_dropdown.options or []))) \
            else meta.get("version_id")
        if target and any(o.key == target for o in (version_dropdown.options or [])):
            version_dropdown.value = target
            state["selected_version"] = target
            on_version_selected()  # also derives/sets state["selected_mc_version"]
        switch_tab("play")
        page.update()

    def _build_modpacks_tab():
        content, installed, popular = build_modpacks_tab(
            page, cfg, state,
            section_label=section_label, go_to_pack=go_to_pack,
            **THEME,
        )
        modpacks_tab.content = content
        _tab_cbs["modpacks"] = {"installed": installed, "popular": popular}

    # -----------------------------------------------------------------
    # SERVERS GROUP - host a local server for the selected version.
    # Two sidebar sub-items (Console, Settings) sharing one backend module.
    # -----------------------------------------------------------------
    def _build_server_tab():
        console, settings, plugins, refresh = build_server_tab(
            page, cfg, state,
            section_label=section_label, pixel_divider=pixel_divider,
            **THEME,
        )

        def _join_server(host: str, port: int, name: str):
            """Browse's JOIN: launch the selected profile straight into a
            public server. The SAME path the friends flow uses
            (launch_game's --server/--port). No selected version = an
            honest snackbar, never a dead click.

            Runs on a WORKER thread, exactly like on_play_click and the
            friends launcher: launch_game resolves+installs assets before
            spawning, which is seconds of blocking network/disk - doing
            that on the UI thread froze the whole window (reported live
            2026-10-18 as "the play button isn't working")."""
            version_id = state.get("selected_version")
            if not version_id:
                _show_snack("Pick a Minecraft version on the Play tab first - "
                            "the server decides which one too.")
                return

            def worker():
                try:
                    # Through the core facade - NEVER a direct cubeon.launch
                    # import: the facade is what the test harness stubs, so a
                    # fuzzer-fired JOIN stays a recorded no-op instead of
                    # spawning a real Minecraft process.
                    mc_version = core.extract_mc_version(version_id)
                    loader = state.get("mod_loader") or "fabric"
                    username = cfg.get("username") or "Player"
                    core.launch_game(version_id, username,
                                     cfg.get("ram_mb", 4096),
                                     cfg.get("width", 1280),
                                     cfg.get("height", 720),
                                     cfg.get("java_path"), on_exit=None,
                                     mc_version=mc_version, loader=loader,
                                     cfg=cfg,
                                     server_address=host, server_port=port)
                    _show_snack(f"Launching Minecraft into {name} "
                                f"({host}:{port})…")
                except Exception as ex:
                    _show_snack(f"Couldn't launch into {name}: {ex}")

            threading.Thread(target=worker, daemon=True,
                             name="server-browse-join").start()

        browse_view, browse_refresh = build_server_browse_tab(
            page, cfg, state, join_game=_join_server, **THEME)
        server_console_tab.content = console
        server_browse_tab.content = browse_view
        server_settings_tab.content = settings
        server_plugins_tab.content = plugins
        _tab_cbs["server"] = {"refresh": refresh,
                              "browse_refresh": browse_refresh}

    _TAB_BUILDERS = {
        "mods": _build_mods_tab,
        "modpacks": _build_modpacks_tab,
        "server": _build_server_tab,       # one build fills all three screens
        "stats": _build_stats_tab,
        "chat": _build_chat_tab,
    }

    def _ensure_tab(key):
        """Builds a lazy tab the first time it's shown. A build that fails
        leaves the tab unbuilt so the next visit retries, and must never
        take navigation down with it - an empty panel beats a dead sidebar."""
        if key in _tab_cbs or key not in _TAB_BUILDERS:
            return
        try:
            _TAB_BUILDERS[key]()
        except Exception:
            traceback.print_exc()

    # -----------------------------------------------------------------
    # FRIENDS - unique Cubeon name, presence (online + which version they're
    # playing), friend requests, and P2P worlds.
    #
    # There is no Friends *tab*: the UI is the in-game "Cubeon Friends" mod
    # (see mod/), which draws Minecraft's own widgets and talks to the launcher
    # over the localhost bridge. Friends belong in the game's pause menu, where
    # you actually are when you want to invite someone - not behind an
    # alt-tab. FriendsService owns everything the tab used to: the realtime
    # client's callbacks, the P2P state machine, and the bridge endpoints. It's
    # created here and lives for the whole process so presence keeps flowing no
    # matter which tab is showing. See cubeon/friends_service.py.
    # -----------------------------------------------------------------
    # Development builds run the Friends bridge/service. Public builds omit
    # it entirely, so they make no Friends network connection or localhost
    # bridge and remain a normal launcher while the feature is in development.
    #
    # Process-scoped (like the Discord presence above): the process can be
    # relaunched in place (Settings > Restart, GPU-crash recovery), so
    # several sessions can exist in ONE process over its life. The
    # service must not be rebuilt per session - FriendsClient.on() has no
    # unregister, so a second instance would double every event, and a
    # second local_api server would steal the mod's token file. Instead the
    # first session's instances are kept; only their cfg/state references
    # are re-pointed at the current session's dicts (both are plain dicts
    # the service reads live).
    if friends_enabled():
        if _session_runtime["friends_service"] is None:
            _session_runtime["friends_client"] = friends.FriendsClient()
            _session_runtime["friends_service"] = FriendsService(
                cfg, state, _session_runtime["friends_client"])
            _session_runtime["friends_service"].start()
        else:
            _svc = _session_runtime["friends_service"]
            _svc.cfg = cfg
            _svc.state = state
            _svc._save_config = lambda: core.save_config(cfg)
        friends_client = _session_runtime["friends_client"]
        friends_service = _session_runtime["friends_service"]
        if friends_service is not None:
            try:
                friends_service.reconcile_username()
            except Exception:
                logging.getLogger(__name__).debug("username reconciliation failed", exc_info=True)
    else:
        friends_client = None
        friends_service = None

    # -----------------------------------------------------------------
    # SETTINGS TAB
    # -----------------------------------------------------------------

    # RAM slider - bounded by *this machine's* actual RAM instead of a
    # hardcoded 16384 MB ceiling. That hardcoded max was the bug: a machine
    # with only 8 GB total could still drag the slider up to 16 GB and hand
    # Java an -Xmx bigger than physically available RAM, which reliably
    # crashes Minecraft (or thrashes the whole OS) instead of failing with
    # a clear message.
    #
    # Fix:
    #   - max = detected system RAM (so you can never select more than you
    #     actually have)
    #   - default / recommended point = half of system RAM, shown as a
    #     labelled tick and used to seed new configs
    #   - going above the half point still works (some people do want to
    #     push higher) but shows an explicit warning instead of pretending
    #     it's a normal position on the slider
    system_ram_mb = core.get_system_ram_mb()
    recommended_ram_mb = core.recommended_max_ram_mb(system_ram_mb)
    # Keep a sane minimum (Minecraft won't launch well under ~1GB) and never
    # let max fall below min, e.g. a very low-RAM host.
    ram_min_mb = 1024
    ram_max_mb = max(system_ram_mb, ram_min_mb + 512)
    # If a previously-saved value is now above what this machine actually
    # has (config copied from a beefier PC, RAM physically removed, etc.)
    # clamp it down rather than silently keeping an impossible selection.
    if cfg["ram_mb"] > ram_max_mb:
        cfg["ram_mb"] = recommended_ram_mb
    if cfg["ram_mb"] < ram_min_mb:
        cfg["ram_mb"] = ram_min_mb
    _ram_divisions = max(1, min(32, (ram_max_mb - ram_min_mb) // 256 or 1))

    # The old version drew a static green-to-red gradient bar UNDER a fully
    # transparent Slider. That's what made it look broken: the gradient's red
    # end always sat at the right edge of the track regardless of the actual
    # value, so a slider sitting at its minimum still showed mostly
    # yellow/red - visually implying "almost maxed out" while the label right
    # below it said the opposite. The transparent thumb was also nearly
    # invisible against the dark track, so there was nothing to actually look
    # at to see where the slider currently was.
    #
    # Fixed by letting Slider draw its own active/inactive track (so the
    # colored portion genuinely stops at the thumb) and giving the thumb a
    # solid, visible color. The active color still shifts green -> red, but
    # now the red kicks in only once you cross the recommended half-point,
    # not just from raw slider position.
    def _ram_color(value: float) -> str:
        """Green up to the recommended half-point, then blends toward red
        as you push further above it, reaching full red at the max."""
        if value <= recommended_ram_mb:
            return ACCENT
        span = max(ram_max_mb - recommended_ram_mb, 1)
        frac = (value - recommended_ram_mb) / span
        frac = max(0.0, min(1.0, frac))
        lo = tuple(int(ACCENT[i:i + 2], 16) for i in (1, 3, 5))
        hi = tuple(int(DANGER[i:i + 2], 16) for i in (1, 3, 5))
        mixed = tuple(round(lo[c] + (hi[c] - lo[c]) * frac) for c in range(3))
        return "#{:02x}{:02x}{:02x}".format(*mixed)

    ram_slider = ft.Slider(
        min=ram_min_mb, max=ram_max_mb, divisions=_ram_divisions, value=cfg["ram_mb"],
        active_color=_ram_color(cfg["ram_mb"]), inactive_color=SURFACE_HI,
        thumb_color=_ram_color(cfg["ram_mb"]),
        label="{value} MB",
    )
    ram_range_row = ft.Row(
        [
            ft.Text(f"{ram_min_mb} MB", size=11, color=TEXT_DIM, font_family=FONT_MONO),
            ft.Text(f"Recommended: {recommended_ram_mb} MB (half of {system_ram_mb} MB detected)",
                    size=11, color=TEXT_DIM, font_family=FONT_MONO),
            ft.Text(f"{ram_max_mb} MB", size=11, color=TEXT_DIM, font_family=FONT_MONO),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    ram_label = ft.Text(f"{cfg['ram_mb']} MB allocated", size=13, color=TEXT_DIM, font_family=FONT_MONO)
    ram_warning = ft.Text(
        "",
        size=12, color=DANGER, font_family=FONT_MONO, visible=False,
    )

    def _update_ram_warning(value: int):
        if value > recommended_ram_mb:
            ram_warning.value = (
                f"⚠ Above the recommended half-point ({recommended_ram_mb} MB). "
                f"Allocating too much RAM to Minecraft can starve your computer "
                f"and other apps, or cause instability."
            )
            ram_warning.visible = True
        else:
            ram_warning.visible = False

    _update_ram_warning(cfg["ram_mb"])

    def on_ram_change(e):
        """Per-tick: visual only - label, thumb/track colour, warning.

        Deliberately does NOT touch the config here. This handler fires for
        every integer step of a drag (the slider has ~64 divisions), and it
        used to call core.save_config(cfg) - i.e. serialise and rewrite the
        whole config JSON to disk up to dozens of times per drag, on the UI
        thread. That is the bulk of the "chunky slider" feel.

        Persisting is deferred to on_ram_change_end (drag/keyboard release).
        The repaint is control-level, not page.update(): a full-tree diff on
        every tick is the other half of the jank - only three controls change.
        """
        value = int(ram_slider.value)
        color = _ram_color(value)
        ram_slider.active_color = color
        ram_slider.thumb_color = color
        ram_label.value = f"{value} MB allocated"
        _update_ram_warning(value)
        thread_safe_ui.refresh(ram_slider)
        thread_safe_ui.refresh(ram_label)
        thread_safe_ui.refresh(ram_warning)

    def on_ram_change_end(e):
        """Persist the allocation once, when the user lets go of the slider.

        Guarded so a read-only config (or a full disk) surfaces as a message
        instead of an exception escaping a UI handler, which Flet swallows -
        leaving the user staring at a slider that "didn't stick".
        """
        value = int(ram_slider.value)
        if int(cfg.get("ram_mb", 0)) == value:
            return  # nothing changed (e.g. a stray change_end after load)
        cfg["ram_mb"] = value
        try:
            core.save_config(cfg)
        except Exception as ex:
            ram_warning.value = f"⚠ Couldn't save the RAM setting: {ex}"
            ram_warning.visible = True
            thread_safe_ui.refresh(ram_warning)

    ram_slider.on_change = on_ram_change
    # on_change_end exists in this Flet generation (0.86.x) and fires on drag
    # release / keyboard step. Unknown control attrs are silently dropped by
    # Flet, so this is a no-op on a build without it rather than a crash.
    ram_slider.on_change_end = on_ram_change_end

    # Width and height input fields
    width_field = ft.TextField(
        value=str(cfg["width"]), label="Width", width=140,
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    height_field = ft.TextField(
        value=str(cfg["height"]), label="Height", width=140,
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    # Java path input (optional)
    java_path_field = ft.TextField(
        value=cfg.get("java_path") or "", label="Java path",
        hint_text="Leave blank to auto-detect",
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
    )

    # Extra JVM flags the player can add on top of Cubeon's tuned defaults,
    # e.g. "-Dsome.prop=value -XX:MaxGCPauseMillis=100". One line, split on
    # whitespace (quotes respected). Saved like every other Settings field.
    custom_jvm_field = ft.TextField(
        value=cfg.get("custom_jvm_flags") or "", label="Custom JVM flags",
        hint_text="e.g. -Dsome.prop=value -XX:MaxGCPauseMillis=100",
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
    )

    def save_settings(e=None):
        """Saves width/height/java_path/custom JVM flags from the UI fields
        to the config file. Called on field blur/submit by the Settings tab
        (instant save - there is no Save button anymore)."""
        for key, field, default, minimum, maximum in (
            ("width", width_field, 1280, 320, 7680),
            ("height", height_field, 720, 240, 4320),
        ):
            try:
                value = int(field.value)
            except (TypeError, ValueError, OverflowError):
                value = default
            cfg[key] = max(minimum, min(maximum, value))
            field.value = str(cfg[key])
            thread_safe_ui.refresh(field)
        cfg["java_path"] = java_path_field.value.strip() or None
        cfg["custom_jvm_flags"] = custom_jvm_field.value.strip()
        core.save_config(cfg)
        set_status("Settings saved")

    # The in-game Cubeon Client mod (Friends button, in-game menu) is injected
    # into Fabric/Quilt profiles at launch. This is the user's off switch:
    # unchecking launches a clean mod setup (the launcher itself is unaffected).
    client_mod_cb = ft.Checkbox(
        label="",
        value=bool(cfg.get("client_mod_enabled", True)),
        active_color=ACCENT,
    )

    def on_client_mod_change(e):
        cfg["client_mod_enabled"] = bool(client_mod_cb.value)
        core.save_config(cfg)
        set_status("Cubeon Client mod " +
                   ("will install at launch" if client_mod_cb.value
                    else "disabled - launches clean"))

    client_mod_cb.on_change = on_client_mod_change

    # Glass background: translucent window so the desktop shows through
    # faintly. Restart-to-apply (the window alpha is set once at startup).
    glass_cb = ft.Checkbox(
        label="",
        value=bool(cfg.get("glass_mode_enabled", True)),
        active_color=ACCENT,
    )

    def on_glass_change(e):
        cfg["glass_mode_enabled"] = bool(glass_cb.value)
        core.save_config(cfg)
        set_status("Glass background " +
                   ("on - restart Cubeon to apply" if glass_cb.value
                    else "off - restart Cubeon to apply"))

    glass_cb.on_change = on_glass_change

    # Custom window frame (Windows only, prototype). The frame is applied while
    # the window is still HIDDEN at startup, so this needs a relaunch - the same
    # contract as the glass background above. Built only on Windows: a toggle
    # that can never do anything is worse than no toggle. See
    # cubeon/winchrome.py for why this is opt-in and Windows-only.
    custom_chrome_cb = None
    if sys.platform == "win32":
        custom_chrome_cb = ft.Checkbox(
            label="",
            value=bool(cfg.get(winchrome.CONFIG_KEY, False)),
            active_color=ACCENT,
        )

        def on_custom_chrome_change(e):
            cfg[winchrome.CONFIG_KEY] = bool(custom_chrome_cb.value)
            core.save_config(cfg)
            set_status("Custom window frame " +
                       ("on - restart Cubeon to apply"
                        if custom_chrome_cb.value
                        else "off - restart Cubeon to apply"))

        custom_chrome_cb.on_change = on_custom_chrome_change

    # "Tidy up files": runs cubeon/maintenance.py's organizer on demand. It is
    # idempotent and never touches game content, so the button is always safe
    # to press; it reports what it did in the status line. The same pass also
    # runs automatically at startup unless auto_organize_files is turned off.
    def run_tidy_up(e=None):
        set_status("Tidying up Cubeon's files…")

        def _work():
            try:
                rep = maintenance_mod.organize(apply=True)
                set_status(maintenance_mod.summary(rep, applied=True))
            except Exception:
                logging.getLogger(__name__).warning("tidy up failed", exc_info=True)
                set_status("Couldn't tidy the files - see the log for details")

        threading.Thread(target=_work, name="cubeon-tidy-up", daemon=True).start()

    tidy_btn = ft.Container(
        content=ft.Text("Tidy up files", color=TEXT, weight=ft.FontWeight.W_600, size=14),
        bgcolor=SURFACE_HI, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=11),
        alignment=ft.Alignment.CENTER, ink=False, on_click=run_tidy_up,
    )

    detected_java = core.find_java()  # Try to auto-detect Java

    # -----------------------------------------------------------------
    # BACKUP SYSTEM (Settings tab)
    # -----------------------------------------------------------------
    # Backs up config, mod profiles, skins/capes, profile picture, and
    # local server configs into a single zip under CUBEON_HOME/backups.
    # World saves are excluded by default (opt-in) since they live under
    # the shared .minecraft dir and can be many GB. See cubeon/backup.py.
    backup_settings = core.backup_module.load_backup_settings()

    backup_status_text = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)

    def _refresh_backup_status():
        existing = core.backup_module.list_backups()
        if not existing:
            backup_status_text.value = "No backups yet."
            return
        newest = existing[0]
        import datetime
        when = datetime.datetime.fromtimestamp(newest.created_ts).strftime("%Y-%m-%d %H:%M")
        backup_status_text.value = (
            f"{len(existing)} backup(s) saved. Most recent: {when} "
            f"({core.backup_module.human_size(newest.size_bytes)})."
        )

    _refresh_backup_status()

    backup_enabled_switch = ft.Switch(
        value=backup_settings["enabled"], active_color=ACCENT,
    )

    frequency_dropdown = ft.Dropdown(
        value=backup_settings["frequency"],
        label="How often",
        options=[
            ft.dropdown.Option("manual", "Manual only"),
            ft.dropdown.Option("daily", "Daily"),
            ft.dropdown.Option("weekly", "Weekly"),
        ],
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        bgcolor=SURFACE_HI, border_radius=RADIUS, expand=True,
        disabled=not backup_settings["enabled"],
    )

    include_saves_switch = ft.Switch(
        value=backup_settings["include_saves"], active_color=ACCENT,
    )

    keep_last_field = ft.TextField(
        value=str(backup_settings["keep_last"]),
        label="Keep last", hint_text="0 = keep all",
        width=150, border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
        keyboard_type=ft.KeyboardType.NUMBER,
        disabled=not backup_settings["enabled"],
    )

    def _persist_backup_settings():
        backup_settings["enabled"] = backup_enabled_switch.value
        backup_settings["frequency"] = frequency_dropdown.value
        backup_settings["include_saves"] = include_saves_switch.value
        try:
            backup_settings["keep_last"] = max(0, int(keep_last_field.value or 5))
        except ValueError:
            backup_settings["keep_last"] = 5
        core.backup_module.save_backup_settings(backup_settings)

    def on_backup_enabled_change(e):
        # Auto-backup off -> its knobs go grey too (frequency AND retention);
        # include-saves stays live because the manual "Back up now" reads it.
        frequency_dropdown.disabled = not backup_enabled_switch.value
        keep_last_field.disabled = not backup_enabled_switch.value
        _persist_backup_settings()
        set_status("Backup settings saved")
        page.update()

    def on_backup_setting_change(e):
        _persist_backup_settings()
        set_status("Backup settings saved")
        page.update()

    backup_enabled_switch.on_change = theme.toggle_wrap(on_backup_enabled_change, backup_enabled_switch)
    frequency_dropdown.on_select = on_backup_setting_change
    include_saves_switch.on_change = theme.toggle_wrap(on_backup_setting_change, include_saves_switch)
    keep_last_field.on_blur = on_backup_setting_change

    backup_busy = {"value": False}

    def run_backup_now(e):
        """Runs a manual backup on a background thread so a large mods
        folder or saves/ inclusion doesn't freeze the UI."""
        if backup_busy["value"]:
            return
        backup_busy["value"] = True
        backup_now_btn.content.value = "Backing up..."
        backup_now_btn.disabled = True
        page.update()

        def worker():
            result = core.backup_module.create_backup(
                include_saves=include_saves_switch.value,
            )
            backup_busy["value"] = False
            backup_now_btn.content.value = "Back up now"
            backup_now_btn.disabled = False
            _refresh_backup_status()
            set_status(result.message if result.ok else f"Backup failed: {result.message}")
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    backup_now_btn = ft.Container(
        content=ft.Text("Back up now", color=BG, weight=ft.FontWeight.W_700, size=14),
        bgcolor=ACCENT, border_radius=RADIUS, padding=ft.padding.Padding.symmetric(vertical=13),
        alignment=ft.Alignment.CENTER, ink=False, on_click=run_backup_now, expand=True,
    )

    def open_backups_folder(e):
        """Opens the backups folder in the OS file browser so the user can
        find/copy zips manually (e.g. onto external storage)."""
        import subprocess
        import sys as _sys
        folder = core.backup_module.BACKUPS_DIR
        try:
            os.makedirs(folder, exist_ok=True)
            if _sys.platform == "win32":
                os.startfile(folder)  # noqa
            elif _sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as ex:
            set_status(f"Couldn't open folder: {ex}")

    open_folder_btn = ft.Container(
        content=ft.Text("Open backups folder", color=TEXT, weight=ft.FontWeight.W_600, size=14),
        bgcolor=SURFACE_HI, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=13),
        alignment=ft.Alignment.CENTER, ink=False, on_click=open_backups_folder, expand=True,
    )

    # ------------------------------------------------------------------
    # MINECRAFT FILES - Settings > "Minecraft files"
    #
    # One place that opens the folders a player actually needs to find by hand:
    # the game folder itself, mods, resource packs, shaders, worlds,
    # screenshots and the launcher's own data (config/logs/cache). Before this
    # the only folder button in the app was "Open backups folder" in Backups,
    # so "where is my mods folder" had no answer inside Cubeon (the user asked
    # for exactly this on 2026-10-18).
    #
    # Same opener as open_backups_folder - os.startfile on Windows, `open` on
    # macOS, `xdg-open` elsewhere - and every failure lands in set_status
    # instead of a traceback. Each folder is created first, because opening a
    # path that does not exist yet is the one way this reads as broken.
    # ------------------------------------------------------------------
    def _open_any_folder(folder, label):
        import subprocess
        import sys as _sys
        try:
            os.makedirs(folder, exist_ok=True)
            if _sys.platform == "win32":
                os.startfile(folder)  # noqa
            elif _sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
            set_status(f"Opened {label}")
        except Exception as ex:
            set_status(f"Couldn't open {label}: {ex}")

    from cubeon import paths as _paths
    _FOLDER_ROWS = [
        ("Minecraft folder", "the game folder - versions, logs and options",
         lambda: _paths.MINECRAFT_DIR),
        ("Mods", "every jar Cubeon syncs into the game",
         lambda: _paths.MODS_DIR),
        ("Resource packs", "texture packs the game reads",
         lambda: _paths.RESOURCEPACKS_DIR),
        ("Shaders", "shaderpacks the game reads",
         lambda: _paths.SHADERPACKS_DIR),
        ("Worlds (saves)", "your singleplayer worlds",
         lambda: os.path.join(_paths.MINECRAFT_DIR, "saves")),
        ("Screenshots", "the game's screenshots folder",
         lambda: os.path.join(_paths.MINECRAFT_DIR, "screenshots")),
        ("Cubeon data", "config, logs and caches - not the game",
         lambda: _paths.CUBEON_HOME),
    ]

    def _folder_button(label, hint, getter):
        """A quiet, left-aligned row: name + hint, chevron on the right.
        The tooltip is the real resolved path - the honest answer to "where
        IS my mods folder" without opening anything."""
        row = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED, size=17, color=ACCENT_DIM),
                    ft.Column(
                        [ft.Text(label, size=13.5, color=TEXT,
                                 weight=ft.FontWeight.W_600),
                         ft.Text(hint, size=11.5, color=TEXT_DIM)],
                        spacing=1, expand=True,
                    ),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=17, color=TEXT_DIM),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="transparent", border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=10, vertical=9),
            on_click=lambda e=None, g=getter, l=label: _open_any_folder(g(), l),
        )
        try:
            row.tooltip = getter()   # the real path, resolved at build time
        except Exception:
            row.tooltip = f"Open {label}"
        theme.attach_hover(row, "transparent", ROW_HOVER)
        return row

    minecraft_files_pane = ft.Column(
        [
            section_label("Minecraft files"),
            ft.Container(height=2),
            ft.Text(
                "Open the folders Cubeon and Minecraft use. Anything you drop "
                "into Mods, Resource packs or Shaders is picked up on the next "
                "launch.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=12),
            ft.Container(
                content=ft.Column(
                    [_folder_button(*row) for row in _FOLDER_ROWS],
                    spacing=2,
                ),
                bgcolor=SURFACE_HI, border_radius=RADIUS, padding=8,
                border=ft.border.Border.all(1, BORDER),
            ),
            ft.Container(height=12),
            ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=15, color=TEXT_FAINT),
                    ft.Text(
                        "Hover a row to see its full path. These are the same "
                        "folders the Mods, Cosmetics and Screenshots surfaces "
                        "write to - nothing moves without telling you.",
                        size=11.5, color=TEXT_FAINT, expand=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(height=8),
        ],
        spacing=4, visible=False,
    )

    restore_file_picker = ft.FilePicker()

    def on_restore_picked(e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. See on_pfp_picked() above for why
        # this stays untyped rather than annotated as
        # ft.FilePickerResultEvent (missing on some pinned Flet builds).
        do_restore(e.files)

    restore_file_picker.on_result = on_restore_picked

    # Same version-spanning registration dance used for the pfp/skin
    # FilePickers above - newer Flet self-registers Services, older Flet
    # needs the explicit page.overlay append.
    _restore_registered = False
    _services_list = getattr(page, "_services", None)
    _already_registered = (
        _services_list is not None
        and hasattr(_services_list, "_services")
        and restore_file_picker in _services_list._services
    )
    _register_fn = getattr(page, "register_service", None)
    if _already_registered:
        _restore_registered = True
    elif callable(_register_fn):
        try:
            _register_fn(restore_file_picker)
            _restore_registered = True
        except Exception:
            _restore_registered = False
    if not _restore_registered:
        try:
            if restore_file_picker not in page.overlay:
                page.overlay.append(restore_file_picker)
        except Exception:
            pass

    def do_restore(files):
        if not files:
            return
        picked = files[0]
        path = getattr(picked, "path", None)
        if not path:
            set_status("Couldn't read the selected file's path")
            return

        def worker():
            result = core.backup_module.restore_backup(path)
            set_status(result.message if result.ok else f"Restore failed: {result.message}")
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    def pick_restore_file(e):
        run_file_picker(
            page, restore_file_picker, on_files=do_restore,
            allow_multiple=False, allowed_extensions=["zip"],
        )

    restore_btn = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.RESTORE_ROUNDED, size=15, color=TEXT_FAINT),
                ft.Text("Restore from a backup zip...", color=TEXT_DIM,
                        weight=ft.FontWeight.W_600, size=13),
            ],
            spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,
        ),
        border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=9),
        alignment=ft.Alignment.CENTER, ink=False, on_click=pick_restore_file,
    )

    # Small Minekube credit - a quiet icon on the Settings header row, not
    # a button demanding attention. Cubeon's entire server + sharing stack
    # (Paper hosting tunnels, public addresses) runs on Minekube Connect's
    # software and network, and that deserves a visible "this is what we
    # run on" link where server owners configure things. Clicking it opens
    # an in-launcher card (who they are and why Cubeon backs them) instead
    # of teleporting straight to the web; the card carries the website
    # button.
    def _open_minekube_website():
        """Opens Minekube's site, with the same browser-open fallback as
        every other external link in the app: if no browser can be opened,
        show the URL in a snackbar instead of failing silently."""
        import webbrowser
        try:
            if webbrowser.open("https://connect.minekube.com/"):
                return
        except Exception:
            logging.getLogger(__name__).warning("background worker error", exc_info=True)
        _show_snack("Minekube's site: https://connect.minekube.com/",
                    duration=8000)

    def _open_minekube_info(e=None):
        """The credit card: who Minekube is, why Cubeon backs them, and the
        one button that actually leaves the app."""

        def _web(_e=None):
            _close_dialog(dlg)
            _open_minekube_website()

        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.DNS_ROUNDED, color=ACCENT,
                                        size=24),
                        width=40, height=40, bgcolor=ACCENT_TINT,
                        border_radius=RADIUS, alignment=ft.Alignment.CENTER,
                    ),
                    ft.Column(
                        [
                            ft.Text("Minekube Connect", size=18, color=TEXT,
                                    font_family=FONT_DISPLAY),
                            ft.Text("Why Cubeon backs them", size=11,
                                    color=TEXT_DIM),
                        ],
                        spacing=2, tight=True,
                    ),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Minekube is open source, and their service "
                            "gives everyone - not just Cubeon - a free "
                            "public address for a server hosted on your "
                            "own machine. No port-forwarding trickery, "
                            "for anyone.",
                            size=13, color=TEXT_DIM,
                        ),
                        ft.Container(height=2),
                        ft.Text(
                            "Our server sharing runs on their network, and "
                            "that's why Cubeon backs them. If hosting with "
                            "us has helped you, a quick look at their site "
                            "keeps that going.",
                            size=13, color=TEXT_DIM,
                        ),
                    ],
                    tight=True, spacing=8,
                ),
                width=400,
            ),
            actions=[
                ft.TextButton("Close",
                              on_click=lambda e: _close_dialog(dlg),
                              style=ft.ButtonStyle(color=TEXT_DIM)),
                ft.FilledButton(
                    "Open their website",
                    icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                    on_click=_web,
                    style=ft.ButtonStyle(
                        color=ON_ACCENT, bgcolor=ACCENT,
                        shape=ft.RoundedRectangleBorder(radius=RADIUS)),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        _open_dialog(dlg)

    # --- Cubeon Web (user ask, 2026-10-16: a Settings link to the site) -----
    # The public site is the static site in web/, deployed on Vercel. It lives
    # in the Settings rail next to the Minekube credit - the two outbound links
    # in one place. CUBEON_WEB_URL can be overridden for a fork or a staging
    # deploy without touching this file.
    CUBEON_WEB_URL = (os.environ.get("CUBEON_WEB_URL")
                      or "https://cubeon.vercel.app")

    def _open_cubeon_web(e=None):
        """Opens the site, with the same browser-open fallback as every other
        external link in the app: if no browser can be opened, show the URL in
        a snackbar instead of failing silently."""
        import webbrowser
        try:
            if webbrowser.open(CUBEON_WEB_URL):
                return
        except Exception:
            logging.getLogger(__name__).warning("background worker error", exc_info=True)
        _show_snack(f"Cubeon Web: {CUBEON_WEB_URL}", duration=8000)

    cubeon_web_link = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.PUBLIC_ROUNDED, size=16, color=TEXT_DIM),
                ft.Text("Cubeon Web", size=13, color=TEXT_DIM,
                        weight=ft.FontWeight.W_500),
            ],
            spacing=10, tight=True,
        ),
        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=9),
        border_radius=RADIUS,
        ink=False,
        tooltip=CUBEON_WEB_URL,
        on_click=_open_cubeon_web,
        # Matches the rail rows: the hover wash fades rather than snapping.
        animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT_CUBIC),
    )

    minekube_badge = ft.IconButton(
        ft.Icons.DNS_ROUNDED,
        icon_size=16, icon_color=TEXT_DIM,
        tooltip="We back Minekube - open source, free addresses",
        on_click=_open_minekube_info,
    )

    # -----------------------------------------------------------------
    # SEASONAL SETTINGS (see cubeon/seasonal.py + ui/seasonal_ui.py)
    #
    # Every control here saves instantly, like the rest of the Settings tab. The
    # one thing that CANNOT take effect immediately is said out loud: the palette
    # is bound while Cubeon's package is imported, so a new season needs a fresh
    # start - and the Restart button does it (module-level `_relaunch`, honoured
    # by the __main__ session loop).
    #
    # `_season_rt` holds the runtime pieces the LAYOUT section builds later (the
    # ambience band, its particles, the one shared ticker). The handlers below
    # reach into it at CLICK time, never at definition time, which is why an
    # empty dict here is fine.
    # -----------------------------------------------------------------
    _season_rt = {"animator": None, "band": None, "strip": None,
                  "particles": None, "bounds": None}

    _SEASON_CHOICES = [("auto", "Auto (from my timezone)")] + [
        (key, cubeon_seasonal.PRETTY[key]) for key in cubeon_seasonal.SEASONS
    ] + [("off", "Off (keep the normal colors)")]

    seasonal_status_icon = ft.Icon(season_icon(cubeon_seasonal.current()),
                                   size=16, color=ACCENT)
    seasonal_status_text = ft.Text("", size=13, color=TEXT,
                                   weight=ft.FontWeight.W_600)
    seasonal_source_text = ft.Text("", size=11.5, color=TEXT_FAINT)
    # A pin that outranks the picker must be VISIBLE where the picker lives -
    # a tiny source line is easy to miss and reads as "the dropdown is broken".
    _env_pin_season = cubeon_seasonal.env_pin()
    season_pin_note = ft.Text(
        f"CUBEON_SEASON={_env_pin_season} is set in your environment and is "
        "outranking this picker. Run Cubeon without it (unset CUBEON_SEASON) "
        "to choose freely.",
        size=11.5, color=DANGER, visible=bool(_env_pin_season),
    )

    def _season_controls_sync(info=None):
        """Repaints the Settings block from a resolution.

        One function for every trigger (initial build, switch, dropdown) so the
        label and the "why" line can never disagree with each other.
        """
        info = info or cubeon_seasonal.current()
        seasonal_status_icon.name = season_icon(info)
        seasonal_status_text.value = f"{info.label} - {info.place}"
        seasonal_source_text.value = cubeon_seasonal.describe_source(info)
        for ctrl in (seasonal_status_icon, seasonal_status_text,
                     seasonal_source_text):
            thread_safe_ui.refresh(ctrl)
        # The RUNTIME half follows the new season immediately - badge chip,
        # companion sprite, weather strip - so picking a season visibly does
        # something even though the palette itself waits for a relaunch (see
        # the module map: tokens are bound at import; don't fight that).
        season_update_badge(season_badge, info)
        season_update_pet(season_pet, info)
        thread_safe_ui.refresh(season_badge)
        thread_safe_ui.refresh(season_perch)

    seasonal_switch = ft.Checkbox(
        label="", value=bool(cfg.get("seasonal_theme", False)), active_color=ACCENT,
    )
    season_dropdown = ft.Dropdown(
        value=str(cfg.get("season_override") or "auto").lower(),
        options=[ft.dropdown.Option(key=k, text=label)
                 for k, label in _SEASON_CHOICES],
        width=250, bgcolor=SURFACE_HI, border_color=BORDER,
        focused_border_color=ACCENT, border_radius=RADIUS,
        text_style=ft.TextStyle(color=TEXT, size=13),
        label_style=ft.TextStyle(color=TEXT_DIM),
    )
    season_pet_switch = ft.Checkbox(
        label="", value=bool(cfg.get("season_pet", False)), active_color=ACCENT,
    )
    season_ambience_switch = ft.Checkbox(
        label="", value=bool(cfg.get("season_ambience", False)), active_color=ACCENT,
    )

    # Full-window "Restarting…" cover, shown the instant the Restart button is
    # clicked and held until the native window goes away. Same proven pattern
    # as the account scrim (left/top/right/bottom=0 in page.overlay, opacity
    # animated): without it the window blinks out on `window.close()` and the
    # user sees no acknowledgement at all between the old and the new process.
    restart_overlay = ft.Container(
        bgcolor=ft.Colors.with_opacity(0.72, "#000000"),
        left=0, top=0, right=0, bottom=0,
        opacity=0,
        visible=False,
        ink=False,
        alignment=ft.Alignment.CENTER,
        animate_opacity=ft.Animation(170, ft.AnimationCurve.EASE_OUT),
        content=ft.Column(
            [
                ft.ProgressRing(width=26, height=26, stroke_width=3,
                                color=ACCENT),
                ft.Container(height=2),
                ft.Text("Restarting Cubeon…", size=14, color=TEXT,
                        font_family=FONT_DISPLAY),
                ft.Text("Applying your seasonal look.", size=11.5,
                        color=TEXT_DIM),
            ],
            spacing=8, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
    )
    page.overlay.append(restart_overlay)

    # Tracks whether a native close is currently in flight, so a re-click can
    # retry after a failure but two rapid clicks cannot double-fire.
    _restart_state = {"closing": False}

    def _restore_restart_ui():
        """Undo the 'Restarting…' cover WITHOUT touching the relaunch request.

        The request is the user's intent, not the UI's: it stays armed so the
        __main__ loop (or the window-gone watchdog) still re-execs. Only the
        cosmetics are undone.
        """
        _restart_state["closing"] = False
        seasonal_restart_btn.disabled = False
        seasonal_restart_note.value = "Close and reopen Cubeon to apply."
        restart_overlay.opacity = 0
        restart_overlay.visible = False
        for _c in (seasonal_restart_btn, seasonal_restart_note,
                   restart_overlay):
            thread_safe_ui.refresh(_c)

    def _on_restart_click(e=None):
        """Ask the __main__ loop to relaunch Cubeon after this session ends.

        The re-exec happens THERE, never here: execv from inside main() would
        replace the interpreter while the flet client is still running, and
        `_kill_flet_client()` (which only runs in __main__) would never get to
        clean it up - leaving a ghost window. So this sets the request, shows
        the "Restarting…" cover, and asks the window to close, nothing more.
        """
        try:
            core.save_config(cfg)
        except Exception:
            pass  # an unwritable config must not block the relaunch
        if _relaunch["request"] is None:
            # No request event (an unusual entry point): fall back to advice
            # rather than pretending to act.
            _show_snack("Close Cubeon and open it again to apply the seasonal "
                        "colors.", duration=6000)
            return
        # Idempotent: arming is the click's real effect. A click after a close
        # that raised must be able to try again, so this is NOT guarded by
        # is_set() - only a close already in flight short-circuits below.
        _relaunch["request"].set()
        if _restart_state["closing"]:
            return  # a close is already underway: don't double-schedule it
        _restart_state["closing"] = True
        seasonal_restart_btn.disabled = True
        seasonal_restart_note.value = "Restarting…"
        restart_overlay.visible = True
        restart_overlay.opacity = 1
        for _c in (seasonal_restart_btn, seasonal_restart_note,
                   restart_overlay):
            thread_safe_ui.refresh(_c)

        async def _restart_close_after_beat():
            # Let the cover fade in BEFORE the native close, so the transition
            # reads as an intentional restart instead of the UI blinking out.
            # The request stays armed for the __main__ loop either way; this
            # only paces the native close.
            #
            # Two attempts: a raise here does NOT mean the close failed - the
            # desktop client can tear the session down while the invoke is
            # still awaiting its reply (on Windows a programmatic close
            # delivers a "close" event, which runs _kill_flet_client
            # MID-AWAIT), and the window is usually already gone. The old code
            # cleared _relaunch["request"] on a raise, which turned a
            # successful close into "closes but never reopens". Retrying
            # covers the other case - the window really did stay up - without
            # ever discarding the user's restart request.
            for _attempt in range(2):
                try:
                    await asyncio.sleep(0.4 if _attempt == 0 else 0.6)
                    await page.window.close()
                    _restart_state["closing"] = False
                    return
                except Exception:
                    continue
            _restore_restart_ui()

        try:
            page.run_task(_restart_close_after_beat)
        except Exception:
            # No event loop to schedule on: fall back to the immediate close.
            _restart_state["closing"] = False
            try:
                page.run_task(page.window.close)
            except Exception:
                _restore_restart_ui()

    seasonal_restart_btn = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.RESTART_ALT_ROUNDED, size=15, color=ON_ACCENT),
                ft.Text("Restart to apply", color=ON_ACCENT,
                        weight=ft.FontWeight.W_700, size=13),
            ],
            spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,
        ),
        bgcolor=ACCENT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=10, horizontal=16),
        ink=False, on_click=_on_restart_click,
    )
    seasonal_restart_note = ft.Text(
        "Colors change on the next start.", size=11.5, color=TEXT_FAINT,
    )

    # --- seasonal handlers --------------------------------------------------
    # Each one: write cfg -> save -> re-resolve -> repaint the block -> apply the
    # runtime half (`_season_runtime_apply`, defined in the layout section where
    # the ambience band and the ticker are actually built).
    def _on_seasonal_toggle(e=None):
        cfg["seasonal_theme"] = bool(seasonal_switch.value)
        try:
            core.save_config(cfg)
        except Exception:
            pass
        _season_controls_sync(cubeon_seasonal.refresh(cfg))
        _season_runtime_apply()
        set_status("Seasonal look on" if seasonal_switch.value else
                   "Seasonal look off - the next start uses the normal colors")

    def _on_season_change(e=None):
        choice = str(season_dropdown.value or "auto").lower()
        if choice == "off":
            # "Off" in the Season list means the same as the master switch:
            # no seasonal layer at all. Keeping them in sync matters - two
            # controls that disagree about the same setting is how a settings
            # page starts lying.
            cfg["seasonal_theme"] = False
            seasonal_switch.value = False
        else:
            cfg["season_override"] = choice
            if choice in cubeon_seasonal.SEASONS:
                cfg["seasonal_theme"] = True     # picking a season implies wanting it
                seasonal_switch.value = True
        try:
            core.save_config(cfg)
        except Exception as ex:
            # A silent save failure was reported by a user as "my pick keeps
            # reverting to autumn" - the config on disk still said auto. If
            # saving fails, SAY so; a launcher that lies is worse than one
            # that complains.
            traceback.print_exc()
            set_status(f"Couldn't save your season choice: {ex}")
            _show_snack(f"Couldn't save the season choice ({ex}) - it will "
                        "revert on the next start.", duration=6000)
        _season_controls_sync(cubeon_seasonal.refresh(cfg))
        _season_runtime_apply()
        thread_safe_ui.refresh(seasonal_switch)
        _season_controls_sync()
        # The env pin outranks this setting BY DESIGN (it is the test and
        # screenshot contract) - but a pick that is silently ignored reads as
        # "the picker is broken". Name the winner out loud.
        env_pin = cubeon_seasonal.env_pin()
        if env_pin:
            _show_snack(
                f"Saved: you picked {cubeon_seasonal.PRETTY.get(choice, choice)}."
                f" But this terminal has CUBEON_SEASON={env_pin} set, which "
                "outranks the picker - run Cubeon from a terminal without it "
                "(or `unset CUBEON_SEASON`) to see your choice.",
                duration=8000)
            set_status(f"Saved {cubeon_seasonal.PRETTY.get(choice, choice)} - "
                       f"but CUBEON_SEASON={env_pin} is pinning this launch")
        else:
            set_status("Season set to "
                       + (cubeon_seasonal.PRETTY.get(choice) or "Auto")
                       + " - restart to apply")

    def _on_season_pet_toggle(e=None):
        cfg["season_pet"] = bool(season_pet_switch.value)
        try:
            core.save_config(cfg)
        except Exception:
            pass
        _season_runtime_apply()

    def _on_season_ambience_toggle(e=None):
        cfg["season_ambience"] = bool(season_ambience_switch.value)
        try:
            core.save_config(cfg)
        except Exception:
            pass
        _season_runtime_apply()
        set_status("Weather effects on" if season_ambience_switch.value
                   else "Weather effects off")

    seasonal_switch.on_change = _on_seasonal_toggle
    season_dropdown.on_select = _on_season_change
    season_pet_switch.on_change = _on_season_pet_toggle
    season_ambience_switch.on_change = _on_season_ambience_toggle
    _season_controls_sync(season_info)

    # The Import section's target: whatever version + loader the player has
    # chosen on the Play tab, so a scanned mod/pack lands in the exact
    # instance they are about to launch (mods and packs are per-profile).
    def _import_target():
        vid = version_dropdown.value or cfg.get("last_version")
        mc = core.extract_mc_version(vid) if vid else None
        loader = state.get("mod_loader") or "fabric"
        return mc, loader, vid

    # Every installed instance for the Import-to picker. Loader is derived
    # from the version id (the only place it's recorded for non-active
    # instances); mc_version from the id as well, so the picker can grey out
    # a Fabric jar offered to a Forge instance or a mod that needs 1.20.1.
    def _import_instances():
        out = []
        try:
            installed = core.get_installed_versions()
        except Exception:
            installed = []
        for v in installed or []:
            vid = v.get("id") or v.get("version_id")
            if not vid:
                continue
            try:
                mc = core.extract_mc_version(vid)
            except Exception:
                mc = None
            out.append({
                "version_id": vid,
                "mc_version": mc,
                "loader": None,  # importer.loader_of fills it from the id
                "label": v.get("display_name") or vid,
            })
        return out

    import_pane = build_import_section(
        page, cfg, section_label=section_label,
        get_active_target=_import_target,
        get_instances=_import_instances, show_snack=_show_snack,
        **THEME,
    )

    # Build the Settings tab UI - two panes (section rail + content), all
    # controls prebuilt above, arranged by ui/settings_tab.py. Every field
    # saves instantly on blur/submit; there is no Save button anymore.
    settings_tab = build_settings_tab(
        page, cfg,
        section_label=section_label, pixel_divider=pixel_divider,
        set_status=set_status,
        save_width_height_java=save_settings,
        browse_online_row=browse_online_row, legacy_btn=legacy_btn,
        legacy_note=legacy_note, client_mod_cb=client_mod_cb,
        glass_cb=glass_cb, tidy_btn=tidy_btn,
        custom_chrome_cb=custom_chrome_cb,
        ram_slider=ram_slider, ram_range_row=ram_range_row,
        ram_label=ram_label, ram_warning=ram_warning,
        width_field=width_field, height_field=height_field,
        java_path_field=java_path_field, custom_jvm_field=custom_jvm_field,
        detected_java=detected_java, import_pane=import_pane,
        backup_enabled_switch=backup_enabled_switch,
        frequency_dropdown=frequency_dropdown,
        include_saves_switch=include_saves_switch,
        keep_last_field=keep_last_field,
        backup_status_text=backup_status_text,
        backup_now_btn=backup_now_btn, open_folder_btn=open_folder_btn,
        minecraft_files_pane=minecraft_files_pane,
        restore_btn=restore_btn, minekube_badge=minekube_badge,
        cubeon_web_link=cubeon_web_link,
        seasonal_switch=seasonal_switch, season_dropdown=season_dropdown,
        seasonal_status_icon=seasonal_status_icon,
        seasonal_status_text=seasonal_status_text,
        seasonal_source_text=seasonal_source_text,
        seasonal_restart_btn=seasonal_restart_btn,
        seasonal_restart_note=seasonal_restart_note,
        season_pin_note=season_pin_note,
        season_pet_switch=season_pet_switch,
        season_ambience_switch=season_ambience_switch,
        **THEME,
    )

    # -----------------------------------------------------------------
    # TAB SWITCHING LOGIC
    # -----------------------------------------------------------------

    # Map tab keys to their respective content. Each is a plain, natively
    # scrollable ft.Column (scroll=ft.ScrollMode.AUTO) - no fake-smoothing
    # or blur-on-scroll wrapper.
    tabs = {
        "play": play_tab,
        "mods": mods_tab,
        "modpacks": modpacks_tab,
        "profile": profile_tab,
        "server_console": server_console_tab,
        "server_browse": server_browse_tab,
        "server_plugins": server_plugins_tab,
        "server_settings": server_settings_tab,
        "settings": settings_tab,
        "stats": stats_tab_host,
        "chat": chat_tab_host,
    }
    SERVER_GROUP_KEYS = {"server_console", "server_browse", "server_plugins", "server_settings"}

    def _reconcile_running_button():
        """Self-heal the play button against a dead session record.

        on_exit() is the normal path, but a launcher re-exec (GPU-crash
        recovery, Settings > Restart) drops the in-process on_exit watcher
        while the game record lives on - leaving state["running_version"] set
        and the button stuck on GAME RUNNING... Re-sync against the
        watchdog (cheap: one psutil probe, and only when a running version
        is even claimed).
        """
        vid = state.get("running_version")
        if not vid:
            return
        try:
            from cubeon import watchdog as _watchdog
            live = _watchdog.stale_session()
        except Exception:
            return  # watchdog unavailable: leave the state untouched
        if live is None:
            # Nothing actually alive - the record is stale. Clear it and, if
            # the user is looking at the version it claimed, repaint the
            # honest mode. (A different selected version already owns its
            # own correct mode from on_version_selected.)
            state["running_version"] = None
            if version_dropdown.value == vid:
                _sync_play_button()
        elif version_dropdown.value == vid:
            # Claimed AND alive: re-assert it. This runs on every Play-tab
            # entry and from the liveness watcher, so a stray repaint (a
            # selection refresh, a finishing prefetch) cannot leave PLAY
            # showing while the game is live - and clicking PLAY then quits
            # the game instead of starting one (reported 2026-10-16).
            set_button_mode("running")

    def switch_tab(key):
        """
        Switches the active tab. Updates the navigation buttons' appearance
        and replaces the content area with the chosen tab.
        Also triggers a refresh of the mods list when switching to the Mods
        tab, and of the Servers tab (with its Console/Plugins/Settings chip
        row) when switching to any of its keys.
        """
        active_tab["value"] = key
        # The top-bar Servers icon is an entry point, not a tab of its own:
        # it opens the Console (the chips then switch between the three).
        if key == SERVER_TOP_KEY:
            key = "server_console"
        # Update nav button styles
        for k, btn in nav_buttons.items():
            _style_nav_button(btn, k == key or (k == SERVER_TOP_KEY and key in SERVER_GROUP_KEYS))
        # The server chip row lives under the top bar and is visible only
        # while a server tab is active. The top-bar "Servers" icon itself is
        # just an entry point - it opens the Console.
        subnav_bar.visible = key in SERVER_GROUP_KEYS
        # Replace content - instantly. No AnimatedSwitcher fade: a 220ms
        # cross-fade reads as lag on tab changes (the user reads it as
        # "sloppy rendering"), and the fade forced the whole-page update
        # below to carry two full tab trees at once. Hard-cut + scoped
        # refresh is the snappy path.
        tab_switcher.content = ft.Container(tabs[key], padding=ft.padding.Padding.symmetric(
            horizontal=28, vertical=24), expand=True)
        # If switching to Mods, refresh the list and load recommendations if not yet loaded
        if key == "mods":
            _ensure_tab("mods")
            refresh_mods_list()
            if not state.get("mods_recommendations_loaded"):
                state["mods_recommendations_loaded"] = True
                load_recommended_mods()
        elif key == "modpacks":
            _ensure_tab("modpacks")
            refresh_installed_packs()
            if not state.get("modpacks_loaded"):
                state["modpacks_loaded"] = True
                load_popular_modpacks()
        elif key == "profile":
            refresh_profile_tab()
        elif key in SERVER_GROUP_KEYS:
            _ensure_tab("server")
            refresh_server_tab()
            if key == "server_browse":
                _cb("server", "browse_refresh")()
        elif key == "stats":
            _ensure_tab("stats")
            _cb("stats", "refresh")()
        elif key == "chat":
            _ensure_tab("chat")
            _cb("chat", "refresh")()
        elif key == "play":
            refresh_server_status_panel()
            _reconcile_running_button()
            # Also re-derive the big button on every entry: a pack install
            # elsewhere (Modpacks tab) can have claimed or released this
            # instance while the Play tab was hidden, and the button must
            # never be the stale one.
            _sync_play_button()
        # Scoped repaint, NOT page.update(): a whole-page diff re-sends every
        # control of every mounted tab over the websocket (~hundreds) - a
        # visible frame hitch exactly at the moment of the switch. Diffing
        # the switcher + subnav alone paints the swap; the nav buttons'
        # style changes ride along in the same flush.
        thread_safe_ui.refresh(tab_switcher)
        thread_safe_ui.refresh(subnav_bar)
        for btn in nav_buttons.values():
            thread_safe_ui.refresh(btn)

    # Initialize content area with the Play tab
    tab_switcher.content = ft.Container(play_tab, padding=ft.padding.Padding.symmetric(
        horizontal=28, vertical=24), expand=True)

    # -----------------------------------------------------------------
    # FINAL LAYOUT - assemble the whole page
    # -----------------------------------------------------------------

    # The shell: the top icon bar above the content surface - the whole
    # window is one column now, no sidebar. There is a bottom bar: brand
    # lives in the top bar's left edge.
    #
    # content_area (the tab host) lives INSIDE the surface; switching tabs
    # only ever replaces its .content, so the surface persists. The subnav
    # bar (server Console/Plugins/Settings chips) sits between the top bar
    # and the surface and shows itself only while a server tab is active.
    content_surface = ft.Container(
        content=content_area,
        bgcolor=CARD_FILL,
        border=ft.border.Border.all(1, CARD_BORDER),
        border_radius=RADIUS_LG,
        margin=ft.margin.Margin.only(left=12, top=4, right=12, bottom=12),
        expand=True,
    )

    # --- SEASONAL RUNTIME (the ambience band + the one shared ticker) --------
    # The weather lives in its OWN LAYOUT BAND between the top bar and the
    # content surface, not as an overlay on top of the tabs. An overlay in the
    # corner would sit over the content surface and swallow clicks in whatever
    # happened to be underneath it - and a decoration must never eat an
    # interaction. A 56px band costs nothing, is always visible, and reads as
    # weather across the top of the window rather than as a stray box.
    #
    # `width` is the window width at build time: particles are spread over it
    # once, and keep their positions if the window is later resized (they wrap
    # within that width). Re-flowing them on every resize would mean listening
    # to window events for a decoration.
    # Uses the SAVED width (_gw), not page.window.width: during startup the
    # window is still sized as the loading splash, so reading it here would
    # spread the particles over 360px instead of the real window.
    _season_strip_w = max(360, int(_gw or 1180) - 40)
    season_strip, season_particles, season_bounds = build_ambience(
        season_info, width=_season_strip_w, height=56,
    )
    season_band = ft.Container(
        content=season_strip,
        height=56,
        visible=False,          # flipped by _season_runtime_apply() below
        padding=ft.padding.Padding.only(left=12, right=12),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    _season_rt.update({"band": season_band, "strip": season_strip,
                       "particles": season_particles, "bounds": season_bounds,
                       "season": season_info.season})
    season_animator = SeasonalAnimator()
    _season_rt["animator"] = season_animator

    def _season_runtime_apply():
        """Applies the seasonal runtime switches (pet, weather) immediately.

        These two are the halves of the feature that do NOT need a relaunch -
        only the palette does - so toggling them must be instant. Registration
        is rebuilt from cfg rather than diffed: there are at most two entries,
        and rebuilding can't drift out of sync with the checkboxes.
        """
        info = cubeon_seasonal.current()
        pet_on = bool(cfg.get("season_pet", True)) and info.seasonal
        weather_on = bool(cfg.get("season_ambience")) and info.seasonal

        if season_perch.visible != pet_on:
            season_perch.visible = pet_on
            thread_safe_ui.refresh(season_perch)
        if _season_rt["band"].visible != weather_on:
            _season_rt["band"].visible = weather_on
            thread_safe_ui.refresh(_season_rt["band"])

        animator = _season_rt["animator"]
        animator.clear()
        if weather_on and _season_rt.get("season") != info.season:
            # A live season change re-seeds the weather for the new season
            # (same particle controls, new palette/behavior) - the palette
            # itself still waits for a relaunch.
            _season_rt["bounds"] = season_reflow_ambience(
                _season_rt["particles"], _season_rt["bounds"], info)
            _season_rt["season"] = info.season
            thread_safe_ui.refresh(_season_rt["strip"])
        if pet_on:
            animator.add_pet(season_pet)
        if weather_on:
            animator.add_ambience(_season_rt["strip"], _season_rt["particles"],
                                  _season_rt["bounds"])
        if animator.has_work:
            animator.start()
        else:
            animator.stop()

    _season_runtime_apply()

    # -----------------------------------------------------------------
    # SEASONAL ACTIONS - the deferred half of the badge/pet wiring
    # (their click handlers were built with the top bar, above)
    # -----------------------------------------------------------------
    def _open_seasonal_settings(e=None):
        """The badge's job: land the user ON the Seasonal pane, not just the
        Settings tab. A season they disagree with is fixed there."""
        try:
            switch_tab("settings")
            settings_tab.select_section("seasonal")
        except Exception:
            traceback.print_exc()

    def _on_pet_clicked(e=None):
        """The companion is a mood, never a feature: it bounces and says one
        line. The bounce lifts the sprite inside its perch lane (top, like the
        animator's idle hops) so it can't fight the wander machine.

        Every step is guarded - decoration that can raise is worse than no
        decoration, and this runs off a click in the top bar.
        """
        try:
            season_pet_ctrl.top = -10
            thread_safe_ui.refresh(season_pet_ctrl)

            def _settle():
                try:
                    season_pet_ctrl.top = 0
                    thread_safe_ui.refresh(season_pet_ctrl)
                except Exception:
                    pass  # window gone mid-hop - the hop is over anyway

            _t = threading.Timer(0.22, _settle)
            _t.daemon = True
            _t.start()
        except Exception:
            pass
        try:
            _show_snack(season_quip(cubeon_seasonal.current()), duration=3500)
        except Exception:
            pass

    # Swap the loading splash for the real UI. The window is already mapped
    # (showing the splash), so this swap IS the transition the user sees -
    # no hidden build, no flash of an empty frame.
    #
    # Glass background: a single dark artwork layer painted BEHIND everything,
    # under the translucent content panel (CARD_FILL is 55% opaque) and the thin
    # margins around it - so the window reads as panels floating over a lit
    # backdrop rather than a flat black slab. Painting the backdrop in-app is
    # deliberate: a translucent NATIVE window is not portable (the Linux embedder
    # has to opt into per-pixel alpha and usually does not), whereas a background
    # layer looks the same everywhere. Toggle in Settings; needs a relaunch.
    _glass_on = bool(cfg.get("glass_mode_enabled", True))
    # The backdrop follows the ACTIVE palette: a seasonal boot uses the matching
    # glass_<season>.jpg, and green / a pinned --color / anything unknown falls
    # back to the base glass.jpg. The seasonal files are generated alongside it
    # by tools/make_background.py.
    _bg_dir = os.path.join(resolve_assets_dir(), "bg")
    _bg_path = os.path.join(
        _bg_dir, background_image_name(getattr(theme, "ACTIVE_TEMPLATE", None),
                                       _bg_dir))
    _bg_kwargs = {}
    if _glass_on and os.path.isfile(_bg_path):
        _bg_kwargs["image"] = ft.DecorationImage(
            src=_bg_path, fit=ft.BoxFit.COVER, opacity=1.0,
            filter_quality=ft.FilterQuality.MEDIUM,
        )
    # The window's content: the branded top bar over the rest of the shell.
    # With the custom frame (Windows) two things change here:
    #   1. the top bar IS the title bar - WindowDragArea gives it the native
    #      behaviours (drag to move, double-click to maximize/restore, and,
    #      because a drag is a WM_NCLBUTTONDOWN/HTCAPTION under the hood, Snap
    #      Layouts, drag-to-restore and Win+arrow). Its pan recognizer does not
    #      consume taps, so the nav icons and buttons still take their clicks;
    #   2. the same column is wrapped in a Stack with the eight resize hot-zones,
    #      which are positioned against the WINDOW's own edges and so must sit at
    #      the outermost layer.
    _top_region = top_bar
    if _custom_chrome:
        try:
            _top_region = ft.WindowDragArea(content=top_bar, maximizable=True)
        except Exception:
            _top_region = top_bar  # a frame that can't be dragged beats none
    _root_content = ft.Column([_top_region, subnav_bar, season_band, content_surface],
                              expand=True, spacing=0)
    if _custom_chrome:
        try:
            _resize_edges = build_resize_edges(_on_resize_edge)
            # A window that came up maximized has no resizable border to grab.
            set_resize_edges_visible(_resize_edges,
                                     not _is_chrome_maximized())
            _root_content = ft.Stack([_root_content, *_resize_edges],
                                     fit=ft.StackFit.EXPAND, expand=True)
        except Exception:
            # Resizing is a nicety; the frame itself must survive without it.
            _resize_edges = []
    _app_root = ft.Container(
        content=_root_content,
        expand=True,
        bgcolor=BG,
        # Start transparent and fade in on reveal (see _reveal_window): the
        # splash is swapped for this root a beat before the window is shown, so
        # a 0 -> 1 fade turns what would be a hard cut into one smooth reveal.
        # The values below are the safety net - if the reveal task never runs,
        # opacity is forced to 1 there too, so the UI can never stay invisible.
        opacity=0.0,
        animate_opacity=ft.Animation(260, ft.AnimationCurve.EASE_OUT),
        **_bg_kwargs,
    )
    page.controls.clear()
    page.controls.append(_app_root)
    page.update()

    # Finally, populate the version dropdown for the first time (offline mode)
    refresh_version_list()
    _startup_mark("UI built and control tree mounted")

    # Marks the initial synchronous mount as done. Must come after
    # refresh_version_list() (which is itself synchronous and may start
    # background threads like the loader-support check), not before -
    # otherwise a background update could still land while this very
    # function is mid-mount. See cubeon/thread_safe_ui.py for the startup
    # IndexError this fixes (a background page.update() racing Flet's diff
    # of the still-mounting control tree).
    thread_safe_ui.mark_mounted(page)

    # --- Swap the splash for the finished window --------------------------
    # The window PROCESS was started hidden (view=FLET_APP_HIDDEN at ft.run)
    # and the splash revealed right after the first window settings. By now
    # the full control tree is mounted and the theme is applied, so applying
    # the saved geometry and making the finished UI visible is one clean
    # shot: no default-size flash, no hide-then-reshow.
    # wait_until_ready_to_show() is the desktop-shell handshake that the
    # first frame is actually in the window's back buffer.
    async def _reveal_window():
        _apply_real_geometry()
        try:
            await asyncio.wait_for(
                page.window.wait_until_ready_to_show(), timeout=5)
        except Exception:
            pass  # non-desktop or an odd runtime: fall through, visible still applies
        _show_window()
        _nudge_window_to_front()
        _backstop_window_visible()
        # Fade the finished UI in. It was mounted at opacity 0 (see _app_root
        # in main), so this single property change turns the splash -> app hand
        # off into one smooth fade instead of a hard cut. One control-level
        # patch for the root: the diff walk still covers the whole subtree, but
        # the patch SENT is one number, and it happens once at startup.
        try:
            _app_root.opacity = 1.0
            thread_safe_ui.refresh(_app_root)
        except Exception:
            pass
        # Some desktop clients apply their native default position when the
        # hidden window is first mapped, after the earlier geometry call. That
        # late native write is why the launcher could still appear at (0, 0)
        # even though the splash and real geometry both requested centering.
        # Correct it after the first visible frame, when the window manager
        # owns the mapped window. Only do this for the no-position case; an
        # intentional saved position must remain untouched.
        if _needs_center:
            try:
                await asyncio.sleep(0.15)
                await page.window.center()
                page.window.update()
            except Exception:
                pass
        elif not _saved_maximized and _gl is not None and _gt is not None:
            # Re-assert the SAVED position after the first frame. The same
            # late native write that used to stomp centering (see above) also
            # stomps a restored position on some Linux builds - the window
            # then opens at (0, 0) top-left no matter where it was closed.
            # Setting left/top again while the WM owns the mapped window wins.
            try:
                await asyncio.sleep(0.15)
                page.window.left = int(_gl)
                page.window.top = int(_gt)
                page.window.width = int(_gw)
                page.window.height = int(_gh)
                page.window.update()
            except Exception:
                pass
        # First successful paint: clear any GPU-crash flag so the NEXT run
        # trusts hardware GL again (see the exit watcher under __main__).
        # _CUBEON_HOME lives in the __main__ block, not in main()'s scope -
        # importing it here is what keeps the ui_painted_ok marker actually
        # being written (a NameError here used to silently kill the marker,
        # making every session look like a pre-paint crash to the watcher).
        try:
            from cubeon.paths import CUBEON_HOME as _CUBEON_HOME
            _ui = os.path.join(_CUBEON_HOME, "ui_painted_ok")
            open(_ui, "w").close()
            # The software-GL fallback has DONE its job the moment the UI
            # paints on it: clear it now rather than waiting for a clean
            # close. Otherwise the marker lingers armed the whole session
            # (and across kills/crashes) and - far worse - the game used to
            # inherit the launcher's LIBGL_ALWAYS_SOFTWARE and run at ~4 FPS
            # on llvmpipe. The env vars are also stripped from the game's
            # environment in cubeon/launch.py as belt-and-braces.
            # NOTE the name: this function ALSO reads the saved window
            # position `_gl` (geometry left) from main()'s closure above -
            # naming the marker `_gl` too made Python treat `_gl` as local for
            # the WHOLE coroutine, so the saved-position re-assert raised
            # UnboundLocalError on every launch with saved geometry, aborting
            # the coroutine BEFORE the window was ever shown (the relaunched
            # window never appeared). Keep these names distinct.
            _gl_marker = os.path.join(_CUBEON_HOME, "use_software_gl")
            if os.path.exists(_gl_marker):
                try:
                    os.remove(_gl_marker)
                except OSError:
                    pass
        except (OSError, ImportError):
            pass
        try:
            page.window.update()
        except Exception:
            page.update()
        _startup_mark("finished UI revealed")

    # The overlay handle lives outside the `if` so the post-reveal fade below
    # can stay a plain `if _onboard_overlay is not None`.
    _onboard_overlay = None

    # -----------------------------------------------------------------
    # FIRST-RUN ONBOARDING
    # A brand-new config (no "onboarded" flag) gets a full-screen, four-step
    # welcome: what Cubeon is, the in-game name, the features worth knowing
    # about, and the seasonal look (with a real switch for it). The old
    # one-field dialog explained none of that - a first run ended up feeling
    # like "a pop-up with a username box" (user ask, 2026-10-23).
    #
    # The screen is an overlay, not a Dialog: it has to own the whole window,
    # fade in smoothly, and let its own steps animate. It is appended LAST to
    # page.overlay, so it sits above every other overlay until the user
    # finishes. Nothing is written until _finish_onboarding; the seasonal
    # switch is the one exception (it is a real preference and saves as it is
    # flipped, exactly like its Settings twin).
    #
    # The seasonal step doubles as this season's greeting, so finishing marks
    # `season_seen` - otherwise the once-per-season card would land on top of
    # the screen that just explained the season.
    # -----------------------------------------------------------------
    if "onboarded" not in cfg:

        def _finish_onboarding(name):
            ok, err = core.validate_username(name)
            if not ok:
                return False, err
            profile_username_field.value = name
            # Publish the new name NOW, synchronously. The old call here
            # (on_profile_username_change) was removed by the account-panel
            # debounce rework and this call site was missed - every first
            # run crashed both "Start playing" and Enter in the welcome
            # dialog with NameError. Point the shared publisher at this
            # field and publish directly: the debounced path would fire
            # 1.2s later, after this handler has already saved cfg and
            # retired the overlay.
            _name_state["field"] = profile_username_field
            _cancel_pending_name()
            _publish_username()
            cfg["onboarded"] = True
            try:
                cfg["season_seen"] = cubeon_seasonal.current().slug
            except Exception:
                pass  # a greeting key is optional; finishing must not fail
            try:
                core.save_config(cfg)
            except Exception as ex:
                return False, f"Couldn't save your settings: {ex}"
            return True, ""

        def _onboard_season_toggle(on):
            # The onboarding speaks about "the seasonal look" as one thing, so
            # the switch owns both halves that make it visible: the palette
            # (next start) and the top-bar companion (immediately). Ambience
            # stays off - it is the one part with a repaint clock and the
            # Settings pane still treats it as opt-in.
            cfg["seasonal_theme"] = bool(on)
            cfg["season_pet"] = bool(on)
            try:
                core.save_config(cfg)
            except Exception:
                pass  # the switch still reflects the choice for this session
            try:
                cubeon_seasonal.refresh(cfg)
                _season_runtime_apply()
            except Exception:
                logging.getLogger(__name__).debug(
                    "onboarding seasonal runtime apply failed", exc_info=True)

        try:
            _onboard_overlay = build_onboarding(
                page,
                initial_name=cfg.get("username") or "",
                info=cubeon_seasonal.current(),
                friends_on=friends_enabled(),
                season_on=bool(cfg.get("seasonal_theme")),
                backdrop=_bg_path,
                validate_name=core.validate_username,
                on_season_toggle=_onboard_season_toggle,
                on_finish=_finish_onboarding,
            )
            page.overlay.append(_onboard_overlay)
            # Mount it transparent; the fade-in is fired right after the
            # window's own reveal (see below), so the two fades don't overlap
            # into one flash.
            page.update()
        except Exception:
            traceback.print_exc()  # a missed welcome must not break startup



    # AWAIT the finish reveal (same rationale as the splash above). Awaiting
    # yields to the loop, which flushes the swap patch queued at page.update()
    # just above, applies the real geometry and fades the finished UI in.
    try:
        await _reveal_window()
    except Exception:
        # Belt-and-braces: never leave the app mounted but invisible.
        _apply_real_geometry()
        _show_window()
        try:
            _app_root.opacity = 1.0  # never leave the UI stuck invisible
        except Exception:
            pass

    # Now that the window is up, bring the first-run tour in. The overlay was
    # mounted transparent a moment ago, so this is one opacity animation over
    # an already-visible launcher - no second window reveal, no flash.
    if _onboard_overlay is not None:
        try:
            _onboard_overlay.opacity = 1
            _onboard_overlay.scale = ft.Scale(1)
            thread_safe_ui.refresh(_onboard_overlay)
        except Exception:
            pass

    # The Cubeon name is automatic now: ensure_identity() mints the
    # secret-derived handle (no claim prompt) and the server binds it on the
    # WebSocket hello. Connect as soon as there IS one - whether it predates
    # this launch or was just minted. Connecting only for a pre-existing
    # identity meant a first-run player who never opened the launcher's Chat
    # tab (in-game chat is the other way in) stayed "not connected to Cubeon"
    # for their whole first session with a perfectly good connection - the
    # 2026-10-17 report. connect() is safe to call again from the Chat tab: it
    # stops a running loop before starting another. Headless harnesses are not
    # affected - they stub FriendsClient.connect before building the UI (see
    # tools/_fuzz_common.py).
    if friends_client is not None and friends_client.is_available:
        try:
            friends.ensure_identity()
        except Exception:
            traceback.print_exc()
        friends_client.connect()

    # Java resolution is ~1.5s the first time on a cold machine: mll probes
    # every JVM it can find by running `java -version` on each. on_play_click
    # runs that on the UI THREAD, before it can so much as paint "Preparing",
    # so the first click on Play froze the window for a second or more. Do the
    # first, expensive probe here instead, off the UI thread, and the click's
    # own call is the cheap warm one. Strictly best-effort: a failure here
    # leaves the click paying exactly what it always paid.
    def _warm_java_check():
        try:
            selected = version_dropdown.value or state.get("selected_version")
            if not selected:
                return
            core.jre.java_status(core.extract_mc_version(selected),
                                 cfg.get("java_path"))
        except Exception:
            pass

    try:
        threading.Thread(target=_warm_java_check, daemon=True,
                         name="cubeon-java-warm").start()
    except Exception:
        pass

    # -----------------------------------------------------------------
    # GAMEPAD SUPPORT
    # A plugged-in controller shows a status pill in the sidebar and can
    # drive the launcher's menus. Mapping (Linux gamepad standard layout,
    # works for Xbox/PlayStation/most third-party pads):
    #   A / Start = Play (or Download & Play)   B = back to the Play tab
    #   D-pad left/right = cycle tabs           X = Mods   Y = Modpacks
    #   Select = show this mapping as a toast
    _CONTROLLER_HINT = ("Gamepad:  A/Start = Play · D-pad = switch tabs · "
                        "B = Play tab · X = Mods · Y = Modpacks · Select = help")

    def _controller_show_help():
        _show_snack(_CONTROLLER_HINT, duration=6000)

    def _controller_cycle_tab(direction: int):
        keys = [k for k in nav_buttons.keys() if k in tabs]
        if not keys:
            return
        try:
            i = keys.index(active_tab["value"])
        except ValueError:
            i = 0
        switch_tab(keys[(i + direction) % len(keys)])

    def _on_controller_event(button: str):
        try:
            if button in ("a", "start"):
                if active_tab["value"] != "play":
                    switch_tab("play")
                elif not play_button.disabled:
                    on_play_click()
            elif button == "b":
                switch_tab("play")
            elif button == "x":
                switch_tab("mods")
            elif button == "y":
                switch_tab("modpacks")
            elif button == "left":
                _controller_cycle_tab(-1)
            elif button == "right":
                _controller_cycle_tab(1)
            elif button == "select":
                _controller_show_help()
        except Exception:
            pass  # a stray pad press must never break the launcher

    def _on_controller_connect(name: str):
        _show_snack(f"🎮 {name} connected · {_CONTROLLER_HINT}", duration=7000)

    def _on_controller_disconnect(name: str):
        _show_snack(f"🎮 {name} disconnected", duration=4000)

    try:
        # Process-scoped watcher (see module-level _dispatch_controller):
        # one watcher serves every session; per-session handlers are
        # registered in the runtime slot and refreshed per session.
        _session_runtime["controller_handlers"] = {
            "event": _on_controller_event,
            "connect": _on_controller_connect,
            "disconnect": _on_controller_disconnect,
        }
        _session_runtime.setdefault("controller_watcher", None)
        if _session_runtime["controller_watcher"] is None:
            _session_runtime["controller_watcher"] = ControllerWatcher(
                on_event=lambda btn: _dispatch_controller("event", btn),
                on_connect=lambda name: _dispatch_controller("connect", name),
                on_disconnect=lambda name: _dispatch_controller("disconnect", name),
            )
        _session_runtime["controller_page"] = page
        _session_runtime["controller_watcher"].start()
    except Exception:
        pass  # no /dev/input (or no perms) - pad stays off

    # -----------------------------------------------------------------
    # SCHEDULED BACKUPS
    # The Settings tab already persists a frequency (daily/weekly) and a
    # last-run timestamp, but nothing was actually triggering them. Check
    # once at startup and then on a slow timer, so even a session left open
    # for days still fires on schedule. is_due() returns False unless
    # backups are enabled AND the interval since the last one has elapsed,
    # so this is a cheap no-op in the common manual/disabled case. Runs on a
    # daemon thread; page.update() from here is safe via thread_safe_ui.
    # -----------------------------------------------------------------
    def _backup_scheduler():
        while True:
            try:
                if core.backup_module.is_due():
                    set_status("Running scheduled backup", busy=True)
                    result = core.backup_module.create_backup()
                    set_status(result.message if result.ok else f"Backup failed: {result.message}")
                    _refresh_backup_status()
                    page.update()
            except Exception:
                # A scheduler that dies silently is bad, but one that takes the
                # app down over a backup hiccup is worse - swallow and retry.
                pass
            time.sleep(1800)  # re-check every 30 minutes

    threading.Thread(target=_backup_scheduler, daemon=True).start()

    # -----------------------------------------------------------------
    # PLAYTIME RECONCILE
    # The game outlives the launcher (see launch.py start_new_session), and a
    # GPU-crash re-exec replaces this process wholesale - killing the in-process
    # on_exit watcher that would otherwise credit playtime. Every start (INCLUDING
    # a deliberate relaunch, which sets CUBEON_RELAUNCH) reconciles the persisted
    # session record so the game's time is still counted.
    # -----------------------------------------------------------------
    try:
        core.milestones_reconcile_play_session()
    except Exception:
        pass  # cosmetic; never block startup on it

    # -----------------------------------------------------------------
    # ORPHANED GAME WATCHDOG
    # If the previous launcher run died while Minecraft was still up, the
    # game is still running with no one watching it (holding locks on the
    # mods folder). Offer to end it - once, non-blocking, easy to dismiss.
    # -----------------------------------------------------------------
    try:
        from cubeon import watchdog as _watchdog
        _stale = None if os.environ.pop("CUBEON_RELAUNCH", None) \
            else _watchdog.stale_session()
        if _stale:
            def _kill_orphan(e=None):
                _watchdog.terminate(_stale["pid"], _stale["session_id"])
                _show_snack(f"Ended the leftover Minecraft session "
                            f"(pid {_stale['pid']})")

            _show_snack("A Minecraft session from before is still running",
                        duration=8000, action=_kill_orphan, action_label="Close it")
    except Exception:
        pass  # watchdog is a nicety; never block startup on it

    # -----------------------------------------------------------------
    # UPDATE CHECK
    # ONE quiet background GET at startup (cubeon/updater.py). A newer
    # release is announced ONCE PER VERSION and never by a modal: the
    # in-app snackbar offers our own download page, and the optional OS
    # toast rides along if the user kept that switch on.
    #
    # The once-per-version marker (updater.NOTICE_SEEN_KEY) is the fix for
    # the 2026-10-18 report "the notification of new cubeon release is just
    # spamming ... coming up again and again": the snackbar used to be shown
    # on EVERY start with no memory whatsoever. There was also a SECOND check
    # below (without the update token) whose only job was that toast - two
    # GETs per start, and on a private repo two different answers for the same
    # release. One check, one announcement, both channels.
    # -----------------------------------------------------------------
    def _offer_update(info: dict):
        import webbrowser

        def _open_download(e=None):
            # info["url"] is our own download page, not the GitHub release:
            # that repo is private, so the release page is an auth wall for
            # anyone who isn't us (cubeon/updater.DOWNLOAD_URL).
            try:
                webbrowser.open(info["url"])
            except Exception:
                logging.getLogger(__name__).warning("background worker error", exc_info=True)

        _show_snack(f"Cubeon {info['version']} is available",
                    duration=10000, action=_open_download, action_label="Get it")

    def _announce_update(info: dict):
        """Announce a newer release - once, then never again for that version."""
        try:
            version = str((info or {}).get("version") or "").strip()
            if not version or not updater.should_announce(cfg, version):
                return
            # Marked (above, in place) BEFORE either notice goes out: the OS
            # toast is switched off for plenty of people and a closed window
            # swallows the snackbar, and a lost notice must never turn into a
            # nag on the next start. Its write is best-effort for the same
            # reason - a full disk costs one repeated message, not the notice.
            try:
                core.save_config(cfg)
            except Exception:
                pass
            try:
                from cubeon import osnotify
                osnotify.update_available(version, cfg=cfg)
            except Exception:
                pass  # the toast is optional; the snackbar is the real notice
            _offer_update(info)
        except Exception:
            logging.getLogger(__name__).debug("update notice failed", exc_info=True)

    try:
        from cubeon import updater
        updater.check_in_background(_announce_update, token=cfg.get("update_token"))
    except Exception:
        logging.getLogger(__name__).warning("background worker error", exc_info=True)

    # -----------------------------------------------------------------
    # SEASONAL GREETING
    # Once per season per year: the "the season changed and the launcher
    # noticed" moment, which is the whole point of a seasonal update. It is
    # deliberately NON-modal (an informative card must never trap anyone),
    # skipped on a brand-new install (the onboarding dialog is already up -
    # two dialogs at once is how a first run feels broken), and every step is
    # guarded, because a missed greeting must never break startup.
    #
    # `season_seen` stores "2026-autumn"; seasonal.season_year() is what makes
    # winter greet ONCE across the December->January boundary instead of again
    # in January.
    # -----------------------------------------------------------------
    try:
        _greet_info = cubeon_seasonal.current()
        _greet_key = _greet_info.slug
        if ("onboarded" in cfg and _greet_info.seasonal
                and cfg.get("season_seen") != _greet_key):
            def _dismiss_greeting(e=None):
                cfg["season_seen"] = _greet_key
                try:
                    core.save_config(cfg)
                except Exception:
                    pass  # the greeting is already seen; a save failure is not
                _close_dialog(greet_dlg)

            def _open_seasonal_from_greeting(e=None):
                _dismiss_greeting()
                _open_seasonal_settings()

            greet_dlg = ft.AlertDialog(
                title=ft.Row(
                    [
                        ft.Image(src=season_pet_src(_greet_info), width=34,
                                 height=34, fit=ft.BoxFit.CONTAIN),
                        ft.Text(f"Happy {_greet_info.label.lower()}",
                                color=TEXT, font_family=FONT_DISPLAY, size=20),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                f"Autumn where you are, so Cubeon is wearing "
                                f"autumn colors - and a friend moved in."
                                if _greet_info.season == cubeon_seasonal.AUTUMN
                                else f"It's {_greet_info.label.lower()} in "
                                     f"{_greet_info.place}, so the launcher "
                                     f"changed with it.",
                                size=13, color=TEXT_DIM,
                            ),
                            ft.Text(cubeon_seasonal.describe_source(_greet_info),
                                    size=11.5, color=TEXT_FAINT),
                        ],
                        tight=True, spacing=10,
                    ),
                    width=380,
                ),
                actions=[
                    ft.TextButton("See what changed",
                                  on_click=_open_seasonal_from_greeting,
                                  style=ft.ButtonStyle(color=ACCENT)),
                    ft.TextButton("Nice", on_click=_dismiss_greeting,
                                  style=ft.ButtonStyle(color=TEXT_DIM)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            _open_dialog(greet_dlg)
    except Exception:
        pass  # a missed seasonal hello must not break startup

    # -----------------------------------------------------------------
    # CUBEON UPDATE CHECK (Phase 7)
    # The check itself ran once, early on (see UPDATE CHECK above): the toast
    # and the snackbar are two channels of ONE announcement, so there is
    # deliberately nothing here. A second check here was the "spam" half of
    # the 2026-10-18 report - it re-fetched the feed (without the update
    # token) purely to fire the OS toast, on top of the snackbar, on every
    # single start. The per-version marker now gates both.
    # -----------------------------------------------------------------

    # --- Clear the Discord activity when the launcher window closes ---
    # Without this, the "Playing / in the launcher" presence can linger on the
    # player's profile after they quit Cubeon. Best-effort and version-tolerant:
    # --- Window geometry persistence + close cleanup -----------------------
    # on_window_event was renamed on some Flet builds, so absent/odd behavior
    # just means the presence clears on the next launch instead.
    _geometry_timer = None  # debounce: resize/move fire a stream of events

    def _save_geometry_now():
        # Ignore move/close events emitted while the hidden splash/native
        # window still reports its placeholder geometry.
        if not _geometry_ready:
            return
        try:
            w = page.window
            # Fullscreen counts as maximized here: its rect is the whole
            # screen, and saving that would make the next fresh launch open
            # screen-sized-but-not-fullscreen.
            maximized = _is_chrome_maximized() or bool(_fullscreen["active"])
            if maximized:
                # Keep the last RESTORED geometry: the window manager's
                # un-maximize returns to its own remembered size, and saving
                # the maximized dimensions here would make the next fresh
                # launch open maximized-sized-but-not-maximized.
                prev = core.load_window_geometry()
                core.save_window_geometry(
                    prev.get("width") or w.width,
                    prev.get("height") or w.height,
                    prev.get("left"), prev.get("top"),
                    True)
            else:
                core.save_window_geometry(
                    w.width, w.height, w.left, w.top, False)
        except Exception:
            pass

    def _on_window_event(e):
        try:
            raw = getattr(e, "type", "") or getattr(e, "data", "")
            ev = str(getattr(raw, "value", raw)).split(".")[-1].lower()
            if ev in ("close", "hide", "disconnect"):
                # Flet 0.86 reality check: on this build the native X button
                # tears the window down WITHOUT delivering a "close" event to
                # Python (only programmatic window.close() does, and only
                # when prevent_close is set - which itself breaks real X
                # clicks). What actually arrives on a real KDE/GTK close is
                # "hide" (verified 2026-10-06); "close"/"disconnect" are what
                # Windows and programmatic close deliver.
                #
                # NEVER block here: this runs on flet's event loop, and any
                # hang in this handler freezes ft.run() itself - that is
                # exactly how the launcher used to end up alive with no
                # window. So save the geometry (cheap), let the client go so
                # ft.run() can return, and arm the watchdog as the fallback.
                _save_geometry_now()  # last chance: capture final state
                if ev in ("close", "disconnect"):
                    # The window is gone for real. End the desktop client so
                    # ft.run() - which waits on that process - returns and
                    # _session_loop can classify the end and honour a pending
                    # "Restart to apply" (it must NOT be skipped, which is
                    # why there is no os._exit() here).
                    try:
                        _kill_flet_client()
                    except Exception:
                        pass  # module-global under __main__; absent in tests
                # "hide" also fires on minimize, so the watchdog re-checks
                # that no flet client is left before it touches anything.
                _arm_window_gone_exit(f"window {ev}",
                                      delay=2.0 if ev == "hide" else 1.0)
            elif ev.replace("_", "-") in ("enter-full-screen",
                                           "leave-full-screen"):
                # A fullscreen change we did NOT make (the WM, a client-side
                # Escape, a macOS zoom) must not leave our flag - and with it
                # the resize handles and the geometry save - stale until the
                # next F11. Adopt the native state; never write it back (that
                # would ping-pong with the event that just arrived).
                _adopt_fullscreen_state(
                    ev.replace("_", "-") == "enter-full-screen")
            elif ev in ("resized", "resize", "move", "moved",
                        "maximize", "unmaximize", "rescale"):
                if ev in ("maximize", "unmaximize"):
                    # With the custom frame the glyph follows the NATIVE state,
                    # not our click: the drag area's double-click and Win+arrow
                    # maximize the window without the button ever being pressed.
                    _set_chrome_maximized(
                        winchrome.maximize_state(ev, _chrome_state["maximized"]))
                elif ev in ("resized", "resize", "rescale"):
                    # Belt-and-braces for a WM that ignored our maximize on a
                    # hidden window (the "maximized but it isn't / can't
                    # resize" report): the first real resize event is our
                    # chance to adopt what the OS actually did.
                    native = _native_maximized()
                    if native is not None and native != _chrome_state["maximized"]:
                        _set_chrome_maximized(native)
                # Debounced: dragging the window fires dozens of events, and
                # each save is a tiny file write. Saving 400ms after the last
                # event is plenty; a crash mid-drag only loses the last tweak.
                # "moved" is flet's post-drag spelling - without it in this
                # tuple positions were never captured, and the session-end
                # save persisted a placeholder ("always top-left" report).
                nonlocal _geometry_timer
                if _geometry_timer is not None:
                    _geometry_timer.cancel()
                _geometry_timer = threading.Timer(0.4, _save_geometry_now)
                _geometry_timer.daemon = True
                _geometry_timer.start()
        except Exception:
            pass

    # Flet 0.86: window events live on page.window.on_event (Page.on_window_event
    # was removed; assigning it silently did nothing, so close-time cleanup
    # never actually ran on this build). e.type is a WindowEventType enum.
    try:
        page.window.on_event = _on_window_event
    except Exception:
        pass

    # The RELIABLE "the client is gone" signal, on every flet build we ship.
    #
    # Verified on BOTH flet 0.86.5 (the Windows build) and 1.0.3, 2026-10-06:
    # when the desktop client dies, flet's socket server calls session.close(),
    # which dispatches the PAGE-level "close" event. page.on_disconnect is
    # NEVER dispatched - Session.disconnect() has no callers at all in either
    # build - so wiring on_disconnect alone left the process running forever
    # with no window (the background bug). on_disconnect is still wired below
    # because some builds/web do deliver it; the handler is idempotent.
    #
    # It only saves geometry and arms the watchdog: the real exit happens in
    # _window_gone_finish if ft.run() never comes back, and otherwise the
    # session loop does it (which is what keeps "Restart to apply" working).
    def _on_page_gone(_e):
        try:
            _save_geometry_now()
        except Exception:
            pass
        _arm_window_gone_exit("page closed", delay=2.0)

    for _hook in ("on_close", "on_disconnect"):
        try:
            setattr(page, _hook, _on_page_gone)
        except Exception:
            pass

    # End-of-session cleanup callable, executed by the __main__ block right
    # after ft.run returns (the only reliable "window session ended" moment
    # on this build - see the long note there). A session end means the
    # process is on its way out, so everything process-scoped is stopped
    # here - there is no windowless "background" state to stay alive for.
    def _do_session_end_cleanup():
        _save_geometry_now()
        _rpc.clear()
        _rpc.close()
        # The winter leaves must stop falling when the window is gone: the
        # seasonal ticker is a per-session thread and there is no window
        # left to animate.
        try:
            season_animator.stop()
        except Exception:
            pass  # a stopped ticker is not worth an error on the way out
        # The session's page is gone; the process-scoped controller watcher
        # must stop routing events at it.
        _session_runtime["controller_page"] = None
        _session_runtime["controller_handlers"] = None
        try:
            friends_service.stop()
        except Exception:
            pass

    # Module-level _session_end is defined near the top of the file (it
    # must exist when main() runs under any entry point, including the
    # test harness which imports main as a module).
    _session_end["handler"] = _do_session_end_cleanup

    # "Restart to apply" (Settings > Seasonal) arms a request event; the
    # session loop checks it the moment ft.run returns and re-execs into a
    # fresh launcher (see _session_loop).
    if _relaunch["request"] is None:
        _relaunch["request"] = threading.Event()

    # --- Keyboard shortcuts ------------------------------------------------
    # One dispatcher for the whole app (table + policy: cubeon/shortcuts.py).
    # It runs on flet's event loop and every action also has a mouse path (the
    # preview ✕, the nav icons, the Settings button, the big button), so the
    # whole handler is best-effort: a bad payload or a missing control must
    # never be able to take the UI down. F12 (inspector) stays here rather
    # than in the table - it is a dev tool behind the CUBEON_INSPECT gate.
    _shortcuts_dlg = {"dlg": None}

    def _dialog_mounted(dlg):
        """Is `dlg` currently in the page's dialog stack?

        Membership, not `.open`: flet removes a barrier-dismissed dialog from
        its stack WITHOUT clearing the flag, and show_dialog() RAISES for one
        that is still mounted (see InstancesManager._is_mounted, ui/versions.py).
        """
        if dlg is None:
            return False
        stack = getattr(getattr(page, "_dialogs", None), "controls", None)
        if stack is None:
            return bool(getattr(dlg, "open", False))
        return dlg in list(stack)

    def _shortcut_row(combo, what):
        return ft.Row(
            [
                ft.Container(
                    content=ft.Text(combo, size=11.5, color=ACCENT,
                                    font_family=FONT_MONO,
                                    weight=ft.FontWeight.W_600),
                    bgcolor=ACCENT_TINT, border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=8,
                                                         vertical=4),
                    width=132,
                ),
                ft.Text(what, size=12.5, color=TEXT_DIM, expand=True),
            ],
            spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _show_shortcuts(e=None):
        """F1: the shortcut list. Toggles, so the same key dismisses it.

        Built once and reused - the list is static, and rebuilding per press
        would just stack dialog objects. Opened through cubeon_dialogs so it
        mounts exactly like every other dialog in the app.
        """
        try:
            dlg = _shortcuts_dlg["dlg"]
            if dlg is None:
                dlg = ft.AlertDialog(
                    modal=False, bgcolor=SURFACE,
                    title=ft.Text("Keyboard shortcuts", color=TEXT,
                                  weight=ft.FontWeight.W_800),
                    content=ft.Container(
                        width=440,
                        content=ft.Column(
                            [_shortcut_row(combo, what)
                             for combo, what in cubeon_shortcuts.CATALOGUE],
                            spacing=10, tight=True),
                    ),
                    actions=[ft.TextButton(
                        "Close",
                        on_click=lambda _e, d=dlg: cubeon_dialogs.close_dialog(page, d))],
                )
                _shortcuts_dlg["dlg"] = dlg
            if _dialog_mounted(dlg):
                cubeon_dialogs.close_dialog(page, dlg)
            else:
                cubeon_dialogs.open_dialog(page, dlg)
        except Exception:
            pass

    def _jump_to_tab(index):
        """Ctrl+N: switch to the Nth top-bar tab (1-based).

        Indexed off `top_nav_items` instead of a hardcoded table, so the
        numbering always matches what the user actually sees - the Chat tab
        only exists in Friend-enabled builds.
        """
        try:
            n = int(index)
        except (TypeError, ValueError):
            return
        if 1 <= n <= len(top_nav_items):
            switch_tab(top_nav_items[n - 1][0])

    def _on_key(e):
        try:
            # flet 0.86+ spells the payload `key`; keeps `data` as a fallback
            # for older builds. The modifier attributes have been spelled both
            # `ctrl` and `control` across releases, so read both.
            key = getattr(e, "key", "") or getattr(e, "data", "")
            action = cubeon_shortcuts.resolve(
                key,
                ctrl=bool(getattr(e, "ctrl", False)
                          or getattr(e, "control", False)),
                alt=bool(getattr(e, "alt", False)),
                shift=bool(getattr(e, "shift", False)),
                meta=bool(getattr(e, "meta", False)),
            )
            if action is None:
                if str(key) == "F12" and _inspector_enabled:
                    _open_inspector()
                return
            if action == cubeon_shortcuts.ESCAPE:
                # Close the topmost thing, the way Escape is expected to
                # behave: the help dialog, then fullscreen, then the panel.
                if _dialog_mounted(_shortcuts_dlg["dlg"]):
                    cubeon_dialogs.close_dialog(page, _shortcuts_dlg["dlg"])
                elif _fullscreen["active"]:
                    _set_fullscreen(False)
                elif account_panel.right == 0:
                    _close_account_panel()
            elif action == cubeon_shortcuts.FULLSCREEN:
                _toggle_fullscreen()
            elif action == cubeon_shortcuts.HELP:
                _show_shortcuts()
            elif action == cubeon_shortcuts.SETTINGS:
                switch_tab("settings")
            elif action == cubeon_shortcuts.MAIN_ACTION:
                # Only when the big button is actually actionable: the mouse
                # path is blocked by `disabled`, and the keyboard must not be
                # a way around a disabled Play (incomplete install, launching,
                # a running game...). Whatever is live is handled by
                # _main_action_click's own state routing.
                if not play_button.disabled:
                    _main_action_click()
            elif action == cubeon_shortcuts.QUIT:
                _chrome_close()
            else:
                tab = cubeon_shortcuts.tab_index(action)
                if tab:
                    _jump_to_tab(tab)
        except Exception:
            pass
    try:
        page.on_keyboard_event = _on_key
    except Exception:
        pass



def run_sync(page) -> None:
    """Build the launcher against `page` on a private event loop.

    A convenience for the test/tool harnesses: Flet awaits main() on its own
    loop, but they build the UI from a plain synchronous script, so they need
    the coroutine driven to completion here. Never used by a real launch - do
    not call it from inside a running loop.
    """
    asyncio.run(main(page))


# This is the standard Python entry point - when the script is run directly, start the Flet app.
if __name__ == "__main__":

    # Crash forensics start HERE, not in main(). setup_logging() used to be
    # reached only from main() - the flet SESSION callback - so a client that
    # died BEFORE the window ever painted left NOTHING in cubeon.log. That is
    # exactly the crash reported on 2026-10-18 (KDE's crash reporter showed
    # "flet ... encountered a fatal error and was closed"): the whole event
    # was invisible to us, and the only evidence in existence was a
    # screenshot. Idempotent, so main()'s later call becomes a no-op.
    from cubeon.logging_setup import setup_logging as _setup_logging
    _setup_logging()
    from cubeon import incident as _incident

    # Silence GTK's accessibility bridge on the flet client. It fails to
    # plug into AT-SPI on KDE/X11 and prints
    #   (flet:N): Atk-CRITICAL **: atk_socket_embed: assertion 'plug_id != NULL' failed
    # on nearly every launch - including perfectly working ones. Pure noise;
    # NO_AT_BRIDGE stops GTK from loading the broken bridge at all. Set
    # BEFORE ft.run() so the client inherits it (flet passes os.environ
    # to the client process).
    if sys.platform.startswith("linux"):
        os.environ.setdefault("NO_AT_BRIDGE", "1")

    # The atk-bridge env alone doesn't stop the flet client's GTK a11y
    # socket from printing
    #   Atk-CRITICAL **: atk_socket_embed: assertion 'plug_id != NULL'
    # to inherited stderr on every launch (a KDE/X11 cosmetic - the socket
    # has no atk-bridge to plug into; the window works fine). The client's
    # stderr is inherited, so we wrap flet_desktop's spawn just enough to
    # stream it through a drop-filter: everything that isn't that one
    # known-harmless line still reaches the log. Restored to the real
    # stream so genuine client errors (GL timeouts, engine failures)
    # keep arriving.
    import flet_desktop as _flet_desktop
    _real_open_view_async = _flet_desktop.open_flet_view_async
    _ATK_NOISE = re.compile(
        r"Atk-CRITICAL|atk_socket_embed|plug_id != NULL")
    # The flet client logs this line for every OpenGL frame it fails to
    # produce within the timeout. One of them at startup is a slow driver
    # warm-up; a steady stream is the wedged-driver state (see
    # _wedge_watchdog below).
    _GL_FRAME_TIMEOUT = re.compile(
        r"Timed out waiting for OpenGL frame")

    # --- Wedge watchdog ---------------------------------------------------
    # The flet client's failure mode is normally a CRASH (signal death ->
    # ft.run returns -> _classify_session_end -> software-GL retry ladder).
    # But it can also WEDGE instead: window mapped, not a single frame
    # rendered, ~180% CPU spinning, and ft.run never returning. In that
    # state every recovery mechanism in _session_loop is unreachable (it
    # all lives after ft.run returns), and the
    # user is left with a zombie window - observed live on 2026-09-19
    # (Mesa 26.1 / AMD Polaris) right after a restart re-exec. The wedge
    # reproduces even AFTER _reveal_window has run: the marker proves the
    # reveal task executed, not that frames flow (measured: marker written
    # at T, "no OpenGL frame" timeouts at T+0.6s, T+0.7s, client frozen
    # indefinitely).
    #
    # The fix is NOT to tear down the session from a side thread (ft.run
    # is not re-entrant); it is to kill the wedged client. Its death makes
    # ft.run return normally, and the EXISTING classified recovery ladder
    # takes over: pre-paint -> software-GL retry; painted-but-dead ->
    # mid-session re-exec.
    #
    # The judgment is pure evidence from the client itself - it logs
    # "Timed out waiting for OpenGL frame" for every frame it fails to
    # produce. Kill requires ALL of:
    #   >= _WEDGE_TIMEOUTS timeouts since THIS client spawned,
    #   the newest one within _WEDGE_RECENT seconds of now (it is failing
    #     right now, not historically),
    #   the client is between _WEDGE_GRACE and _WEDGE_WINDOW old.
    # A healthy client emits none of these lines; a merely slow one emits
    # one or two (each costs 10s of no-frame time). Three fresh ones in
    # the first minute means the rasterizer is producing nothing and the
    # window is already frozen - the kill only changes what the user
    # watches: a restart attempt instead of a dead picture. After
    # _WEDGE_WINDOW the client is considered stable; a later wedge is the
    # (much rarer) mid-session case left to its own path.
    _wedge_lock = threading.Lock()
    # pid/armed_at None = no live client being judged; set on each spawn.
    # "stamps" are the recent GL-frame timeout times (monotonic), pruned to
    # _WEDGE_RECENT - the BURST test below reads them.
    _wedge_state = {"stamps": [], "pid": None, "armed_at": None}
    _WEDGE_GRACE = 12.0    # min client age before judging
    _WEDGE_WINDOW = 60.0   # only judge a client this early in its life
    # The numbers below are NOT guesses - they come from the measured
    # signature of a real wedge on this machine (2026-09-19, Mesa 26.1 /
    # AMD Polaris). A wedged client emits its GL-frame timeouts as a short
    # BURST and then goes silent forever while burning CPU:
    #   rt2.log ghost 29728: 2 lines 0.155s apart, then silent 34+ min
    #   rt.log  slave 22385: 2 lines 0.216s apart, then silent
    #   rt.log  slaves 22020/22263: 1 line each, then killed by the next
    #                                restart
    # So the burst length is TWO (a threshold of 3 could never fire - the
    # original value was dead code). The burst GAP matters just as much:
    # each timeout line means 10s of no frame, so a merely SLOW client also
    # emits several - but spaced ~10s apart, one per failed frame. Only a
    # client that is producing NOTHING emits them seconds apart, and THAT
    # is the wedge. Without the gap test, two slow frames in the first
    # minute killed a healthy session and the recovery ladder immediately
    # reopened Cubeon - the "it reopens after I close it" bug.
    # Tradeoff, stated plainly: a false positive costs one automatic
    # session restart (the client is killed and ft.run returns, so the
    # EXISTING recovery ladder runs); a false negative is a frozen window
    # the user can never dismiss and a launcher that can never be reopened.
    # Erring toward the restart is correct - but only for the real burst.
    _WEDGE_TIMEOUTS = 2    # GL-frame timeout lines required (measured: 2)
    _WEDGE_RECENT = 25.0   # newest timeout must be this fresh
    _WEDGE_BURST_GAP = 4.0  # two stamps must be closer than this (measured: ~0.2s)
    _WEDGE_ESCALATE = 3.0  # SIGTERM -> SIGKILL wait

    def _wedge_note_gl_timeout():
        with _wedge_lock:
            now = time.monotonic()
            stamps = [t for t in _wedge_state["stamps"]
                      if now - t <= _WEDGE_RECENT]
            stamps.append(now)
            _wedge_state["stamps"] = stamps[-8:]

    def _wedge_arm(pid):
        with _wedge_lock:
            _wedge_state["pid"] = pid
            _wedge_state["armed_at"] = time.monotonic()
            _wedge_state["stamps"] = []

    def _wedge_disarm():
        with _wedge_lock:
            _wedge_state["pid"] = None
            _wedge_state["armed_at"] = None
            _wedge_state["stamps"] = []

    def _wedge_watchdog():
        # One daemon for the whole process life: wait for a client, judge
        # it once, then loop for the next session/retry/re-exec client.
        while True:
            with _wedge_lock:
                pid, armed_at = (_wedge_state["pid"],
                                 _wedge_state["armed_at"])
            if pid is None or armed_at is None:
                time.sleep(0.25)
                continue
            now = time.monotonic()
            age = now - armed_at
            with _wedge_lock:
                pid, stamps = (_wedge_state["pid"],
                               list(_wedge_state["stamps"]))
            if pid is None:
                continue  # disarmed between reads; take the next client
            if age > _WEDGE_WINDOW:
                _wedge_disarm()  # stable client; done judging this one
                continue
            stamps = [t for t in stamps if now - t <= _WEDGE_RECENT]
            burst = (len(stamps) >= _WEDGE_TIMEOUTS
                     and (stamps[-1] - stamps[-2]) <= _WEDGE_BURST_GAP)
            if (age >= _WEDGE_GRACE and burst
                    and now - stamps[-1] <= _WEDGE_RECENT):
                # Wedged: kill so ft.run returns and the classified
                # recovery ladder restarts the session.
                print("cubeon: client is producing no OpenGL frames - "
                      "treating the wedged driver as a crash and "
                      "restarting the session", flush=True)
                killed = False
                try:
                    os.kill(pid, 0)
                    try:
                        os.kill(pid, signal.SIGTERM)
                        killed = True
                    except OSError:
                        pass
                except OSError:
                    pass  # client gone on its own already
                _wedge_disarm()
                if killed:
                    escalate_at = time.monotonic() + _WEDGE_ESCALATE
                    while time.monotonic() < escalate_at:
                        try:
                            os.kill(pid, 0)
                        except OSError:
                            break  # took the polite exit
                        time.sleep(0.1)
                    else:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except OSError:
                            pass
                continue
            time.sleep(0.5)

    _wedge_thread = threading.Thread(
        target=_wedge_watchdog, daemon=True, name="cubeon-wedge-watchdog")
    _wedge_thread.start()

    # The tail of the CURRENT client's own output, kept for the crash record
    # (cubeon/incident.py). main.py's filter below is the only place that text
    # passes through, and stdout is not somewhere a user can send us from.
    _client_tail = _incident.ClientOutputTail()

    async def _filtered_open_flet_view_async(page_url, assets_dir, hidden):
        args, flet_env, pid_file = \
            _flet_desktop.__locate_and_unpack_flet_view(
                page_url, assets_dir, hidden)
        # The flet.exe client must not flash its own console either
        # (asyncio passes kwargs to the underlying subprocess on Windows).
        from cubeon.winproc import hidden as _hidden_kw
        proc = await asyncio.create_subprocess_exec(
            args[0], *args[1:], env=flet_env,
            # Capture BOTH streams and merge them (stderr -> stdout) so the
            # wedge detector below can never be defeated by which fd a
            # message happens to land on. The GL-frame warnings are GLib
            # `** (flet:N): WARNING **` lines (they arrive on stderr in the
            # wild - measured 2026-09-19), but a fake/replacement client,
            # or any upstream logging change, can print to stdout. A
            # detector that only watched stderr looked correct while
            # silently never firing once already; one pipe, no assumption.
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **_hidden_kw(),
        )
        # Fresh client: (re)start the wedge judgment window for it. Any
        # previous client is already gone by the time flet spawns the next.
        _wedge_arm(proc.pid)

        async def _filter_client_output():
            # Async pipe: must be read with await readline() (a sync read
            # here leaves the coroutine un-awaited and eats ALL client
            # output instead of filtering it).
            # Destination is the real stderr (unchanged from when only
            # stderr was filtered) with an explicit flush: the merged pipe
            # is block-buffered whenever the launcher's own stdout is not a
            # tty, which would otherwise hold diagnostic lines back.
            try:
                while True:
                    raw = await proc.stdout.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", "replace")
                    if _ATK_NOISE.search(line):
                        continue
                    # Keep the tail for the crash record before anything else
                    # looks at the line: the client's own last words are the
                    # only place a Mesa/GTK/wayland library name shows up.
                    _client_tail.add(line)
                    if _GL_FRAME_TIMEOUT.search(line):
                        # The client announces every OpenGL frame it failed
                        # to produce. A burst of these with no painted
                        # window is the wedged-driver state (measured live
                        # 2026-09-19: window mapped, zero frames, ~180% CPU,
                        # ft.run never returning - so NOTHING downstream
                        # could recover). The wedge watchdog turns the
                        # burst into a session restart.
                        try:
                            _wedge_note_gl_timeout()
                        except Exception:
                            pass
                    try:
                        sys.__stderr__.write(line)
                        sys.__stderr__.flush()
                    except Exception:
                        pass
            except Exception:
                pass

        asyncio.get_running_loop().create_task(_filter_client_output())
        return proc, pid_file

    _flet_desktop.open_flet_view_async = _filtered_open_flet_view_async

    # assets_dir tells Flet where "..." src paths (window icon, sidebar
    # logo) resolve to on disk. Paths in src= are relative to this folder
    # itself - e.g. src="icon.svg" resolves to assets/icon.svg on disk.
    # (Using src="assets/icon.svg" here would double the path and fail.)
    #
    # Built as an ABSOLUTE path from this script's own location rather than
    # the relative string "assets" - a relative path only resolves correctly
    # if the app happens to be launched with the project folder as the
    # current working directory. Launched any other way (a shortcut, an
    # IDE run config, `python /some/other/path/main.py`), Flet can't find
    # the assets folder, silently fails to load icon.svg, and the sidebar
    # logo falls back to a generic placeholder glyph instead of the real
    # Cubeon mark. An absolute path always resolves correctly regardless of
    # cwd at launch time.
    _assets_dir = resolve_assets_dir()

    # --- GPU-crash auto-recovery -------------------------------------------
    # The flet client may die to a driver bug (observed: AMD Polaris +
    # Mesa 26.1 gallium, SIGSEGV inside libgallium on first frame - both
    # hardware AND llvmpipe paths, flaky). Nothing in this repo can fix a
    # system driver, but the launcher can refuse to stay dead:
    #
    #   attempt 1: normal launch (hardware GL)
    #   client dies pre-paint -> relaunch with software GL
    #   client dies again pre-paint -> relaunch ONCE more with software GL
    #                                  (llvmpipe is usually reliable; a
    #                                  second try gets past the flakiness)
    #   dies a third time / user closes normally -> give up, exit
    #
    # A clean session (window painted, then closed) resets the counter, so
    # every launch gets fresh chances.
    from cubeon.paths import CUBEON_HOME as _CUBEON_HOME
    _gl_fallback_marker = os.path.join(_CUBEON_HOME, "use_software_gl")

    # Set once the UI is actually up (see _reveal_window); checked after
    # ft.run returns to tell a clean close from a pre-paint GPU crash.
    _ui_up_marker = os.path.join(_CUBEON_HOME, "ui_painted_ok")

    # --- Clean shutdown state (shared with main()) --------------------------
    # Flet 0.86 delivers NO window events to Python on the real X button
    # (proven on live X11/KDE - see the window-event note in main()). So
    # end-of-session cleanup (Discord presence clear, friends disconnect,
    # geometry save) cannot live in an event handler; it runs HERE, right
    # after ft.run returns in the main thread, which is the one moment that
    # reliably means "the window session just ended".
    # (the cleanup slot itself is module-level; see its definition near the
    # imports. This local copy was a duplicate - removed.)
    _MAX_CLIENT_RETRIES = 2
    # Mid-session GPU-crash re-execs (see the ui_painted-but-client-dead
    # branch in _session_loop). Each restart bumps CUBEON_GPU_RESTARTS in the
    # environment, which survives execv; a clean close resets it.
    _MAX_MIDSESSION_RESTARTS = 2

    # The flet client's exit status for the session that just ended, filled by
    # the capture installed below. 0 = normal close, negative = signal death.
    _last_client_exit = {"code": None}
    _capture_flet_client_exit(_last_client_exit)


    def _run_flet_once():
        ft.run(main, assets_dir=_assets_dir, view=ft.AppView.FLET_APP_HIDDEN)

    # session_loop: run flet sessions until the process should end.
    #
    #   run session -> crashed pre-paint? retry (up to 2) with software GL
    #   session painted + user closed: exit (a clean close ends the process)
    #
    # Note the X button DESTROYS the window session on Flet 0.86/GTK and
    # delivers no "close" event to Python, so there is nothing to re-show -
    # a closed window is always the end of this process, never a park. That
    # is also why window.prevent_close is never set: it stops the window
    # closing at all, i.e. the user cannot quit.
    def _kill_flet_client():
        """Ends the flet desktop client left over from a finished session.

        Flet 0.86 cannot remove its implicit view (the client logs
        "FlutterEngineRemoveView returned kInvalidArguments - the implicit
        view cannot be removed" on the X button). The Python session ends,
        but the CLIENT PROCESS stays alive with its window still mapped,
        now showing the engine's disconnected placeholder - a bare spinner
        and "Working...". So after closing the launcher the user was left
        staring at a ghost window that belongs to no session, which looks
        exactly as broken as it is.

        ft.run() doesn't clean that up (it owns a pid file under a random
        temp name we're not given), so the client is found the direct way:
        our own child processes named "flet". Matching on the name matters
        - Minecraft is a child of this process too (comm "java") and must
        never be touched by this.
        """
        if not os.path.isdir("/proc"):
            # Windows/macOS have no /proc, but the same ghost can survive a
            # close there - and on Windows the flet client is the thing users
            # see as "Cubeon still running in the background". Find our flet
            # client with psutil (a dependency) and end it. Two-factor match
            # (our child, or our assets dir in its command line) so another
            # live Cubeon instance is never touched; the "flet" name filter
            # excludes Minecraft (java).
            try:
                import psutil
            except Exception:
                return False
            me = os.getpid()
            victims = []
            for proc in psutil.process_iter(
                    ["pid", "name", "ppid", "cmdline"]):
                try:
                    info = proc.info
                    if "flet" not in (info.get("name") or "").lower():
                        continue
                    cmdline = " ".join(info.get("cmdline") or [])
                    if info.get("ppid") == me or (
                            _assets_dir and _assets_dir in cmdline):
                        victims.append(info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if not victims:
                return False
            for pid in victims:
                try:
                    psutil.Process(pid).terminate()
                except Exception:
                    pass
            time.sleep(0.5)
            for pid in victims:
                try:
                    proc = psutil.Process(pid)
                    if proc.is_running():
                        proc.kill()
                except Exception:
                    pass
            return True
        me = os.getpid()
        victims = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat", "rb") as fh:
                    head, _, tail = fh.read().rpartition(b")")
                comm = head.partition(b"(")[2].decode("utf-8", "replace")
                fields = tail.split()
                ppid = int(fields[1])
                state = fields[0].decode("ascii", "replace")
            except (OSError, IndexError, ValueError):
                continue  # process vanished mid-read, or an odd stat line
            if ppid == me and comm == "flet":
                # A zombie already exited - nothing to kill. (On flet 0.86 the
                # client is normally reaped by ft.run before we get here, so
                # this scan is a safety net; the session is classified by exit
                # status, not by what this finds.)
                if state == "Z":
                    continue
                victims.append(int(entry))
        # Orphan sweep: a "flet" client whose parent is gone or is not a
        # launcher is a ghost from a DEAD Cubeon run - the launcher that
        # spawned it died before _kill_flet_client could run, and the
        # client was reparented (to systemd --user here), window still
        # mapped, CPU still burning. Measured live 2026-09-19: four ghost
        # windows on screen from three dead launchers. Identification is
        # two-factor so a healthy second instance is never touched:
        #   1. our assets dir must appear in the client's args;
        #   2. the parent must NOT be a live launcher (python/main.py or
        #      a process named like Cubeon). A reparented-to-systemd
        #      client or one whose parent vanished is a ghost; a client
        #      whose parent is a live launcher is another instance's
        #      working window.
        if _assets_dir:
            orphans = []
            for entry in list(os.listdir("/proc")):
                if not entry.isdigit() or int(entry) in victims:
                    continue
                try:
                    with open(f"/proc/{entry}/stat", "rb") as fh:
                        head, _, tail = fh.read().rpartition(b")")
                    comm = head.partition(b"(")[2].decode(
                        "utf-8", "replace")
                    fields = tail.split()
                    ppid = int(fields[1])
                    state = fields[0].decode("ascii", "replace")
                    if comm != "flet" or state == "Z" or ppid == me:
                        continue
                    with open(f"/proc/{entry}/cmdline", "rb") as fh:
                        args = fh.read().decode("utf-8", "replace")
                    if _assets_dir not in args:
                        continue  # not this app's client
                    with open(f"/proc/{ppid}/cmdline", "rb") as fh:
                        parent = (fh.read().decode("utf-8", "replace")
                                  .replace("\x00", " "))
                except OSError:
                    continue  # gone mid-read; catch it next sweep
                if "main.py" in parent or "cubeon" in parent.lower():
                    continue  # a live launcher owns it
                print(f"cubeon: sweeping an orphaned flet client left "
                      f"behind by a dead launcher (pid {entry})",
                      flush=True)
                orphans.append(int(entry))
            victims.extend(orphans)

        if not victims:
            return False
        for pid in victims:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        # Give the client its polite exit, then insist. A GPU-wedged client
        # ignoring SIGTERM must not keep the ghost window on screen.
        deadline = time.monotonic() + 2.0
        for pid in victims:
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
                time.sleep(0.05)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        return True

    def _session_loop():
        while True:
            _retries = 0
            while True:
                if os.path.exists(_gl_fallback_marker):
                    # How many client attempts have already died. The
                    # in-process pre-paint retries know their own count; a
                    # re-exec'd mid-session restart carries it forward in
                    # CUBEON_GPU_RESTARTS (the fresh process starts at
                    # _retries == 0). The DRIVER depends on it - llvmpipe
                    # first, then softpipe - because the 2026-10-18 crash is
                    # in the LLVM rasterizer llvmpipe shares with radeonsi:
                    # see incident.driver_for_attempt.
                    try:
                        _failed_attempts = max(
                            _retries, int(os.environ.get(
                                "CUBEON_GPU_RESTARTS", "0") or "0"))
                    except ValueError:
                        _failed_attempts = _retries
                    # retry_environment also carries a dice roll on the OTHER
                    # way the flet client dies on Linux (the GTK/Wayland path)
                    # - only here, after a crash, and only when it can help:
                    # incident.wayland_x11_fallback keeps a working Wayland
                    # session native.
                    for _fk, _fv in _incident.retry_environment(
                            _failed_attempts).items():
                        if os.environ.get(_fk) != _fv:
                            os.environ[_fk] = _fv
                            print(f"cubeon: retrying with {_fk}={_fv}")

                # Each attempt needs a clean per-run marker state, a fresh slot
                # for the client's exit status, and an empty output tail (the
                # client about to start writes its own).
                try:
                    if os.path.exists(_ui_up_marker):
                        os.remove(_ui_up_marker)
                except OSError:
                    pass
                _last_client_exit["code"] = None
                _client_tail.clear()

                # A fresh session is also the natural place to reap the
                # ghosts of dead launchers (frozen client windows whose
                # parent died) - see the orphan sweep in _kill_flet_client.
                # Doing it HERE means the ghosts vanish the moment the new
                # session comes up, not when it closes again.
                _kill_flet_client()

                # FLET_APP_HIDDEN: the desktop client starts with its window
                # hidden, so the only transition the user sees is the single
                # reveal of the finished UI in _reveal_window.
                #
                # session_ended_at is stamped the moment ft.run returns; the
                # park logic below uses it to tell a reopen click that came
                # AFTER the user closed the window (honor it) from a stray
                # one made earlier in the session (ignore it). It can't use
                # "is a session running?" for that: ft.run keeps running for
                # a second or two of teardown after the window is gone, and
                # a click in that gap is the most common one there is.
                try:
                    # Fresh session: re-arm the window-gone watchdog (it was
                    # disarmed when the previous ft.run() returned) and drop
                    # any timer left over from that session.
                    _window_gone["ft_returned"] = False
                    _window_gone["dismissed_at"] = None
                    if _window_gone.get("timer") is not None:
                        try:
                            _window_gone["timer"].cancel()
                        except Exception:
                            pass
                        _window_gone["timer"] = None
                    _run_flet_once()
                except RuntimeError as _ex:
                    # Narrow, known teardown race: ^C delivered in the sliver
                    # between flet closing its asyncio loop and ft.run
                    # returning makes exit_gracefully raise "Event loop is
                    # closed" from inside the signal handler, unwinding ft.run
                    # itself. The session is over either way - classify it
                    # normally instead of dying with a cubeon.fatal CRITICAL.
                    if "Event loop is closed" not in str(_ex):
                        raise

                # From here on THIS process owns the exit: the window-gone
                # watchdog must not fire (it only exists for the case where
                # ft.run() never returns).
                _window_gone["ft_returned"] = True

                # flet's exit_gracefully handler is still installed but now
                # points at a closed loop - reclaim both signals before ANY
                # teardown code runs (see _reclaim_session_signals; a ^C in
                # _ct.join below used to raise out of the signal handler and
                # escape as a cubeon.fatal CRITICAL).
                _reclaim_session_signals()

                # First thing, before any cleanup: get rid of any leftover
                # ghost window (see _kill_flet_client). The flet 0.86 client is
                # normally already reaped by the time ft.run returns, so this is
                # just a safety net and its result no longer classifies the end.
                _kill_flet_client()

                # CUBEON_PERF=1: dump the repaint table for the session that
                # just ended. Printed HERE, not from atexit, because this
                # process leaves via os._exit/execv - atexit never runs.
                if os.environ.get("CUBEON_PERF"):
                    print(thread_safe_ui.perf_report()
                          or "cubeon repaint profile: no repaints recorded")

                # A pending "Restart to apply" (Settings > Seasonal) outranks
                # every session-end classification: the ghost client is already
                # reaped above, so this execv cannot strand one. It goes
                # straight to the fresh launcher - no GL-fallback retry, no
                # parking; if re-exec itself fails there is no good in-process
                # recovery left (ft.run is once-per-process), so exit.
                _rl = _relaunch.get("request")
                if _rl is not None and _rl.is_set():
                    print("cubeon: restart requested - relaunching to apply "
                          "seasonal settings")
                    try:
                        _relaunch_fresh_process()
                    except Exception as ex:
                        print(f"cubeon: relaunch via re-exec failed ({ex})")
                    return  # nothing sane left in this process

                _cleanup = _session_end["handler"]
                _session_end["handler"] = None

                def _run_cleanup():
                    try:
                        if _cleanup is not None:
                            _cleanup()
                    except Exception:
                        pass

                # Watchdogged: native teardown (discord IPC,
                # friends WS) can deadlock - observed the whole process
                # hanging in futex_wait during exit on KDE.
                _ct = threading.Thread(target=_run_cleanup, daemon=True,
                                       name="cubeon-exit-cleanup")
                _ct.start()
                _ct.join(timeout=3.0)

                # ft.run returned. Classify WHY from the client's exit status
                # (captured while flet reaped it): a normal close exits 0, a
                # driver crash dies to a signal (-11 SIGSEGV, ...). See
                # _classify_session_end for the full contract.
                try:
                    ui_painted = os.path.exists(_ui_up_marker)
                    if ui_painted:
                        os.remove(_ui_up_marker)
                except OSError:
                    ui_painted = False

                _session_end_kind = _classify_session_end(
                    ui_painted, _last_client_exit["code"])
                # If the user already dismissed the window (close/hide/
                # disconnect), a signal death during teardown is NOT a crash to
                # recover from - it would re-exec the launcher and pop the
                # window back up right after the user closed it.
                _session_end_kind = _apply_dismissed_close(
                    _session_end_kind, _window_gone.get("dismissed_at"),
                    time.monotonic())

                # Record WHY this session ended, in cubeon.log, for every
                # kind - including the clean close, so support can tell "the
                # user closed it" from "cubeon.log just stops here". This is
                # the line the 2026-10-18 crash report could not contain:
                # before it, a client signal death was a print() to stdout
                # that nobody launching from a menu could see or send us.
                _incident.record_session_end(
                    _session_end_kind, _last_client_exit["code"], ui_painted,
                    _client_tail.lines())

                if _session_end_kind == "clean_close":
                    # Real user close: clear any crash-fallback flag so the
                    # next session retries hardware GL (driver may be fixed),
                    # and reset the mid-session restart budget.
                    try:
                        if os.path.exists(_gl_fallback_marker):
                            os.remove(_gl_fallback_marker)
                            print("cubeon: clean session - hardware OpenGL re-enabled")
                    except OSError:
                        pass
                    os.environ.pop("CUBEON_GPU_RESTARTS", None)
                    return  # a clean close ends this process

                if _session_end_kind == "mid_session_crash":
                    # The window HAD painted, but the client died to a signal:
                    # a mid-session crash (observed live 2026-09-08: Mesa
                    # 26.1 SIGSEGV inside libgallium during a GTK paint).
                    # ft.run is ONCE-per-process - a second one hangs silently
                    # - so the in-process retry below is NOT an option here.
                    # Recovery is a wholesale process replacement instead: arm
                    # the software-GL fallback so the fresh image doesn't hit
                    # the same driver bug, and re-exec.
                    # Bounded by CUBEON_GPU_RESTARTS so a wedged driver can
                    # never turn this into an infinite relaunch loop; on
                    # exhaustion we exit, exactly as if the user had closed
                    # the window.
                    try:
                        _gpu_restarts = int(os.environ.get(
                            "CUBEON_GPU_RESTARTS", "0")) + 1
                    except ValueError:
                        _gpu_restarts = 1
                    if _gpu_restarts <= _MAX_MIDSESSION_RESTARTS:
                        try:
                            os.makedirs(_CUBEON_HOME, exist_ok=True)
                            open(_gl_fallback_marker, "w").close()
                        except OSError:
                            pass
                        os.environ["CUBEON_GPU_RESTARTS"] = str(_gpu_restarts)
                        print(f"cubeon: client crashed mid-session (GPU "
                              f"driver?) - restarting with software OpenGL "
                              f"(attempt {_gpu_restarts})")
                        time.sleep(1.5)  # let the WM/core dump settle
                        try:
                            _relaunch_fresh_process()
                        except Exception as ex:
                            print(f"cubeon: mid-session restart via re-exec "
                                  f"failed ({ex})")
                        return  # execv, detached handoff, or nothing left
                    _incident.record_giving_up(
                        _MAX_MIDSESSION_RESTARTS, "mid_session_crash")
                    return  # restart budget exhausted: exit

                if _session_end_kind == "pre_paint_crash":
                    # UI never painted: client crash. Arm fallback, retry.
                    try:
                        os.makedirs(_CUBEON_HOME, exist_ok=True)
                        open(_gl_fallback_marker, "w").close()
                    except OSError:
                        pass
                    _retries += 1
                    if _retries <= _MAX_CLIENT_RETRIES:
                        print(f"cubeon: client died before showing the window "
                              f"(attempt {_retries}) - retrying with software OpenGL")
                        time.sleep(1.5)  # let the WM/core dump settle
                    else:
                        print("cubeon: client keeps dying before the window "
                              "shows - giving up")
                        _incident.record_giving_up(_retries, "pre_paint_crash")
                        return

    _session_loop()

    # Hard exit. Native threads (pango fontconfig, GLib leftovers) are
    # occasionally still alive and ignore daemon status during interpreter
    # shutdown, leaving a zombie launcher process. os._exit skips all
    # teardown beyond what we already did explicitly above. Cleanup handlers
    # have ALREADY run at this point (see loop body) - nothing is skipped.
    os._exit(0)
