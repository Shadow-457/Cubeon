#!/usr/bin/env python3
"""
Runs Cubeon with a real console: every core call, click, thread, page repaint
and subprocess is logged with a timestamp and thread name.

    python tools/debug_run.py

Everything also goes to tools/debug_run.log so it can be pasted somewhere.

Why this exists: a hang inside a background thread is invisible from the UI.
main.py runs the install/launch work on a daemon thread and reports failures by
writing into a Flet label - so if the thread blocks, or if the repaint never
reaches the window, the button just sits on "Preparing" with no error anywhere.
This wrapper makes that case readable in three ways:

  1. Every launcher_core / cubeon.* function logs ENTER and EXIT with how long
     it took. A hang is then simply the last ENTER with no matching EXIT.
  2. A watchdog prints the full Python stack of any call still running after
     STALL_AFTER seconds, and keeps re-printing it. That names the exact line
     it is stuck on, which is the thing guessing can't get right.
  3. Thread deaths, uncaught exceptions and subprocess spawns are logged even
     when the UI swallows them.

Flags:
    --lite         log only: no per-function wrapping, so timing stays close to
                   a plain `python main.py`. Use this when the bug DISAPPEARS
                   under a full debug run - that means the tracing latency was
                   hiding a race, and this narrows down what to remove.
    --flet-debug   turn on Flet's own (very loud) internal logging
    --quiet-paint  stop logging page.update() calls
    --paint-race   detect two threads inside page.update() at the same time.
                   Flet's patch_control mutates a shared control index, so
                   overlapping repaints can corrupt it - after which the UI
                   silently stops updating until something forces a rebuild.
    --stall N      seconds before the watchdog calls a call stalled (default 8)

Nothing here changes the app: it only wraps functions, so behaviour under
debug_run is the same as under `python main.py`.
"""
import faulthandler
import functools
import itertools
import logging
import os
import runpy
import signal
import subprocess
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

_argv = sys.argv[1:]


def _flag(name):
    return name in _argv


FLET_DEBUG = _flag("--flet-debug")
QUIET_PAINT = _flag("--quiet-paint")
LITE = _flag("--lite")
PAINT_RACE = _flag("--paint-race") or LITE  # the reason --lite usually exists
STALL_AFTER = 8.0
if "--stall" in _argv:
    try:
        STALL_AFTER = float(_argv[_argv.index("--stall") + 1])
    except (IndexError, ValueError):
        pass

# main.py must not see our flags.
sys.argv = [sys.argv[0]]

LOG_PATH = os.path.join(HERE, "debug_run.log")


# ---------------------------------------------------------------------------
# Logging: millisecond timestamps + thread name, unbuffered, console + file
# ---------------------------------------------------------------------------
class _Fmt(logging.Formatter):
    start = time.monotonic()

    def format(self, record):
        rel = time.monotonic() - self.start
        return (f"{rel:8.3f}s [{record.threadName[:18]:<18}] "
                f"{record.getMessage()}")


