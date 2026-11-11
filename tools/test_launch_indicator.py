#!/usr/bin/env python3
"""The Play tab's launch indicator, driven through the real UI.

launch_game() is non-blocking: it spawns the game and returns the moment the
process exists. So a game that dies on startup - bad Java, a mod conflict, a
broken pack, all of which are routine with heavy Forge modpacks - reaches
on_exit() while do_install_and_launch() is still finishing up. Whatever runs
after launch_game() therefore races the crash handler, and if it wins it
overwrites the crash reason with a "Minecraft is running" line and a progress
bar that pulses forever with no game behind it.

This drives the actual Play button against a fake Page and asserts the launcher
reports what really happened.

Run: python3 tools/test_launch_indicator.py
"""
import os
import sys
import threading
import time
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


# A fake Page, and a tree walker, so the UI builds with no Flet runtime and no
# window. Kept local rather than imported from test_ui_smoke, whose module body
# runs a whole suite (and exits) on import.
class FakeWindow:
    def __init__(self):
        self.width = self.height = 0
        self.min_width = self.min_height = 0
        self.title = ""
        self.icon = ""
        self.prevent_close = False

    def center(self):
        pass

    def destroy(self):
        pass


class FakePage:
    def __init__(self):
        self.window = FakeWindow()
        self.overlay = []
        self.controls = []
        self.fonts = {}
        self.theme = None
        self.theme_mode = None
        self.title = ""
        self.bgcolor = None
        self.padding = 0
        self.update_calls = 0
        self.opened = []
        self.snackbars = []
        self.session = types.SimpleNamespace()
        self.services = []
        self.tasks = []

    def update(self, *controls):
        self.update_calls += 1

    def add(self, *controls):
        self.controls.extend(controls)

    def open(self, control):
        self.opened.append(control)

    def close(self, control):
        pass

    def run_thread(self, fn, *a, **kw):
        return fn(*a, **kw)

    def run_task(self, fn, *a, **kw):
        self.tasks.append(fn.__name__)
        return None


def walk(control, depth=0, seen=None):
    if seen is None:
        seen = set()
    if control is None or id(control) in seen or depth > 60:
        return
    seen.add(id(control))
    yield control
    for attr in ("controls", "content", "actions", "title", "leading",
                 "trailing", "label", "tabs", "items"):
        child = getattr(control, attr, None)
        if child is None:
            continue
        if isinstance(child, (list, tuple)):
            for c in child:
                if hasattr(c, "_c") or hasattr(c, "controls") or hasattr(c, "content"):
                    yield from walk(c, depth + 1, seen)
        elif hasattr(child, "_c") or hasattr(child, "controls") or hasattr(child, "content"):
            yield from walk(child, depth + 1, seen)


# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

import cubeon.versions as versions  # noqa: E402
import cubeon.csl as csl  # noqa: E402

versions.get_available_versions = lambda *a, **kw: [
    {"id": "1.20.1", "type": "release"}]
versions.get_latest_release = lambda: "1.20.1"
csl.ensure_ready = lambda *a, **kw: None

import launcher_core as core  # noqa: E402

core.get_available_versions = versions.get_available_versions
core.get_latest_release = versions.get_latest_release
core.get_installed_versions = lambda *a, **kw: [{"id": "1.20.1"}]
core.install_version = lambda *a, **kw: None
core.install_mod_loader = lambda lid, v, *a, **kw: v
core.is_loader_supported = lambda *a, **kw: True
core.find_installed_loader_version = lambda *a, **kw: None
core.save_config = lambda *a, **kw: None
core.sync_mods_to_game = lambda *a, **kw: None

import main as app  # noqa: E402


def build():
    page = FakePage()
    app.run_sync(page)
    return page


def find(page, pred):
    for root in page.controls:
        for c in walk(root):
            if pred(c):
                return c
    return None


def texts(page):
    out = []
    for root in page.controls:
        for c in walk(root):
            v = getattr(c, "value", None)
            if isinstance(v, str) and v.strip():
                out.append(v.lower())
    return out


def bars(page):
    out = []
    for root in page.controls:
        out += [c for c in walk(root) if type(c).__name__ == "ProgressBar"]
    return out


def _drain_new_threads(before, timeout):
    """Join every thread that appeared since `before`.

    `threading.enumerate()` also lists threads that are sitting in
    `threading._limbo` - `start()` has been called but the bootstrap body has
    not run yet. `join()` on one of those raises
    RuntimeError("cannot join thread before it is started"), which is what
    made this suite fail intermittently on slow CI runners: the launch thread
    had not been scheduled yet when this loop ran. Wait for limbo threads to
    actually start, then join them for real - the waiting guarantee (all new
    threads finish before the assertions run) is unchanged.
    """
    deadline = time.monotonic() + timeout
    for t in set(threading.enumerate()) - before:
        while time.monotonic() < deadline:
            try:
                t.join(timeout=max(0.0, deadline - time.monotonic()))
                break
            except RuntimeError:
                time.sleep(0.05)  # still in limbo; it will start


