"""
Making page.update() safe to call from a background thread.

THE BUG THIS FIXES

The launcher does its slow work (installing a version, downloading a loader,
starting the game) on background threads, and reports progress by mutating a
control and calling page.update(). That is the documented Flet pattern and it
looks completely correct - but on Flet 0.80+ it silently loses updates.

Chased down to Flet's own transport. `page.update()` ends at
`FletSocketServer.send_message`, which does:

    self.__send_queue.put_nowait(framed)     # __send_queue is an asyncio.Queue

`asyncio.Queue.put_nowait()` is **not thread-safe**. Called from a foreign
thread it appends the frame and marks the waiting getter ready, but it never
wakes the event loop - that requires `loop.call_soon_threadsafe`, which writes
to the loop's self-pipe. So the frame sits in the queue while the loop sleeps in
`select()`, and the window shows nothing.

Then *any* unrelated event - a mouse move, a click, a focus change, a window
resize - wakes the loop, and the whole backlog transmits at once.

Reproduced directly against asyncio (an idle loop delivered nothing for 2s,
then delivered instantly on one unrelated wakeup). That is exactly the reported
symptom: the Play button sat on "Preparing" forever, and switching tabs or
windows made it jump to its real state. The launcher was never hung - it had
finished and told the window, and the window never got the message.

It is intermittent because it depends only on whether the user happened to
generate input while waiting. Moving the mouse hides it completely, which is why
it survived development.

THE FIX

Wrap `page.update()` so a call from any non-loop thread is forwarded to the
loop with `loop.call_soon_threadsafe`. That is the one operation asyncio
guarantees is safe across threads, and it wakes the loop. Calls already on the
loop thread run unchanged, so there is no added latency on the UI path.

install(page) is called once at startup and fixes all ~80 existing
page.update() call sites at once, with no changes to any of them. Nothing else
in the app needs to know this module exists.

A SECOND, RELATED BUG - see mark_mounted() below

Even with the above fix, a background-thread update can still land *during*
the app's own initial `page.add(...)` at startup: main() calls
refresh_version_list() synchronously right after page.add(), and that in turn
starts at least one background thread (the loader-support check) that calls
page.update() from a worker before the client has confirmed the first frame
is mounted (observed directly: "Timed out waiting for OpenGL frame" followed
by an IndexError inside Flet's own object_patch diffing, from a background
update racing the still-in-flight initial mount). Flet's diff assumes it is
comparing two full snapshots of a control tree that isn't being mutated out
from under it mid-comparison; a background patch queued via
call_soon_threadsafe right behind the startup patch violates that.

Fixed by holding background-thread updates until the initial synchronous
mount is done: mark_mounted() flips a flag once main() finishes its own
first page.add()/update() call, and any background update() that arrives
before that is deferred (re-scheduled a beat later) instead of racing it.
"""
import asyncio
import atexit
import logging
import os
import sys
import threading
import time

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# REPAINT PROFILER (opt-in: CUBEON_PERF=1)
#
# Every page.update() is a full diff of the mounted control tree plus a
# serialized patch over the IPC transport to the Flutter client, so a repaint
# is the single most expensive routine thing the Python side does. There are
# ~170 update() call sites; guessing which ones hurt is how you end up
# "optimizing" the wrong half of the app (or concluding the language is the
# problem when it isn't).
#
# With the env var set, each call is timed and attributed to the first frame
# OUTSIDE this module - i.e. the real call site - and a table is printed at
# exit, worst total time first. Zero cost when the var is unset: one bool
# check per repaint.
# ---------------------------------------------------------------------------
_PERF = bool(os.environ.get("CUBEON_PERF"))
_perf_lock = threading.Lock()
_perf: dict = {}  # "file:line" -> [calls, total_s, worst_s]


def _perf_site() -> str:
    """"file:line" of the nearest caller that isn't this module."""
    try:
        frame = sys._getframe(1)
        mine = __file__
        while frame is not None:
            name = frame.f_code.co_filename
            if name != mine:
                return f"{os.path.basename(name)}:{frame.f_lineno}"
            frame = frame.f_back
    except Exception:
        pass
    return "?"


def _perf_add(site: str, seconds: float) -> None:
    with _perf_lock:
        row = _perf.get(site)
        if row is None:
            _perf[site] = [1, seconds, seconds]
        else:
            row[0] += 1
            row[1] += seconds
            if seconds > row[2]:
                row[2] = seconds