_handlers = [logging.StreamHandler(sys.stdout),
             logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")]
for h in _handlers:
    h.setFormatter(_Fmt())
logging.basicConfig(level=logging.DEBUG, handlers=_handlers)
log = logging.getLogger("cubeon.debug")

# Flet's own logs are extremely loud (a line per control patch), so they are
# off unless asked for. requests/urllib3 stay at INFO so network calls show up
# without dumping headers.
for noisy in ("flet", "flet_desktop", "flet.controls", "flet_core"):
    logging.getLogger(noisy).setLevel(logging.DEBUG if FLET_DEBUG else logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.INFO)


def _short(value, limit=110):
    """A repr short enough to log, with bytes/PNGs collapsed."""
    try:
        if isinstance(value, (bytes, bytearray)):
            return f"<{len(value)} bytes>"
        text = repr(value)
    except Exception:
        return "<unreprable>"
    return text if len(text) <= limit else text[:limit] + "..."


# ---------------------------------------------------------------------------
# In-flight call tracking, so a stall can be named instead of guessed at
# ---------------------------------------------------------------------------
_inflight = {}           # seq -> (label, started_at, thread)
_inflight_lock = threading.Lock()
_seq = itertools.count(1)


def _watchdog():
    """Prints the stack of any call that has outlived STALL_AFTER seconds.

    Repeats every few seconds while it is still stuck, because the interesting
    part of a hang is which line it sits on, not that it happened.
    """
    warned = {}
    while True:
        time.sleep(2.0)
        now = time.monotonic()
        with _inflight_lock:
            snapshot = list(_inflight.items())
        frames = sys._current_frames()
        for seq, (label, started, thread) in snapshot:
            waited = now - started
            if waited < STALL_AFTER:
                continue
            last = warned.get(seq, 0)
            if now - last < 5.0:
                continue
            warned[seq] = now
            log.warning("STALLED %.1fs in %s  (thread %s)", waited, label, thread.name)
            frame = frames.get(thread.ident)
            if frame is None:
                continue
            for line in traceback.format_stack(frame):
                for part in line.rstrip().splitlines():
                    log.warning("    %s", part)
        for seq in list(warned):
            if not any(s == seq for s, _ in snapshot):
                warned.pop(seq, None)


# ---------------------------------------------------------------------------
# Wrapping every cubeon/launcher_core function
# ---------------------------------------------------------------------------
def _wrap(func, label):
    @functools.wraps(func)
    def inner(*args, **kwargs):
        seq = next(_seq)
        shown = ", ".join(
            [_short(a, 60) for a in args]
            + [f"{k}={_short(v, 60)}" for k, v in kwargs.items()]
        )
        log.debug("ENTER %s(%s)", label, shown)
        thread = threading.current_thread()
        with _inflight_lock:
            _inflight[seq] = (label, time.monotonic(), thread)
        t0 = time.monotonic()
        try:
            result = func(*args, **kwargs)
        except BaseException as ex:
            dt = time.monotonic() - t0
            log.error("RAISE %s after %.3fs -> %s: %s", label, dt, type(ex).__name__, ex)
            for line in traceback.format_exc().rstrip().splitlines():
                log.error("    %s", line)
            raise
        else:
            dt = time.monotonic() - t0
            slow = "  <<< SLOW" if dt > 1.0 else ""
            log.debug("EXIT  %s (%.3fs) -> %s%s", label, dt, _short(result), slow)
            return result
        finally:
            with _inflight_lock:
                _inflight.pop(seq, None)
    inner.__cubeon_wrapped__ = func
    return inner


def instrument():
    """Wraps cubeon.* functions everywhere they are already bound.

    Wrapping only the module attribute is not enough: `from .mods import
    sync_mods_to_game` copies the function object into the importing module's
    namespace, so patching cubeon.mods afterwards would miss that call. So this
    builds an identity map of every original function and then swaps it out
    across every loaded module, which catches re-exports and direct bindings
    alike.
    """
    import launcher_core                                          # noqa: F401
    import cubeon
    import ui.skin_tab, ui.mods_tab, ui.server_tab                         # noqa: F401

    import importlib
    import pkgutil
    for mod in pkgutil.iter_modules(cubeon.__path__, "cubeon."):
        try:
            importlib.import_module(mod.name)
        except Exception as ex:
            log.warning("could not import %s for instrumentation: %s", mod.name, ex)

    replacements = {}
    for name, module in list(sys.modules.items()):
        if not (name == "cubeon" or name.startswith("cubeon.")):
            continue
        for attr, value in list(vars(module).items()):
            if attr.startswith("__") or not callable(value):
                continue
            if not hasattr(value, "__module__") or not hasattr(value, "__code__"):
                continue  # classes / builtins / C functions
            if not str(value.__module__).startswith("cubeon"):
                continue
            if value in replacements:
                continue
            replacements[value] = _wrap(value, f"{value.__module__.split('.')[-1]}.{attr}")

    patched = 0
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        if not (name in ("launcher_core", "ui.skin_tab", "ui.mods_tab", "ui.server_tab", "main")
                or name == "cubeon" or name.startswith("cubeon.")):
            continue
        for attr, value in list(vars(module).items()):
            try:
                wrapper = replacements.get(value)
            except TypeError:
                continue  # unhashable
            if wrapper is not None:
                setattr(module, attr, wrapper)
                patched += 1
    log.info("instrumented %d functions across %d bindings", len(replacements), patched)


# ---------------------------------------------------------------------------
# Flet repaints and Popen spawns
# ---------------------------------------------------------------------------
def instrument_flet():
    import flet as ft

    try:
        import importlib.metadata as md
        log.info("flet version: %s", md.version("flet"))
    except Exception:
        pass

    page_cls = getattr(ft, "Page", None)
    if page_cls is None:
        return

    original = page_cls.update
    counter = itertools.count(1)
    # Who is currently inside page.update(). Flet's patch_control walks and
    # mutates a shared control index, so two threads in here at once is a data
    # race - and a corrupted index shows up later as "the UI just stopped
    # updating", with no exception anywhere.
    active = {}
    active_lock = threading.Lock()
    races = itertools.count(1)

    @functools.wraps(original)
    def update(self, *controls):
        n = next(counter)
        frame = sys._getframe(1)
        where = f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_lineno} in {frame.f_code.co_name}"
        me = threading.current_thread()
        on_main = me is threading.main_thread()

        if PAINT_RACE:
            with active_lock:
                others = [(t, w) for t, w in active.items() if t is not me]
                if others:
                    log.error("PAINT RACE #%d - %s entered update() from %s while "
                              "%s is still inside it (from %s)",
                              next(races), me.name, where,
                              ", ".join(t.name for t, _ in others),
                              "; ".join(w for _, w in others))
                active[me] = where

        try:
            result = original(self, *controls)
        except BaseException as ex:
            # This is the interesting case: a repaint requested from a worker
            # thread that the UI never receives, which looks exactly like the
            # app freezing on whatever label it last displayed.
            log.error("PAINT#%d FAILED from %s (main_thread=%s) -> %s: %s",
                      n, where, on_main, type(ex).__name__, ex)
            raise
        finally:
            if PAINT_RACE:
                with active_lock:
                    active.pop(me, None)

        if not QUIET_PAINT:
            log.debug("paint#%d from %s (main_thread=%s)", n, where, on_main)
        return result

    page_cls.update = update
    log.info("patched Page.update (paint logging=%s, race detection=%s)",
             not QUIET_PAINT, PAINT_RACE)


