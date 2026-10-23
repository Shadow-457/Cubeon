"""The hero PLAY button must survive a real pointer: hit-test regressions.

Headless harnesses can fire on_click directly, so they can never see what a
REAL window does when a painted layer sits on top of a button and absorbs the
tap. That is exactly how PLAY died (2026-10-18/19): the liquid-glass commit
added the sheen sweep as the LAST child of the footer Stack - a full-size
layer painted OVER the button, opaque to hit tests whenever the pointer was
inside it (hover = opacity 1, and every click follows a hover). The user
clicked PLAY, nothing happened, and the session log showed zero handler
activity.

These checks are static (source-shape) because the failure mode only exists
with a real pointer. They pin the invariant:
  1. play_sheen.control is a DESCENDANT of play_button's content (taps land
     on the widget that owns on_click), and
  2. nothing is painted as a sibling behind or above the button in the footer.

Run: python3 tools/test_play_hit_testing.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()

_passed, _failed = 0, 0


def ok(condition, message):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ok  {message}")
    else:
        _failed += 1
        print(f"  FAIL  {message}")


# --------------------------------------------------------------------------
print("sheen placement (the real-window click eater)")

# Extract the play_button creation block.
m = re.search(r"    play_button = ft\.Container\(.*?\n    \)\n", src, re.S)
ok(m is not None, "play_button block found")
button_block = m.group(0) if m else ""

# The sheen must be built AFTER the button (it wraps the content) and the
# content must become a Stack holding the row AND the sheen.
m2 = re.search(
    r"    play_button\.content = ft\.Stack\(\s*\[.*?play_sheen\.control,",
    src, re.S)
ok(m2 is not None,
   "play_button.content is a Stack that CONTAINS play_sheen.control "
   "(a descendant, so taps reach on_click)")

# ...and the sheen must NOT be a sibling painted after the button anywhere.
# The footer used to be a Stack (glow + button); the glow was removed on
# 2026-10-23, so the button now sits directly in the footer Row. If a Stack
# ever comes back around it, the sheen-inside rule above still has to hold.
footer = re.search(
    r"ft\.Row\(\s*\[\s*ft\.Container\(expand=True\),\s*"
    r"ft\.Container\(width=280, content=play_button\),\s*\],",
    src, re.S)
ok(footer is not None,
   "the footer mounts the button directly (no painted layer behind/above it)")
footer_block = footer.group(0) if footer else ""
ok("play_sheen" not in footer_block,
   "the footer no longer paints play_sheen ON TOP of the button")
ok("hero_glow" not in src,
   "the Play/QUIT aura is gone (2026-10-23 user ask)")

# --------------------------------------------------------------------------
print("the button itself")
ok("on_click=_main_action_click" in button_block,
   "on_click is _main_action_click (play / cancel / quit by state)")
ok("ink=False" in button_block, "ink=False (no ripple, hand-painted affordance)")

# The working mode must not disable the button (the FIXING MODS... lock).
ok(not re.search(r'"working".{0,900}play_button\.disabled = True', src, re.S),
   "the background-repair mode never disables PLAY (2026-10-18 lock)")

print()
print(f"{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