def perf_report() -> str:
    """The repaint table as text (empty when profiling is off/unused)."""
    with _perf_lock:
        rows = sorted(_perf.items(), key=lambda kv: kv[1][1], reverse=True)
    if not rows:
        return ""
    total = sum(r[1][1] for r in rows)
    calls = sum(r[1][0] for r in rows)
    out = [f"\ncubeon repaint profile: {calls} page.update() calls, "
           f"{total * 1000:.0f} ms total in the diff+send",
           f"{'call site':<34}{'calls':>7}{'total ms':>10}{'avg ms':>9}{'worst ms':>10}"]
    for site, (n, tot, worst) in rows[:20]:
        out.append(f"{site:<34}{n:>7}{tot * 1000:>10.1f}"
                   f"{tot / n * 1000:>9.2f}{worst * 1000:>10.1f}")
    if len(rows) > 20:
        out.append(f"... and {len(rows) - 20} quieter call sites")
    return "\n".join(out)


if _PERF:
    atexit.register(lambda: print(perf_report() or
                                  "\ncubeon repaint profile: no repaints recorded"))

_installed = False
_warned = False
# Per-page mounted flags. A dict (not a single bool) because Flet can in
# principle serve more than one page/session from the same process; keying
# by id(page) keeps this correct without needing page to be hashable in a
# stable way across Flet versions.
_mounted_pages = set()

# Page-id -> event loop, recorded by install() so refresh() can marshal
# control-level repaints from background threads to the right loop. Flet
# does not expose the loop on the page object, hence the side table.
_loops = {}

# THE THIRD BUG - concurrent tree mutation vs. Flet's diff walk (fixed 2026-08-25)
#
# install() originally fixed only the DELIVERY of background updates (frames
# sat in asyncio's queue until a stray input woke the loop). But the MUTATION
# half was still unsynchronized: a background thread does
# `some_list.controls.append(x); page.update()`, and the append runs on the
# WORKER thread even though the resulting diff is serialized onto the loop.
# Flet's ObjectPatch.from_diff walks the live tree assuming it is quiescent;
# an append landing mid-walk desynchronizes its src/dst key lists and it dies
# with `IndexError: list index out of range` deep in _compare_lists.
#
# Trigger observed in the wild: starting a server floods the console pump,
# so log-line appends collide constantly with the status/console diffs.
#
# THE FIX is one process-wide lock with two users:
#   * every update() this module wraps takes TREE_LOCK around the actual
#     diff+send (both the on-loop fast path and deferred background ones);
#   * hot mutation sites (console append, banner repaints) take TREE_LOCK
#     around their control-tree writes via `with thread_safe_ui.TREE_LOCK:`.
# A worker holding the lock for a microsecond-long append can briefly delay
# the loop; that is exactly the serialization Flet's diff assumes and it is
# invisible at UI timescales. As a belt-and-braces net, a failed update is
# re-scheduled a beat later instead of being dropped - a patch that raised
# was never sent, so the next attempt diffs cleanly against the same snapshot.
TREE_LOCK = threading.RLock()
_UPDATE_MAX_RETRIES = 3

# THROTTLED page.update() for progress floods (fourth bug, 2026-09-05).
#
# install_minecraft_version() reports progress once per FILE - a version is
# ~4000 asset files - and each report used to call page.update(). Thousands of
# full-tree repaints queued onto the event loop saturate it: the window stops
# responding to input for the whole install and unfreezes the moment the
# download ends (the user-visible "it got stuck, then became good again").
#
# Humans cannot perceive more than ~10 fps of progress anyway. throttled_update
# coalesces an arbitrary call rate into at most one repaint per interval, and
# guarantees a final repaint so the last state (100%) is always shown.
_MIN_REPAINT_INTERVAL = 0.1   # seconds; 10 fps
_throttle_lock = threading.Lock()
_throttle_state: dict = {}    # id(page) -> {"t": last send, "dirty": pending}


def throttled_update(page) -> None:
    """Rate-limited page.update() for high-frequency progress callbacks.

    Call sites keep their existing per-file/per-chunk callbacks and simply use
    this instead of page.update(). A repaint is sent at most every
    _MIN_REPAINT_INTERVAL; intermediate calls are coalesced into the next one.
    Safe from any thread, before/after mount, and for any number of pages.
    """
    key = id(page)
    now = time.monotonic()
    with _throttle_lock:
        st = _throttle_state.get(key)
        if st is None:
            _throttle_state[key] = {"t": now, "dirty": False}
            # First call: fall through and paint immediately below.
        else:
            if now - st["t"] < _MIN_REPAINT_INTERVAL:
                st["dirty"] = True   # coalesce; the next tick paints it
                return
            st["t"] = now
            st["dirty"] = False
    page.update()


