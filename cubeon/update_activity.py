"""Wake the updater on existing game/download ownership transitions."""
import threading

_condition = threading.Condition()
_generation = 0
_watched = set()


def changed():
    global _generation
    with _condition:
        _generation += 1
        _condition.notify_all()


def generation():
    with _condition:
        return _generation


def wait(previous, cancel):
    with _condition:
        _condition.wait_for(lambda: _generation != previous or cancel.is_set())


def watch_process(pid):
    """A leftover game's/server's exit also wakes a reopened launcher."""
    import psutil
    try:
        process = psutil.Process(pid)
        key = (pid, process.create_time())
    except psutil.Error:
        changed()
        return
    with _condition:
        if key in _watched:
            return
        _watched.add(key)

    def exited():
        try:
            process.wait()
        except psutil.Error:
            pass
        finally:
            with _condition:
                _watched.discard(key)
            changed()
    threading.Thread(target=exited, daemon=True, name="cubeon-update-process-exit").start()


class Paused(Exception):
    pass


class ActivityGate:
    """Check ownership on edges; body reads never repeatedly scan the OS."""
    def __init__(self, busy, cancel, paused=None):
        self.busy = busy
        self.cancel = cancel
        self.paused = paused
        self._seen = -1
        self._reason = None

    def checkpoint(self, *, block=True):
        from .auto_update import _check_cancel
        while True:
            _check_cancel(self.cancel)
            current = generation()
            if current != self._seen:
                self._reason = self.busy() if self.busy else None
                self._seen = current
            if not self._reason:
                return
            if not block:
                raise Paused()
            if self.paused:
                self.paused(self._reason)
            wait(current, self.cancel)
