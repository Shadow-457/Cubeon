"""Coalesce read-only UI refreshes; paint only the newest completed request."""
import logging
import threading

from . import thread_safe_ui


class BackgroundRefresh:
    def __init__(self, read, apply, *, name, failed=None):
        self.read, self.apply, self.name = read, apply, name
        self.failed = failed
        self._lock = threading.Lock()
        self._generation = 0
        self._pending = None
        self._running = False

    def invalidate(self):
        with self._lock:
            self._generation += 1
            self._pending = None
            return self._generation

    def request(self, *args):
        with self._lock:
            self._generation += 1
            self._pending = (self._generation, args)
            if self._running:
                return
            self._running = True
        try:
            threading.Thread(target=self._work, daemon=True, name=self.name).start()
        except Exception:
            with self._lock:
                self._running = False
            raise

    def _work(self):
        while True:
            with self._lock:
                request, self._pending = self._pending, None
                if request is None:
                    self._running = False
                    return
            generation, args = request
            try:
                value = self.read(*args)
                with thread_safe_ui.TREE_LOCK:
                    with self._lock:
                        current = generation == self._generation
                    if current:
                        self.apply(value)
            except Exception as error:
                logging.getLogger(__name__).warning('%s refresh failed', self.name, exc_info=True)
                with thread_safe_ui.TREE_LOCK:
                    with self._lock:
                        current = generation == self._generation
                    if current and self.failed:
                        try:
                            self.failed(error)
                        except Exception:
                            logging.getLogger(__name__).exception('%s failure feedback failed', self.name)