def final_update(page) -> None:
    """Paint any coalesced state left pending by throttled_update(). Call once
    when a flood ends (install finished/failed) so the last frame always lands."""
    with _throttle_lock:
        st = _throttle_state.pop(id(page), None)
    if st and st.get("dirty"):
        page.update()


# CONTROL-LEVEL REPAINT (the "refresh one control" API).
#
# page.update() diffs the ENTIRE mounted tree - every tab, every row - even
# when the change is one label's text. With ~9,000 lines of eagerly-built
# UI that is the app's #1 runtime cost (172 call sites at last count; see
# the CUBEON_PERF profiler above for the live numbers). Flet's own answer
# is control.update(): it diffs and sends ONLY that control's subtree.
#
# refresh(ctrl) is the thread-safe wrapper for that, mirroring everything
# install(page) does for page.update(): loop-thread fast path, background
# calls marshalled via call_soon_threadsafe, TREE_LOCK around the diff so
# tree mutations can't land mid-walk, reschedule-once on failure, and
# CUBEON_PERF attribution. It intentionally does NOT wait for
# mark_mounted(): a control-level patch can't race the initial full-tree
# mount the way a background page.update() can, because if the control
# isn't mounted yet Flet treats the patch as an add of that subtree -
# which is still correct.
#
# RULE OF THUMB for call sites:
#   * one small region changed (a label, a button state, one row, a
#     banner) -> refresh(that control)
#   * structure changed (added/removed controls from a list, swapped a
#     tab body, multiple regions) -> page.update()
def refresh(control) -> None:
    """Thread-safe control-level repaint: diffs only `control`'s subtree."""
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    # Flet 0.86: `control.page` is a property that RAISES RuntimeError for
    # unmounted controls (hasattr() doesn't catch it - the attribute exists).
    # The lazy-built tabs repaint their lists before the tab body is ever
    # mounted, so this is a normal path, not an error.
    try:
        loop = _loops.get(id(control.page))
    except Exception:
        loop = None
    if loop is None:
        # No loop known for this page (detached/unmounted control, or no
        # install() yet): try a direct control.update(). For an unmounted
        # control Flet's update() is a no-op; when install() hasn't run we
        # are on the loop thread by definition, so direct is correct.
        _refresh_now(control)
        return
    if running is loop:
        _refresh_now(control)
        return
    try:
        loop.call_soon_threadsafe(_refresh_now, control)
    except RuntimeError:
        pass  # loop gone (window closed mid-flight) - nothing left to paint


def _refresh_now(control) -> None:
    site = _perf_site() if _PERF else ""
    try:
        with TREE_LOCK:
            if not _PERF:
                control.update()
            else:
                _t0 = time.perf_counter()
                control.update()
                _perf_add(site, time.perf_counter() - _t0)
    except RuntimeError as ex:
        # Expected in one spot: the control isn't mounted yet (lazy-built
        # tabs repaint their lists before the tab body's first visit mounts
        # them). Not an error - Flet sends the control's full state when
        # it's mounted, so nothing is lost. Quietly skip.
        if "must be added to the page" not in str(ex):
            log.debug("refresh(%s) failed; skipped", type(control).__name__,
                      exc_info=True)
    except Exception:
        # Same contract as the page path: never kill a thread over a
        # repaint. A failed patch was never sent, so the tree is intact;
        # drop it and let the next repaint of this control reconcile.
        log.debug("refresh(%s) failed; skipped", type(control).__name__,
                  exc_info=True)



def mark_mounted(page) -> None:
    """Call once, from the main/loop thread, right after the app's first
    page.add()/page.update() has actually gone out - see main.py, right
    after the initial page.add(...) + refresh_version_list() at the end of
    main(). Before this is called, background-thread update() calls for
    this page are deferred instead of applied, so they can't race Flet's
    diff of the still-mounting initial tree (see module docstring).
    """
    _mounted_pages.add(id(page))


