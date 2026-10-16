"""Windows: make the flet client's window actually visible.

The launcher's window process is started HIDDEN on purpose
(`ft.run(..., view=ft.AppView.FLET_APP_HIDDEN)` -> flet_desktop sets
FLET_HIDE_WINDOW_ON_START for the client), so the only transition the user
sees is the single reveal of the finished UI. Everything that reveals it is a
MESSAGE to that client (`page.window.visible = True`, `page.window.to_front()`),
and there is no build of the launcher in which "the message did not arrive" is
observable from inside the app - the process simply lives on INVISIBLE:

    Cubeon.exe in Task Manager, no window anywhere (reported 2026-10-15, and
    again on the shipped 1.1.2 build 2026-10-16). Nothing in cubeon.log,
    because a launcher that never shows a window cannot tell you anything.

Only real Windows is affected: Linux/GTK (and Wine) map the window anyway, so
the hidden start was never honoured there and the dev box never saw this.

This module asks the OS instead of the client. `ensure_client_window_visible`
finds OUR OWN flet client process (never another instance's, never Minecraft's
java), locates its top-level window and calls ShowWindow() - the one reveal
that does not depend on the client processing anything. It logs what it found
either way, so the next report of "no window" comes with evidence.

Windows-only by construction: with no user32 (i.e. anywhere else) every entry
point degrades to a no-op, so callers never need a platform guard. It BLOCKS
for up to `timeout` seconds - always call it from a worker thread, never from
flet's event loop (see main.py's `_backstop_window_visible`).
"""
import logging
import os
import time

log = logging.getLogger("cubeon.winwindow")

__all__ = ["client_pids", "Win32Windows", "ensure_client_window_visible"]

# A real launcher window is at least this big. Flutter's engine also owns
# tiny hidden helper windows; showing one of those would do nothing useful.
_MIN_DIM = 40


def client_pids(assets_dir=None) -> list:
    """PIDs of the flet desktop clients that belong to THIS launcher.

    Two-factor, the same rule `main._kill_flet_client` uses: the process is
    named like the client AND it is either our direct child or carries our
    assets dir in its command line. Name alone would touch a second Cubeon
    instance's window; the assets dir alone would match one too. Minecraft is
    a child of the launcher as well, so the name filter is what keeps java out.

    Never raises: an unreadable process (or no psutil) just isn't a candidate.
    """
    try:
        import psutil
    except Exception:
        log.debug("psutil unavailable", exc_info=True)
        return []
    me = os.getpid()
    pids = []
    for proc in psutil.process_iter(["pid", "name", "ppid", "cmdline"]):
        try:
            info = proc.info
            if "flet" not in (info.get("name") or "").lower():
                continue
            cmdline = " ".join(info.get("cmdline") or [])
            if info.get("ppid") == me or (assets_dir and assets_dir in cmdline):
                pids.append(info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


class Win32Windows:
    """The user32 calls this module needs, behind one tiny object.

    Split out from the policy loop so the loop can be tested on a machine with
    no user32 at all (the tests inject a stand-in for this).
    """

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    SW_SHOW = 5
    SW_RESTORE = 9

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._byref = ctypes.byref
        # The callback type only exists on Windows, so it is built here rather
        # than at module import.
        self._EnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32 = ctypes.windll.user32
        # Declaring signatures matters: an HWND is 64-bit on x64 and ctypes
        # would otherwise truncate it to 32 bits at the call boundary, i.e.
        # ShowWindow() on the wrong window in the best case and on garbage in
        # the worst.
        user32.EnumWindows.argtypes = [self._EnumProc, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.GetWindowRect.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        self._user32 = user32

    def handles_of(self, pids) -> list:
        """Top-level window handles owned by *pids* (helper windows filtered)."""
        wanted = {int(p) for p in pids}
        if not wanted:
            return []
        user32 = self._user32
        wintypes = self._wintypes
        found = []

        def _cb(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, self._byref(pid))
            if pid.value not in wanted:
                return True
            if user32.GetWindowLongW(hwnd, self.GWL_EXSTYLE) & self.WS_EX_TOOLWINDOW:
                return True  # an engine helper window, not the app's
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, self._byref(rect)):
                return True
            if (rect.right - rect.left) < _MIN_DIM or \
                    (rect.bottom - rect.top) < _MIN_DIM:
                return True  # a 0x0/1x1 shim
            found.append(int(hwnd))
            return True

        user32.EnumWindows(self._EnumProc(_cb), 0)
        return found

    def is_visible(self, hwnd) -> bool:
        return bool(self._user32.IsWindowVisible(hwnd))

    def show(self, hwnd) -> None:
        """Show a hidden window, restoring it first if it is minimized."""
        flag = self.SW_RESTORE if self._user32.IsIconic(hwnd) else self.SW_SHOW
        self._user32.ShowWindow(hwnd, flag)


def ensure_client_window_visible(assets_dir=None, timeout: float = 10.0,
                                 interval: float = 0.5, api=None,
                                 pids_of=None) -> bool:
    """Make sure this launcher has a visible window. Returns True if it does.

    Polls until a client window is visible, calling ShowWindow() on any that
    are not. Returns False on a non-Windows machine (no user32), when no client
    window exists at all (the client never started / died - nothing to show),
    or when Windows still reports it hidden after `timeout`. Never raises: the
    outcome is written to cubeon.log at WARNING level, which is the whole
    point of the backstop.

    `api` and `pids_of` are injection seams for the tests.
    """
    try:
        if api is None:
            if os.name != "nt":
                return False  # callers may call this unguarded
            api = Win32Windows()
        pids_of = pids_of or client_pids
        deadline = time.monotonic() + max(0.0, timeout)
        announced = False
        saw_window = False
        while True:
            handles = api.handles_of(pids_of(assets_dir))
            saw_window = saw_window or bool(handles)
            hidden = []
            for hwnd in handles:
                if api.is_visible(hwnd):
                    log.debug("client window 0x%x is visible", hwnd)
                    return True
                hidden.append(hwnd)
            for hwnd in hidden:
                try:
                    api.show(hwnd)
                except Exception:
                    log.debug("ShowWindow(0x%x) failed", hwnd, exc_info=True)
            if hidden and not announced:
                announced = True
                log.info("flet's reveal did not show the window - asking "
                         "Windows to show it (%d hidden client window(s))",
                         len(hidden))
            if time.monotonic() >= deadline:
                if saw_window:
                    log.warning(
                        "Cubeon still has no VISIBLE window after %.0fs: the "
                        "client's window exists but Windows reports it hidden "
                        "(ShowWindow did not take). Please report this with "
                        "cubeon.log.", timeout)
                else:
                    log.warning(
                        "Cubeon has no window process to show after %.0fs - the "
                        "flet client never created a top-level window. Please "
                        "report this with cubeon.log.", timeout)
                return False
            time.sleep(max(0.01, interval))
    except Exception:
        log.debug("window-visibility backstop failed", exc_info=True)
        return False
