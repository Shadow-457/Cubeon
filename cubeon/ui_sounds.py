"""Optional local launch/error cues. Off by default; no audio dependency or polling."""
import logging
import os
import shutil
import subprocess
import sys
import threading
import time

_lock = threading.Lock()
_cfg = None
_assets = None
_busy = False
_last = float('-inf')


def configure(cfg, assets_dir):
    global _cfg, _assets
    with _lock:
        _cfg, _assets = cfg, assets_dir


def _play_file(path):
    if sys.platform == 'win32':
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        return
    choices = ('afplay',) if sys.platform == 'darwin' else ('paplay', 'aplay')
    player = next((p for name in choices if (p := shutil.which(name))), None)
    if player:
        subprocess.run([player, path], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=2)


def play(kind):
    global _busy, _last
    with _lock:
        if kind not in {'launch', 'error'} or not _cfg or not _cfg.get('ui_sounds', False):
            return False
        now = time.monotonic()
        if _busy or now - _last < 2 or not _assets:
            return False
        path = os.path.join(_assets, 'feedback', kind + '.wav')
        if not os.path.isfile(path):
            return False
        _busy, _last = True, now

    def worker():
        global _busy
        try:
            _play_file(path)
        except Exception:
            logging.getLogger(__name__).debug('feedback sound unavailable', exc_info=True)
        finally:
            with _lock:
                _busy = False

    try:
        threading.Thread(target=worker, name='cubeon-sound', daemon=True).start()
        return True
    except Exception:
        with _lock:
            _busy = False
        return False