def click_play(page):
    """Fill in a username and press the real Play button, then wait out the
    background launch thread."""
    field = find(page, lambda c: getattr(c, "hint_text", None) == "Username")
    assert field is not None, "no username field"
    field.value = "tester"
    btn = find(page, lambda c: getattr(c, "on_click", None) is not None
               and type(c).__name__ == "Container"
               and any(getattr(t, "value", None) == "PLAY"
                       for t in walk(c)))
    assert btn is not None, "no Play button"
    before = set(threading.enumerate())
    btn.on_click(None)
    _drain_new_threads(before, 20)
    # The launch thread may itself spawn the watcher; drain briefly.
    _drain_new_threads(before, 5)


# --------------------------------------------------------------------------
print("\n1. a game that crashes on startup reports the crash, not 'running'")

CRASH_LINES = ["java.lang.OutOfMemoryError: Java heap space"]


def launch_crashes_immediately(*a, on_exit=None, status_cb=None, **kw):
    """The realistic failure: the process is gone before launch_game returns."""
    if status_cb:
        status_cb("Installing CustomSkinLoader")
    if on_exit:
        on_exit(1, CRASH_LINES)   # watcher fires FIRST


core.launch_game = launch_crashes_immediately
page = build()
click_play(page)

shown = texts(page)
running = [t for t in shown if "minecraft is running" in t]
check("the stale 'Minecraft is running' line is NOT shown after a crash",
      not running,
      f"found {running!r}")

explained = app._explain_exit(1, CRASH_LINES).lower()
check("the crash explanation survives to the label",
      any(explained[:24] in t for t in shown),
      f"expected {explained[:40]!r} in {[t for t in shown if 'crash' in t or 'memory' in t]!r}")
check("the crash is reported as out-of-memory (the real cause)",
      any("out of memory" in t for t in shown))
check("a failed launch has a CRASHED stage", "crashed" in shown)
check("a genuine failure still opens its report", "_open_async" in page.tasks)

# NOTE: the sidebar's READY/CRASHED label is deliberately not asserted here.
# It lives in the brand block, which this tree walker doesn't reach, so an
# assertion on it would be testing the walker rather than the launcher. The
# progress label below the Play button - the thing the user actually watches
# during a launch - is what these checks cover.

visible_bars = [b for b in bars(page) if getattr(b, "visible", False)]
check("no progress bar is left pulsing after the crash",
      not any(getattr(b, "value", 0) is None for b in visible_bars),
      f"visible bars values={[getattr(b, 'value', 'n/a') for b in visible_bars]}")

# --------------------------------------------------------------------------
print("\n2. a game that actually starts DOES show the running indicator")


saved_exit = {}


def launch_stays_up(*a, on_exit=None, status_cb=None, **kw):
    saved_exit["callback"] = on_exit
    if status_cb:
        status_cb("Installing CustomSkinLoader")
    # on_exit is never called - the game is still running.


core.launch_game = launch_stays_up
page2 = build()
click_play(page2)

shown2 = texts(page2)
check("the running indicator is shown while the game is up",
      any("minecraft is running" in t for t in shown2),
      f"got {[t for t in shown2 if 'running' in t or 'launch' in t]!r}")
check("no crash text while the game is up",
      not any("out of memory" in t for t in shown2))
check("the loading bar is GONE once the game is running",
      not any(getattr(b, "visible", False) for b in bars(page2)),
      f"bars={[(getattr(b,'visible',None), getattr(b,'value','n/a')) for b in bars(page2)]}")

# The reported failure arrives after RUNNING is already painted, unlike an
# immediate startup crash. Use the actual retained exit callback to reproduce
# both that transition and HotSpot's SIGTERM status.
REALMS_LINES = [
    "[IO-Worker-1/INFO]: Could not authorize you against Realms server: "
    "java.lang.RuntimeException: Failed to parse into SignedJWT: 0",
    "[IO-Worker-1/ERROR]: Couldn't connect to realms",
    "net.minecraft.class_4355: Realms authentication error with message "
    "'java.lang.RuntimeException: Failed to parse into SignedJWT: 0'",
    "\tat java.base/java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:642)",
]
saved_exit["callback"](143, REALMS_LINES)
ended = texts(page2)
check("a later SIGTERM replaces RUNNING with STOPPED",
      "stopped" in ended and "running" not in ended)
