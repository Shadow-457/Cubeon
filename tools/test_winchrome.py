"""
Offline suite for cubeon/winchrome.py - the policy half of the Windows custom
window frame (frameless window, our own title bar).

No Windows required, and no Flet widgets either: the module is deliberately
Flet-free so the decisions it makes - WHEN the frame is custom, WHERE the resize
hot-zones sit, and what a window event means for the maximized state - are all
exercised for real on Linux. The widgets themselves are built and inspected by
tools/test_ui_smoke.py (section 13b).

What cannot be tested here is Windows itself: whether `frameless` survives the
hidden-start reveal, and whether the hot-zones actually resize. Those are the
questions the flag exists to let a real VM answer.

Run: python3 tools/test_winchrome.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft  # noqa: E402  (only to validate the enum/cursor NAMES)

from cubeon import winchrome  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


print("\n1. the frame is available on Windows and Linux, never macOS")
check("Linux gets the custom frame BY DEFAULT (2026-10-26 user ask)",
      winchrome.custom_chrome_enabled({"custom_window_chrome": True},
                                      platform="linux", env={}) is True)
check("...and even with no config key at all",
      winchrome.custom_chrome_enabled({}, platform="linux", env={}) is True,
      "the compact branded frame is the Linux default")
check("macOS never gets it",
      winchrome.custom_chrome_enabled({"custom_window_chrome": True},
                                      platform="darwin", env={}) is False)
check("a bare Windows install is still OFF by default",
      winchrome.custom_chrome_enabled({}, platform="win32", env={}) is False,
      "the native frame must stay the default until a VM has verified this")
check("Windows + the config key turns it on",
      winchrome.custom_chrome_enabled({"custom_window_chrome": True},
                                      platform="win32", env={}) is True)
check("an explicit OFF wins on Linux too",
      winchrome.custom_chrome_enabled({"custom_window_chrome": False},
                                      platform="linux", env={}) is False)

print("\n2. the env var is the escape hatch, and it wins outright")
check("CUBEON_CUSTOM_CHROME=1 forces it on",
      winchrome.custom_chrome_enabled(
          {"custom_window_chrome": False}, platform="win32",
          env={winchrome.ENV_FLAG: "1"}) is True)
check("...on any supported platform",
      winchrome.custom_chrome_enabled(
          {}, platform="linux", env={winchrome.ENV_FLAG: "1"}) is True,
      "the flag overrides the CONFIG, not the platform support")
check("but macOS is still excluded",
      winchrome.custom_chrome_enabled(
          {}, platform="darwin", env={winchrome.ENV_FLAG: "1"}) is False)
check("CUBEON_CUSTOM_CHROME=0 forces it back off",
      winchrome.custom_chrome_enabled(
          {"custom_window_chrome": True}, platform="win32",
          env={winchrome.ENV_FLAG: "0"}) is False,
      "the escape hatch has to work in BOTH directions")
check("the spellings people actually type are all understood",
      all(winchrome.custom_chrome_enabled(
              {}, platform="win32", env={winchrome.ENV_FLAG: v}) is b
          for v, b in (("1", True), ("true", True), ("YES", True), ("on", True),
                       ("0", False), ("false", False), ("Off", False))))
check("an unparseable value is not an instruction - it falls through",
      winchrome.custom_chrome_enabled(
          {"custom_window_chrome": True}, platform="win32",
          env={winchrome.ENV_FLAG: "maybe"}) is True)

print("\n3. a malformed config degrades to the native frame, never to a crash")
check("a cfg with no .get() is not a reason to take the launcher down",
      winchrome.custom_chrome_enabled(object(), platform="win32",
                                      env={}) is False)
check("...and an env mapping that raises is swallowed too",
      winchrome.custom_chrome_enabled(
          {"custom_window_chrome": True}, platform="win32",
          env=object()) is True,  # the config still answers
      "one broken source must not poison the other")
check("the config value is read by the documented key",
      winchrome.CONFIG_KEY == "custom_window_chrome",
      "cubeon/config.py, main.py and the Settings toggle all key off this")

print("\n4. the eight resize hot-zones actually sit on the edges")
edges = winchrome.RESIZE_EDGES
check("exactly eight: four edges, four corners",
      len(edges) == 8 and sorted(e["edge"] for e in edges) == sorted(
          ["top", "bottom", "left", "right",
           "topLeft", "topRight", "bottomLeft", "bottomRight"]))
check("every edge name is a real flet WindowResizeEdge value",
      all(any(e["edge"] == x.value for x in ft.WindowResizeEdge)
          for e in edges),
      "start_resizing() parses these by value - a typo would be silent")
check("every cursor is a real flet MouseCursor name",
      all(hasattr(ft.MouseCursor, e["cursor"]) for e in edges),
      "an unknown name silently degrades to a basic arrow")
for e in edges:
    name = e["edge"]
    pinned_x = [k for k in ("left", "right") if k in e]
    pinned_y = [k for k in ("top", "bottom") if k in e]
    check(f"the {name} zone is anchored to the window edge it resizes",
          len(pinned_x) >= 1 and len(pinned_y) >= 1
          and (e.get("width") is not None or e.get("height") is not None),
          f"position {e}")

print("\n5. the corner zones are painted last (they must win the hit-test)")
# Every band spans its whole edge, so a corner square is ALWAYS overlapped by
# two bands. A Flet Stack gives the hit to the LAST child, so if a corner ever
# moves above the bands, a diagonal drag silently becomes a straight one.
check("the four corners are the last four entries",
      [e["edge"] for e in edges][-4:] ==
      ["topLeft", "topRight", "bottomLeft", "bottomRight"],
      f"order is {[e['edge'] for e in edges]}")
_CORNER_NAMES = ("topLeft", "topRight", "bottomLeft", "bottomRight")
check("the corners are square and the bands are thin",
      all(e["width"] == e["height"] == winchrome.CORNER_BOX
          for e in edges if e["edge"] in _CORNER_NAMES)
      and all(min(e.get("width") or 10 ** 9, e.get("height") or 10 ** 9)
              == winchrome.EDGE_BAND
              for e in edges if e["edge"] not in _CORNER_NAMES)
      and winchrome.CORNER_BOX > winchrome.EDGE_BAND,
      "a corner has to be a comfortable diagonal target, wider than a band")

print("\n6. the maximized state follows the NATIVE events")
ms = winchrome.maximize_state
check("a maximize event means maximized", ms("maximize", False) is True)
check("an unmaximize event means not", ms("unmaximize", True) is False)
check("the window-event enum spellings work too",
      ms("WindowEventType.MAXIMIZE", False) is True
      and ms("WindowEventType.UNMAXIMIZE", True) is False,
      "main.py normalizes e.type, and both spellings have been seen")
check("RESTORE is NOT treated as unmaximize",
      ms("restore", True) is True,
      "flet's RESTORE means 'came back from MINIMIZED' - a window can be "
      "minimized AND maximized, so mapping it to False would flip the glyph "
      "off a maximized window")
check("any other event leaves the state alone",
      all(ms(name, current) is current
          for name in ("resize", "resized", "move", "moved", "focus", "blur",
                       "close", "hide", "show", "disconnect", None, "")
          for current in (True, False)))
check("it accepts whatever main.py hands it (never raises)",
      ms(object(), True) is True and ms(123, False) is False)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
