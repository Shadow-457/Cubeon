"""Coordinate native window close requests without racing Flet session teardown."""
import logging
import threading

log = logging.getLogger(__name__)


class WindowCloser:
    """One native request at a time; a closed session means closing succeeded."""

    def __init__(self, page, on_state_change=None):
        self.page = page
        self.on_state_change = on_state_change
        self._lock = threading.Lock()
        self._closed = False
        self._scheduled = False
        self._inflight = False

    def mark_closed(self):
        with self._lock:
            self._closed = True
        if self.on_state_change:
            self.on_state_change(True)

    async def close(self):
        with self._lock:
            if self._closed or self._inflight:
                return True
            self._inflight = True
        if self.on_state_change:
            self.on_state_change(True)
        try:
            await self.page.window.close()
        except RuntimeError as error:
            if str(error) != "Session closed":
                log.exception("Could not close the launcher window")
                if self.on_state_change:
                    self.on_state_change(False)
                return False
            # The native window/session disappeared before its RPC replied.
        except Exception:
            log.exception("Could not close the launcher window")
            if self.on_state_change:
                self.on_state_change(False)
            return False
        finally:
            with self._lock:
                self._inflight = False
        self.mark_closed()
        return True

    async def _requested_close(self):
        try:
            return await self.close()
        finally:
            with self._lock:
                self._scheduled = False

    def request(self):
        with self._lock:
            if self._closed or self._scheduled or self._inflight:
                return True
            self._scheduled = True
        try:
            # Flet's completion callback re-raises uncaught coroutine errors.
            # Schedule the wrapper so the expected Session-closed race is handled.
            self.page.run_task(self._requested_close)
            return True
        except RuntimeError as error:
            if str(error) == "Session closed":
                self.mark_closed()
                return True
            log.exception("Could not schedule launcher window close")
        except Exception:
            log.exception("Could not schedule launcher window close")
        with self._lock:
            self._scheduled = False
        return False
