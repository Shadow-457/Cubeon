"""Windows-only custom window decoration: the policy half (no Flet here).

WHY THIS EXISTS
---------------
On Windows the launcher is drawn with the OS's own title bar, so the window
carries TWO headers stacked: the system bar (app icon + "Cubeon" + min/max/
close) and Cubeon's own branded top bar (cube mark, wordmark, nav icons).
Reported from the Windows VM on 2026-10-17 with a screenshot: the native bar
sits outside the design system and duplicates the brand, so the window reads as
"unfinished" instead of as Cubeon.

The fix is a FRAMELESS window whose EXISTING top bar becomes the title bar:
`ft.WindowDragArea` for move + double-click-maximize, our own min/max/close
buttons painted on the Cubeon palette (`ui/window_chrome.py`), and explicit
edge hot-zones wired to `Window.start_resizing` for resize.

WHY IT IS OPT-IN, AND WHY WINDOWS ONLY
- The flag is `custom_window_chrome` (Settings > "Custom window frame"), and
  the env var ``CUBEON_CUSTOM_CHROME`` overrides it either way so the VM can
  flip it without touching config.json. Default OFF: the native path stays the
  safe default until the frameless window has been verified on real Windows.
- Windows only, deliberately. The window lifecycle on Linux/GTK in this repo is
  load-bearing and fragile (see agents/docs/module-map.md - the hidden start,
  the three-way reveal, the OpenGL-frame timeout), and a custom frame buys
  nothing there.
- It cannot be verified from the Linux dev box: Wine does not honour flet's
  hidden start, so the reveal path under a frameless window is a real-Windows
  question. That is exactly why this is a flag and not a rewrite.

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

    True only when the platform is Windows AND the user asked for it - via the
    ``CUBEON_CUSTOM_CHROME`` env var (truthy OR falsy, it wins outright) or the
    ``custom_window_chrome`` config key.

    Never raises: a malformed config (or a cfg-like object with no .get) must
    fall back to the native frame rather than take the launcher down with it.
    """
    if (sys.platform if platform is None else platform) != "win32":
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
        return bool(cfg.get(CONFIG_KEY, False))
    except Exception:
        return False


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