check("SIGTERM gives a termination explanation without blaming Realms or Java",
      any("termination signal" in t for t in ended)
      and not any("realms" in t or "java" in t for t in ended if "game stopped" in t))
check("an external stop does not open a false crash report", "_open_async" not in page2.tasks)
check("a stopped game returns the button to PLAY", "play" in ended)
check("the stopped card stays visible so its explanation is readable",
      find(page2, lambda c: getattr(c, "data", None) == "instance-install-progress").visible)

# --------------------------------------------------------------------------
print("\n3. a clean quit clears the indicator instead of stranding it")


def launch_then_quits(*a, on_exit=None, status_cb=None, **kw):
    if on_exit:
        on_exit(0, [])


core.launch_game = launch_then_quits
page3 = build()
click_play(page3)

shown3 = texts(page3)
check("no 'Minecraft is running' left over after a clean quit",
      not any("minecraft is running" in t for t in shown3),
      f"got {[t for t in shown3 if 'running' in t]!r}")
check("no bar left pulsing after a clean quit",
      not any(getattr(b, "value", 0) is None and getattr(b, "visible", False)
              for b in bars(page3)))
check("a clean quit hides the progress card",
      not find(page3, lambda c: getattr(c, "data", None) == "instance-install-progress").visible)

# --------------------------------------------------------------------------
print("\n4. the bar never carries state from the previous launch")
# The launch that just ended left the bar hidden; starting another must not
# resume mid-fill or pin an empty determinate bar at 0% (which reads as frozen
# whenever nothing measurable happens - an already-installed version, or a
# click that just waits on a background prefetch's install lock).
core.launch_game = launch_stays_up
page4 = build()
pb = bars(page4)
for b in pb:
    b.value = 0.42          # pretend a previous run left it part-filled
    b.data = 9999           # ...with a stale phase maximum
click_play(page4)
after = [b for b in bars(page4) if getattr(b, "visible", False)]
check("no visible bar resumes at the previous run's fraction",
      not any(getattr(b, "value", None) == 0.42 for b in after),
      f"values={[getattr(b,'value','n/a') for b in after]}")
check("no visible bar sits frozen at a determinate 0%",
      not any(getattr(b, "value", None) == 0 for b in after),
      f"values={[getattr(b,'value','n/a') for b in after]}")

# The fallback must retire stale RUNNING/busy controls even if repaint fails.
with patch.object(app.thread_safe_ui, "refresh", side_effect=[RuntimeError("fixture: repaint failed")] + [None] * 20):
    saved_exit["callback"](-15, REALMS_LINES)
fallback = texts(page4)
check("a failed exit repaint still leaves STOPPED, never RUNNING",
      "stopped" in fallback and "running" not in fallback)
check("the fallback still returns to PLAY", "play" in fallback)
check("the fallback leaves no pulsing bar",
      not any(getattr(b, "visible", False) for b in bars(page4)))

# --------------------------------------------------------------------------
print("\n5. intentional Quit and real fatal exits keep their own behavior")
core.launch_game = lambda *a, on_exit=None, **kw: on_exit(143, REALMS_LINES)
with patch("cubeon.watchdog.consume_intentional_stop", return_value=True):
    page5 = build()
    click_play(page5)
check("intentional Quit hides the card without a crash report",
      not find(page5, lambda c: getattr(c, "data", None) == "instance-install-progress").visible
      and "_open_async" not in page5.tasks)

core.launch_game = lambda *a, on_exit=None, **kw: on_exit(-11, ["Fatal error: native renderer failed"])
page6 = build()
click_play(page6)
check("SIGSEGV remains a crash with a report",
      "crashed" in texts(page6) and "_open_async" in page6.tasks)

print("\n6. unrelated Realms output never replaces a genuine crash cause")
for code in (-15, 143):
    reason = app._explain_exit(code, REALMS_LINES).lower()
    check(f"termination {code} never claims Java corruption or a Realms crash",
          "game stopped" in reason and "realms" not in reason and "java" not in reason)
reason = app._explain_exit(1, REALMS_LINES).lower()
check("Realms-only output uses an honest unknown-cause fallback",
      "without naming a cause" in reason and "realms" not in reason)
reason = app._explain_exit(1, ["Exception: renderer broke"] + REALMS_LINES).lower()
check("an earlier real error survives a later background Realms failure", "renderer broke" in reason)
reason = app._explain_exit(1, CRASH_LINES + REALMS_LINES).lower()
check("real out-of-memory evidence still wins over background auth failures", "out of memory" in reason)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
