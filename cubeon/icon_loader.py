"""Bounded, coalesced artwork reads for content rows; no I/O on the UI loop."""
from collections import OrderedDict
import logging
import threading

from . import icons, thread_safe_ui


class IconLoader:
    def __init__(self, *, workers=8, limit=128, read=None):
        self.workers, self.limit = workers, limit
        self.read = read or icons.load_source
        self._lock = threading.Lock()
        self._pending = OrderedDict()
        self._callbacks = {}
        self._running = 0

    def request(self, url, callback):
        if not url:
            return
        with self._lock:
            if url in self._callbacks:
                self._callbacks[url].append(callback)
                return
            if len(self._callbacks) >= self.limit:
                return
            self._callbacks[url] = [callback]
            self._pending[url] = None
            if self._running >= self.workers:
                return
            self._running += 1
        try:
            threading.Thread(target=self._work, name='modpack-art', daemon=True).start()
        except Exception:
            with self._lock:
                self._running -= 1
                self._pending.pop(url, None)
                self._callbacks.pop(url, None)
            logging.getLogger(__name__).exception('Could not start artwork loader')

    def _work(self):
        while True:
            with self._lock:
                if not self._pending:
                    self._running -= 1
                    return
                url, _ = self._pending.popitem(last=False)
            source = None
            try:
                source = self.read(url)
            except Exception:
                logging.getLogger(__name__).debug('Artwork unavailable', exc_info=True)
            with self._lock:
                callbacks = self._callbacks.pop(url, [])
            if source:
                for callback in callbacks:
                    try:
                        with thread_safe_ui.TREE_LOCK:
                            callback(source)
                    except Exception:
                        logging.getLogger(__name__).debug('Artwork view retired', exc_info=True)