def _find_loop(page):
    """The event loop Flet is running this page on, or None.

    Dug out defensively: this reaches into Flet internals that have moved
    between versions, and a failure here must degrade to "behave like before"
    rather than break the launcher.
    """
    for path in (
        lambda: page.session.connection.loop,
        lambda: page._session.connection.loop,
        lambda: page.loop,
    ):
        try:
            loop = path()
        except Exception:
            continue
        if isinstance(loop, asyncio.AbstractEventLoop):
            return loop
    return None


def install(page) -> bool:
    """Makes page.update() thread-safe for this page. Returns True if applied.

    Idempotent, and safe to call even if Flet's internals have changed - in
    that case it logs and leaves the original method alone, so the app runs
    exactly as it did before rather than failing at startup.
    """
    global _installed
    if _installed:
        return True

    loop = _find_loop(page)
    if loop is None:
        # Logged at most once per process. Repeating it on every install()
        # attempt would spam the console of anyone whose Flet version moved
        # these internals, and the message is identical every time.
        global _warned
        if not _warned:
            _warned = True
            log.warning("thread_safe_ui: could not find the page's event loop; "
                        "background-thread updates may be delayed until the next "
                        "mouse or keyboard event")
        return False

    original = type(page).update

    def update(self, *controls):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        # Attributed HERE, on the calling thread: by the time a background
        # repaint actually runs on the loop the real call site is long gone
        # from the stack.
        site = _perf_site() if _PERF else ""

        if running is loop:
            # Already on the loop thread - the normal UI path. Still takes
            # TREE_LOCK: event handlers mutate trees too, and a background
            # worker's append must not land mid-diff of this very call.
            try:
                with TREE_LOCK:
                    if not _PERF:
                        return original(self, *controls)
                    _t0 = time.perf_counter()
                    result = original(self, *controls)
                    _perf_add(site, time.perf_counter() - _t0)
                    return result
            except Exception:
                _reschedule(original, self, controls, 1, site)
                return

        # A background thread. Hand the actual send to the loop, which both
        # performs it in the right context and wakes the loop so the bytes
        # leave immediately instead of waiting for stray input.
        try:
            loop.call_soon_threadsafe(_deferred_update, original, self, controls,
                                      0, site)
        except RuntimeError:
            # Loop already closed (app shutting down mid-task). Dropping the
            # repaint is correct here; there is no window left to paint.
            pass

    def _reschedule(fn, page_obj, controls, attempt, site=""):
        """Retry a failed update one loop-tick later. Safe because Flet
        computes patches from its last-sent snapshot: a patch that raised
        was never sent, so nothing is corrupted - we just try again once
        whatever raced us has finished mutating."""
        if attempt > _UPDATE_MAX_RETRIES:
            log.exception("thread_safe_ui: page.update() failed after %d attempts",
                          attempt)
            return
        try:
            loop.call_soon_threadsafe(_deferred_update, fn, page_obj, controls,
                                      attempt, site)
        except RuntimeError:
            pass  # window gone mid-retry; nothing left to paint

    def _deferred_update(fn, page_obj, controls, _retries=0, site=""):
        if id(page_obj) not in _mounted_pages:
            if _retries >= 200:
                # ~a few seconds of retrying (loop ticks are fast) with no
                # mark_mounted() ever arriving - something's wrong upstream
                # (e.g. main() raised before reaching it). Apply anyway
                # rather than silently eating every background update
                # forever; a rare late-mount race is far better than a
                # launcher that never shows install/download progress.
                log.warning("thread_safe_ui: page never marked mounted after "
                            "%d retries; applying deferred update anyway", _retries)
                _safe_update(fn, page_obj, controls, site)
                return
            try:
                loop.call_soon_threadsafe(_deferred_update, fn, page_obj, controls,
                                          _retries + 1, site)
            except RuntimeError:
                pass
            return
        _safe_update(fn, page_obj, controls, site)

    def _safe_update(fn, page_obj, controls, site=""):
        try:
            with TREE_LOCK:
                if not _PERF:
                    fn(page_obj, *controls)
                else:
                    _t0 = time.perf_counter()
                    fn(page_obj, *controls)
                    _perf_add(site or "<background>", time.perf_counter() - _t0)
        except Exception:
            # Never let a repaint failure kill the event loop - that would take
            # the whole window down over a cosmetic update. One quiet retry;
            # only give up (with the traceback) after that.
            _reschedule(fn, page_obj, controls, 1, site)

    type(page).update = update
    _loops[id(page)] = loop
    _installed = True
    log.info("thread_safe_ui: page.update() is now safe from any thread")
    return True
