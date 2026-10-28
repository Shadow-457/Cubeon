"""Custom window decoration (Windows + Linux): the policy half (no Flet here).

WHY THIS EXISTS
---------------
On Windows the launcher is drawn with the OS's own title bar, so the window
carries TWO headers stacked: the system bar (app icon + "Cubeon" + min/max/
close) and Cubeon's own branded top bar (cube mark, wordmark, nav icons).
Reported from the Windows VM on 2026-10-17 with a screenshot: the native bar
sits outside the design system and duplicates the brand, so the window reads as
"unfinished" instead of as Cubeon. The same double header shows on Linux/GTK
under most desktops, and the user asked for the branded frame there too
(2026-10-26).

The fix is a FRAMELESS window whose EXISTING top bar becomes the title bar:
`ft.WindowDragArea` for move + double-click-maximize, our own min/max/close
buttons painted on the Cubeon palette (`ui/window_chrome.py`), and explicit
edge hot-zones wired to `Window.start_resizing` for resize.

WHY IT IS A FLAG
- The flag is `custom_window_chrome` (Settings > "Custom window frame"), and
  the env var ``CUBEON_CUSTOM_CHROME`` overrides it either way so a machine can
  flip it without touching config.json.
- Default ON for Linux (the desktop the user runs, 2026-10-26 ask) and OFF for
  Windows (the frameless reveal still needs a real-Windows check). An explicit
  config value always wins, and ``CUBEON_CUSTOM_CHROME=0`` is the escape hatch
  if a frameless window ever misbehaves on a user's machine.
- macOS is excluded: the window lifecycle there is untested and the app has no
  Mac-specific reveal work.

WHAT LIVES HERE
Everything decidable without a display: the enablement policy, the geometry of
the resize hot-zones, and the maximized-state machine. main.py owns only the
widgets. Keeping this Flet-free is what lets `tools/test_winchrome.py` pin the
decisions on a bare interpreter.
"""
from __future__ import annotations

import os
import sys

__all__ = [
    "CONFIG_KEY",
    "ENV_FLAG",
    "EDGE_BAND",
    "CORNER_BOX",
    "RESIZE_EDGES",
    "custom_chrome_enabled",
    "maximize_state",
    "native_maximized",
]

# The config.json key (see cubeon/config.py) and its env override. The env var
# wins when set, in BOTH directions: "0"/"false" force the native frame back on
# even if the config says yes, which is the escape hatch if the frameless
# window ever misbehaves on a user's machine.
CONFIG_KEY = "custom_window_chrome"
ENV_FLAG = "CUBEON_CUSTOM_CHROME"

_TRUTHY = ("1", "true", "yes", "on")
_FALSY = ("0", "false", "no", "off")

# Edge hot-zone sizes, in logical pixels. A frameless window can lose the
# OS resize border (window_manager's setAsFrameless rebuilds the window style),
# so the resize handles are ours. 6px matches Windows' own thin border; the
# corners are bigger so the diagonal cursors have a comfortable target.
EDGE_BAND = 6
CORNER_BOX = 14

# The eight resize hot-zones, laid into a ft.Stack over the whole window.
#
# ORDER IS LOAD-BEARING: a Flet Stack paints (and hit-tests) later children
# first, and each band spans the full edge, so the two bands ALWAYS overlap in
# each corner square. The corners must therefore come AFTER the edges or a
# diagonal drag would be treated as a straight one. Pinned by
# tools/test_winchrome.py.
#
# Each entry is positioned with Flet's left/top/right/bottom semantics: an
# unset side is simply absent, so a top band is left=0/right=0/height=BAND.
RESIZE_EDGES = (
    {"edge": "top", "left": 0, "top": 0, "right": 0, "height": EDGE_BAND,
     "cursor": "RESIZE_UP"},
    {"edge": "bottom", "left": 0, "right": 0, "bottom": 0, "height": EDGE_BAND,
     "cursor": "RESIZE_DOWN"},
    {"edge": "left", "left": 0, "top": 0, "bottom": 0, "width": EDGE_BAND,
     "cursor": "RESIZE_LEFT"},
    {"edge": "right", "right": 0, "top": 0, "bottom": 0, "width": EDGE_BAND,
     "cursor": "RESIZE_RIGHT"},
    # -- corners (last: they win the hit-test in the overlap) --
    {"edge": "topLeft", "left": 0, "top": 0, "width": CORNER_BOX,
     "height": CORNER_BOX, "cursor": "RESIZE_UP_LEFT_DOWN_RIGHT"},
    {"edge": "topRight", "right": 0, "top": 0, "width": CORNER_BOX,
     "height": CORNER_BOX, "cursor": "RESIZE_UP_RIGHT_DOWN_LEFT"},
    {"edge": "bottomLeft", "left": 0, "bottom": 0, "width": CORNER_BOX,
     "height": CORNER_BOX, "cursor": "RESIZE_UP_RIGHT_DOWN_LEFT"},
    {"edge": "bottomRight", "right": 0, "bottom": 0, "width": CORNER_BOX,
     "height": CORNER_BOX, "cursor": "RESIZE_UP_LEFT_DOWN_RIGHT"},
)


