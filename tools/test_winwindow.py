"""
Offline suite for cubeon/winwindow.py - the Windows-only backstop that shows
the launcher's window at the OS level when flet's own reveal does not.

No Windows required: the user32 layer and the pid provider are injected, so the
poll policy, the filters and the failure logging are all exercised for real on
Linux. What cannot be tested here is user32 itself (that ShowWindow really
un-hides a window) - which is exactly why the module LOGS its outcome on a
machine we don't have.

Run: python3 tools/test_winwindow.py
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import winwindow  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


class _LogCapture(logging.Handler):
    """Records (level, message) so the failure paths can be asserted."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))

    def text(self, level=logging.INFO):
        return " | ".join(m for lvl, m in self.records if lvl >= level)


class FakeApi:
    """A user32 stand-in: windows per pid, hidden until `show` is called."""

    def __init__(self, windows, become_visible_after=1, raise_on_show=False):
        self._by_pid = windows          # {pid: [hwnd, ...]}
        self.visible = set()
        self.shown = []
        self.calls = 0
        self._after = become_visible_after
        self._raise = raise_on_show

    def handles_of(self, pids):
        self.calls += 1
        out = []
        for pid in pids:
            out.extend(self._by_pid.get(pid, []))
        return out

    def is_visible(self, hwnd):
        return hwnd in self.visible

    def show(self, hwnd):
        self.shown.append(hwnd)
        if self._raise:
            raise OSError("ShowWindow failed")
        if len(self.shown) >= self._after:
            self.visible.add(hwnd)


def with_log(fn):
    """Run fn with the module logger captured; returns (result, handler).

    The level is forced to DEBUG too: without it the root logger's WARNING
    default would swallow the INFO line this module's diagnosis depends on,
    and the test would be asserting against an empty capture.
    """
    cap = _LogCapture()
    prev_level = winwindow.log.level
    winwindow.log.setLevel(logging.DEBUG)
    winwindow.log.addHandler(cap)
    try:
        return fn(), cap
    finally:
        winwindow.log.removeHandler(cap)
        winwindow.log.setLevel(prev_level)


print("\n1. off Windows it is a no-op, and never raises")
started = time.monotonic()
res, cap = with_log(lambda: winwindow.ensure_client_window_visible(timeout=3.0))
check("returns False without user32 (os.name != nt)", res is False)
check("returns immediately, it does not poll out its timeout",
      time.monotonic() - started < 1.0, f"{time.monotonic() - started:.2f}s")

print("\n2. a window that is already visible is left alone")
api = FakeApi({4321: [0x10]}, become_visible_after=0)
api.visible.add(0x10)
started = time.monotonic()
res, cap = with_log(lambda: winwindow.ensure_client_window_visible(
    timeout=5.0, interval=0.5, api=api, pids_of=lambda assets: [4321]))
check("reports success", res is True)
check("one probe only, no timeout wait", time.monotonic() - started < 0.4,
      f"{time.monotonic() - started:.2f}s")
check("never called ShowWindow on a visible window", api.shown == [], str(api.shown))

print("\n3. a hidden client window is shown and then verified")
api = FakeApi({4321: [0x20]})
res, cap = with_log(lambda: winwindow.ensure_client_window_visible(
    timeout=5.0, interval=0.05, api=api, pids_of=lambda assets: [4321]))
check("reports success after showing it", res is True)
check("ShowWindow was called on the hidden handle", api.shown == [0x20], str(api.shown))
check("it logged that flet's reveal was not enough",
      "asking Windows to show it" in cap.text(logging.INFO), cap.text(logging.INFO))
check("it re-checked visibility instead of trusting ShowWindow", api.calls >= 2,
      f"handles_of called {api.calls}x")

print("\n4. a window that stays hidden ends as a logged failure, not a hang")
api = FakeApi({4321: [0x30]}, become_visible_after=10 ** 9)
started = time.monotonic()
res, cap = with_log(lambda: winwindow.ensure_client_window_visible(
    timeout=0.3, interval=0.05, api=api, pids_of=lambda assets: [4321]))
