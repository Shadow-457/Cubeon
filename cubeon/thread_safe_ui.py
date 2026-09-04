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
import logging
import threading

log = logging.getLogger(__name__)

_installed = False
_warned = False
# Per-page mounted flags. A dict (not a single bool) because Flet can in
# principle serve more than one page/session from the same process; keying
# by id(page) keeps this correct without needing page to be hashable in a
# stable way across Flet versions.
_mounted_pages = set()

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

        if running is loop:
            # Already on the loop thread - the normal UI path. Still takes
            # TREE_LOCK: event handlers mutate trees too, and a background
            # worker's append must not land mid-diff of this very call.
            try:
                with TREE_LOCK:
                    return original(self, *controls)
            except Exception:
                _reschedule(original, self, controls, 1)
                return

        # A background thread. Hand the actual send to the loop, which both
        # performs it in the right context and wakes the loop so the bytes
        # leave immediately instead of waiting for stray input.
        try:
            loop.call_soon_threadsafe(_deferred_update, original, self, controls)
        except RuntimeError:
            # Loop already closed (app shutting down mid-task). Dropping the
            # repaint is correct here; there is no window left to paint.
            pass

    def _reschedule(fn, page_obj, controls, attempt):
        """Retry a failed update one loop-tick later. Safe because Flet
        computes patches from its last-sent snapshot: a patch that raised
        was never sent, so nothing is corrupted - we just try again once
        whatever raced us has finished mutating."""
        if attempt > _UPDATE_MAX_RETRIES:
            log.exception("thread_safe_ui: page.update() failed after %d attempts",
                          attempt)
            return
        try:
            loop.call_soon_threadsafe(_deferred_update, fn, page_obj, controls, attempt)
        except RuntimeError:
            pass  # window gone mid-retry; nothing left to paint

    def _deferred_update(fn, page_obj, controls, _retries=0):
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
                _safe_update(fn, page_obj, controls)
                return
            try:
                loop.call_soon_threadsafe(_deferred_update, fn, page_obj, controls, _retries + 1)
            except RuntimeError:
                pass
            return
        _safe_update(fn, page_obj, controls)

    def _safe_update(fn, page_obj, controls):
        try:
            with TREE_LOCK:
                fn(page_obj, *controls)
        except Exception:
            # Never let a repaint failure kill the event loop - that would take
            # the whole window down over a cosmetic update. One quiet retry;
            # only give up (with the traceback) after that.
            _reschedule(fn, page_obj, controls, 1)

    type(page).update = update
    _installed = True
    log.info("thread_safe_ui: page.update() is now safe from any thread")
    return True