def custom_chrome_enabled(cfg, *, platform=None, env=None) -> bool:
    """Whether the frameless custom frame should be used.

    Supported on Windows and Linux (macOS is excluded). The
    ``CUBEON_CUSTOM_CHROME`` env var wins outright in both directions; an
    explicit ``custom_window_chrome`` config value is next; otherwise BOTH
    supported platforms default ON (Linux since 2026-10-26, Windows since
    2026-10-28 when the Windows 10 reports came in).

    A stored ``None`` (the current default) or an absent key means "this user
    never chose", which is the only way to reach the platform default: a
    persisted ``False`` is read as a deliberate OFF and stays OFF.

    Never raises: a malformed config (or a cfg-like object with no .get) must
    fall back to the platform default rather than take the launcher down.
    """
    plat = sys.platform if platform is None else platform
    supported = plat == "win32" or str(plat).startswith("linux")
    if not supported:
        return False
    env = os.environ if env is None else env
    try:
        raw = env.get(ENV_FLAG)
    except Exception:
        raw = None
    if raw is not None:
        token = str(raw).strip().lower()
        if token in _TRUTHY:
            return True
        if token in _FALSY:
            return False
        # An unparseable value is not an instruction - fall through to config.
    try:
        configured = cfg.get(CONFIG_KEY, None)
    except Exception:
        configured = None
    if configured is not None:
        return bool(configured)
    # No explicit choice: both supported platforms get the branded frame.
    # Windows joined Linux here on 2026-10-28 - it had been held OFF pending a
    # real-Windows reveal check, and the reports that came back were Windows 10
    # users asking where their branded frame was. The reveal paths it was gated
    # on (forced visible transition, to_front(), the winwindow.py backstop) are
    # all in main.py and all run for a frameless window; CUBEON_CUSTOM_CHROME=0
    # remains the escape hatch for a machine where it misbehaves.
    return True


def maximize_state(event_name, current):
    """The new maximized state for a window event, or ``current`` untouched.

    ``WindowDragArea``'s double-click maximizes through window_manager itself
    (a native call, not a Python property write), and the user can also
    Win+Up / snap, so the state cannot be inferred from our own clicks: it is
    tracked from the events flet delivers.

    Only ``maximize``/``unmaximize`` are mapped. ``restore`` is NOT mapped to
    False on purpose - flet's RESTORE event means "restored from a MINIMIZED
    state", which says nothing about maximization, and a window can be both.
    """
    ev = str(event_name or "").split(".")[-1].strip().lower()
    if ev == "maximize":
        return True
    if ev == "unmaximize":
        return False
    return current


def native_maximized(pid=None, *, title="Cubeon"):
    """Ask the OS whether the real window is maximized: True/False/None.

    WHY THIS EXISTS (2026-10-23 report): "I can't resize the window - it says
    the window is maximized but it isn't; clicking maximize twice fixes it."
    The Python-side ``page.window.maximized`` is what we LAST WROTE, not what
    the window manager actually did. If a saved geometry asked for maximized
    on a hidden window and the WM ignored it, every later click toggled a lie:
    the first click "restored" a normal window (no visible change), the second
    maximized it. The glyph and the resize hot-zones were wrong too.

    Windows only, because that is the only platform with the custom frame
    (see ``custom_chrome_enabled``). The flet client is a SEPARATE process, so
    the window is found by process id when we have it, else by title. Returns
    ``None`` when it cannot tell - callers must keep their last known state.

    Never raises: a crash-report path must not take the launcher down.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsZoomed.argtypes = [wintypes.HWND]
        user32.IsZoomed.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _visit(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if pid:
                    owner = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                    if int(owner.value) != int(pid):
                        return True
                else:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length <= 0:
                        return True
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if title and buf.value.strip() != title:
                        return True
                found.append(hwnd)
                return False  # first match wins
            except Exception:
                return True

        user32.EnumWindows(_visit, 0)
        if not found:
            return None
        return bool(user32.IsZoomed(found[0]))
    except Exception:
        return None