elapsed = time.monotonic() - started
check("returns False", res is False)
check("honored the timeout (0.3s, not the default 10s)", elapsed < 1.5,
      f"{elapsed:.2f}s")
check("warned that the window exists but stays hidden",
      "still has no VISIBLE window" in cap.text(logging.WARNING),
      cap.text(logging.WARNING))
check("kept trying before giving up", len(api.shown) >= 2, str(api.shown))

print("\n5. no client window at all is a different, also-logged failure")
api = FakeApi({})
res, cap = with_log(lambda: winwindow.ensure_client_window_visible(
    timeout=0.2, interval=0.05, api=api, pids_of=lambda assets: [4321]))
check("returns False", res is False)
check("says the client never created a window",
      "no window process to show" in cap.text(logging.WARNING),
      cap.text(logging.WARNING))
check("never called ShowWindow when there was nothing to show", api.shown == [])

print("\n6. the pid provider is re-run while no window exists yet")
seen = {"n": 0}


def _late_pids(assets):
    seen["n"] += 1
    return [4321] if seen["n"] > 1 else []


api = FakeApi({4321: [0x40]})
res, cap = with_log(lambda: winwindow.ensure_client_window_visible(
    timeout=3.0, interval=0.05, api=api, pids_of=_late_pids))
check("a client that starts a beat later is still found and shown", res is True)
check("the slow client's handle got ShowWindow", api.shown == [0x40], str(api.shown))

print("\n7. nothing this module does may raise into its caller")
api = FakeApi({4321: [0x50]}, raise_on_show=True)
res, cap = with_log(lambda: winwindow.ensure_client_window_visible(
    timeout=0.2, interval=0.05, api=api, pids_of=lambda assets: [4321]))
check("a failing ShowWindow degrades to False", res is False)
check("pids_of raising is swallowed too",
      with_log(lambda: winwindow.ensure_client_window_visible(
          timeout=0.1, api=FakeApi({}),
          pids_of=lambda assets: (_ for _ in ()).throw(OSError("gone"))))[0] is False)

print("\n8. what it is allowed to touch - the two-factor process rule")
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "cubeon", "winwindow.py"), encoding="utf-8").read()
check("candidates must be named like the flet client",
      '"flet" not in (info.get("name") or "").lower()' in src,
      "a name filter is what keeps Minecraft's java out")
check("and be our child OR carry our assets dir",
      'info.get("ppid") == me or (assets_dir and assets_dir in cmdline)' in src,
      "name alone would touch a second Cubeon instance's window")
check("no process-terminating call anywhere in it",
      all(tok not in src for tok in ("os.kill", ".terminate(", ".kill(",
                                     ".send_signal(")),
      "this module may only SHOW a window, never end a process")
check("user32 is reached through the API object, not from the policy loop",
      src.count("self._user32.") >= 3 and "SetForegroundWindow" not in src,
      "the backstop shows the window; focus stealing is to_front()'s job")
check("it takes the pid list by injection for tests",
      "api=None," in src and "pids_of=None" in src)

print("\n9. the API object declares real signatures (64-bit handles)")
check("argtypes set on every user32 entry point",
      all(f"user32.{name}.argtypes" in src for name in
          ("EnumWindows", "GetWindowThreadProcessId", "GetWindowLongW",
           "GetWindowRect", "IsWindowVisible", "IsIconic", "ShowWindow")),
      "an undeclared HWND truncates to 32 bits on x64")
check("the EnumWindows callback type is built at runtime, not import",
      "ctypes.WINFUNCTYPE" in src and "ctypes.WINFUNCTYPE(" not in src.split(
          "def __init__")[0],
      "WINFUNCTYPE does not exist off Windows, so the module must import there")
check("restores a minimized window with SW_RESTORE rather than SW_SHOW",
      "self.SW_RESTORE if self._user32.IsIconic(hwnd) else self.SW_SHOW" in src)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