def instrument_popen():
    original = subprocess.Popen.__init__

    @functools.wraps(original)
    def init(self, args, *rest, **kwargs):
        shown = args if isinstance(args, str) else " ".join(str(a) for a in args)
        log.info("SPAWN %s", shown[:400] + ("..." if len(shown) > 400 else ""))
        if kwargs.get("stdout") is subprocess.PIPE:
            # Worth calling out: a piped stdout that nobody drains will block
            # the child once the ~64KB pipe buffer fills. Minecraft logs well
            # past that before its window appears.
            log.warning("SPAWN uses stdout=PIPE - child will block if nothing reads it")
        return original(self, args, *rest, **kwargs)

    subprocess.Popen.__init__ = init


# ---------------------------------------------------------------------------
# Never let a failure go unreported
# ---------------------------------------------------------------------------
def install_hooks():
    def thread_hook(args):
        log.error("UNCAUGHT in thread %s: %s: %s",
                  args.thread.name if args.thread else "?",
                  args.exc_type.__name__, args.exc_value)
        for line in traceback.format_exception(args.exc_type, args.exc_value,
                                               args.exc_traceback):
            for part in line.rstrip().splitlines():
                log.error("    %s", part)

    def excepthook(exc_type, exc_value, tb):
        log.error("UNCAUGHT on %s: %s: %s",
                  threading.current_thread().name, exc_type.__name__, exc_value)
        for line in traceback.format_exception(exc_type, exc_value, tb):
            for part in line.rstrip().splitlines():
                log.error("    %s", part)

    threading.excepthook = thread_hook
    sys.excepthook = excepthook

    original_start = threading.Thread.start

    @functools.wraps(original_start)
    def start(self):
        log.debug("THREAD start %s (target=%s daemon=%s)",
                  self.name, getattr(self._target, "__name__", self._target), self.daemon)
        return original_start(self)

    threading.Thread.start = start

    faulthandler.enable()
    if hasattr(signal, "SIGUSR1"):
        # kill -USR1 <pid> dumps every thread's stack, for a hang that the
        # watchdog can't see because it never entered an instrumented call.
        faulthandler.register(signal.SIGUSR1, all_threads=True)
        log.info("send SIGUSR1 to pid %d to dump all thread stacks", os.getpid())


def main():
    log.info("=" * 70)
    log.info("Cubeon debug run - python %s on %s", sys.version.split()[0], sys.platform)
    log.info("cwd=%s  log=%s", ROOT, LOG_PATH)
    log.info("mode: %s   stall threshold: %.1fs   flet debug: %s",
             "LITE (logging only, near-native timing)" if LITE
             else "FULL (per-function tracing)", STALL_AFTER, FLET_DEBUG)
    log.info("=" * 70)

    install_hooks()
    instrument_popen()
    try:
        instrument_flet()
    except Exception as ex:
        log.warning("could not instrument flet: %s", ex)
    if LITE:
        log.info("--lite: skipping per-function tracing to keep timing realistic")
    else:
        try:
            instrument()
        except Exception as ex:
            log.error("instrumentation failed: %s", ex)
            traceback.print_exc()

    threading.Thread(target=_watchdog, name="watchdog", daemon=True).start()

    log.info("starting main.py ...")
    try:
        runpy.run_path(os.path.join(ROOT, "main.py"), run_name="__main__")
    except KeyboardInterrupt:
        log.info("interrupted")
    except BaseException as ex:
        log.error("main.py exited with %s: %s", type(ex).__name__, ex)
        traceback.print_exc()
        raise
    finally:
        log.info("main.py returned - log written to %s", LOG_PATH)


if __name__ == "__main__":
    main()
