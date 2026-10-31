"""Shared install claims and feedback for browse rows and open detail dialogs."""
import math
import re
import weakref

from cubeon import status_text, thread_safe_ui


def progress_text(done, total, *, batch=False, eta=None):
    """Known totals produce bounded percentages; unknown byte totals show bytes."""
    done = max(0, float(done))
    total = float(total or 0)
    if not math.isfinite(done) or not math.isfinite(total):
        return "Downloading…"
    suffix = f" · {eta}" if eta else ""
    if total <= 0:
        return f"Downloading… {done / 1024:.0f} KB{suffix}" if not batch else "Downloading…"
    pct = min(100, int(done * 100 / total))
    files = int(total)
    file_note = f" (file {min(int(done) + 1, files)}/{files})" if batch and files > 1 else ""
    return f"Downloading… {pct}%{file_note}{suffix}"


def compact_status(text):
    """Keep progress visible inside a 136px action; the tooltip carries full detail."""
    percent = re.search(r"\b\d{1,3}%", text)
    if percent:
        return percent.group()
    size = re.search(r"\b\d+(?:\.\d+)?\s*(?:KB|MB|GB)\b", text)
    if size:
        return size.group()
    if text.startswith("Finding"):
        return "Finding file"
    if text.startswith("Downloading"):
        return "Downloading"
    if text.startswith("Preparing"):
        return "Preparing"
    return "Installing"


class InstallFeedback:
    def __init__(self):
        self.busy = False
        self.text = ""
        self.filename = None
        self.result = None
        self.result_id = 0
        self.note = None
        self._controls = []

    def watch(self, control, paint):
        # The control owns its callback, so closed dialogs/evicted rows can be collected.
        with thread_safe_ui.TREE_LOCK:
            control._cubeon_install_paint = paint
            self._controls.append(weakref.ref(control))
            paint(self)

    def _emit(self):
        alive = []
        for ref in self._controls:
            control = ref()
            if control is not None:
                alive.append(ref)
                control._cubeon_install_paint(self)
                thread_safe_ui.refresh(control)
        self._controls = alive

    def start(self, filename=None, text="Finding file..."):
        with thread_safe_ui.TREE_LOCK:
            if self.busy:
                return False
            self.busy = True
            self.result = None
            self.note = None
            self.filename = filename
            self.text = text
            self._emit()
            return True

    def status(self, text):
        with thread_safe_ui.TREE_LOCK:
            self.text = status_text.human(text)
            self._emit()

    def finish(self, filename=None, error=None, *, note=None):
        with thread_safe_ui.TREE_LOCK:
            self.busy = False
            self.filename = filename or self.filename
            self.result = "error" if error else "success"
            self.result_id += 1
            self.text = status_text.human(error) if error else "Installed"
            self.note = note if not error else None
            self._emit()


class InstallRegistry:
    def __init__(self):
        self._jobs = weakref.WeakValueDictionary()

    def project(self, target, *identities):
        keys = [(target, str(identity).strip().lower()) for identity in identities if identity]
        with thread_safe_ui.TREE_LOCK:
            job = next((self._jobs[key] for key in keys if key in self._jobs), None) or InstallFeedback()
            for key in keys:
                self._jobs[key] = job
            return job
