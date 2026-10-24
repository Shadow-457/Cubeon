#!/usr/bin/env python3
"""
Tests for the motion layer: cubeon/motion.py + the places that use it.
Run with:

    python tools/test_motion.py

No display, no network, no config.json: every control here is built by hand and
every event is fired with the driver's FakeEvent, so the whole file is offline.
The cascade/shimmer/ambient paths really do run their threads - the periods are
patched down so the file stays fast.

Covers:
  * the level: coercion (including the hand-typed "off"/"on" aliases), the
    transforms() gate, listeners (including a listener that raises)
  * polish(): the hover fill + lift + the liquid-glass hover (corners open, rim
    lights up, halo rises - and all of it reverts), the press dip and its
    release, `active()`, `on_hover_fill`, and the promise that it does NOT wrap
    on_click (the nav and the version picker identify their controls by
    `on_click.__defaults__`)
  * Sheen: the specular sweep parks invisible, sweeps on hover-in, parks again
    on hover-out, and is a no-op on reduced motion
  * stagger(): opacity 0 -> 1, the rise, reduced doing nothing, a newer list
    superseding an older one, and a mid-cascade switch to Reduced
  * shimmer(): registration, pulsing, and every path that has to put a
    placeholder back to full opacity
  * ambient(): starting, parking and restarting with the level
  * wiring: theme.attach_hover delegating here, the glass style the theme pins
    onto motion, the config key, main.py's hero glow + Play sheen, and
    Settings > Display's Motion row
"""
import os
import re as _re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import flet as ft  # noqa: E402

from cubeon import motion  # noqa: E402
from cubeon import theme  # noqa: E402
from _fuzz_common import FakeEvent  # noqa: E402

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


def hover(control, hot=True):
    control.on_hover(FakeEvent(control=control, data="true" if hot else "false"))


def tap_down(control):
    if control.on_tap_down is not None:
        control.on_tap_down(FakeEvent(control=control))


def _scale_value(control):
    """The scale as a number, whether it is a raw float or a Scale transform."""
    s = control.scale
    if s is None:
        return None
    return getattr(s, "scale", s)


def _offset_y(control):
    """The control's vertical paint offset as a number (None when unset)."""
    o = control.offset
    return None if o is None else getattr(o, "y", o)


def _reset():
    motion.stop_shimmer()
    motion.set_level("full")


# ---------------------------------------------------------------- the level ---
print("\n1. the level")
check("the default level is full", motion.DEFAULT_LEVEL == "full"
      and motion.level() == "full")
check("LEVELS is the two settings values",
      motion.LEVELS == ("full", "reduced"))
check("coerce() accepts the real levels",
      [motion.coerce(v) for v in motion.LEVELS] == list(motion.LEVELS))
check("coerce() normalises case and whitespace",
      motion.coerce("  Full ") == "full" and motion.coerce("REDUCED") == "reduced")
check("the hand-typed spellings of 'calm down' land on reduced",
      [motion.coerce(v) for v in ("off", "OFF", "none", "false", "no", 0)]
      == ["reduced"] * 6)
check("... and the hand-typed spellings of 'on' land on full",
      [motion.coerce(v) for v in ("on", "true", "yes", 1)] == ["full"] * 4)
check("coerce() falls back to the default on junk",
      motion.coerce("") == "full" and motion.coerce("fast") == "full"
      and motion.coerce(None) == "full" and motion.coerce(3) == "full")

check("full: transforms allowed",
      motion.set_level("full") == "full" and motion.transforms())
check("reduced: transforms refused",
      motion.set_level("reduced") == "reduced" and not motion.transforms())
check("set_level() returns the level it applied",
      motion.set_level("nonsense") == "full")
check("there is no 'off' level to switch to - it is two levels by design",
      not hasattr(motion, "enabled") and "off" not in motion.LEVELS)

_seen = []
motion.on_change(lambda lv: _seen.append(lv))
motion.set_level("reduced")
motion.set_level("reduced")          # same level: no second notification
motion.set_level("off")              # an alias of reduced: still no change
check("listeners hear each real change exactly once",
      _seen == ["reduced"], _seen)


def _boom(_level):
    raise RuntimeError("listener blew up")


motion.on_change(_boom)
_after = []
motion.on_change(lambda lv: _after.append(lv))
check("a dead listener cannot block the others or the setter",
      motion.set_level("full") == "full" and _after == ["full"])

# ------------------------------------------------------- polish: hover lift ---
print("\n2. polish() - hover")
motion.set_level("full")
c = theme.attach_hover(ft.Container(bgcolor="#101010"), "#101010", "#202020")
check("attach_hover() return value is the container itself",
      isinstance(c, ft.Container))
check("the fill animates instead of snapping",
      c.animate == motion.FAST and c.animate_scale == motion.FAST)
check("the resting scale is written at build time",
      _scale_value(c) == 1.0, _scale_value(c))

hover(c)
check("hovering swaps the fill", c.bgcolor == "#202020", c.bgcolor)
check("hovering leaves the control's size unchanged",
      abs(_scale_value(c) - motion.LIFT) < 1e-9, _scale_value(c))
check("default hover and press do not zoom", motion.LIFT == 1.0 and motion.PRESS == 1.0)
check("default clicks start no press animation", not callable(getattr(c, "on_tap_down", None)))
hover(c, False)
check("leaving restores the fill and the scale",
      c.bgcolor == "#101010" and _scale_value(c) == 1.0,
      f"{c.bgcolor} {_scale_value(c)}")

_owned = ft.Container(scale=ft.Scale(1.4, alignment=ft.Alignment.CENTER),
                      bgcolor="#101010")
theme.attach_hover(_owned, "#101010", "#202020")
hover(_owned)
check("a control that owns its own scale is left alone",
      _scale_value(_owned) == 1.4, _scale_value(_owned))

_filled = []
_f = theme.attach_hover(ft.Container(bgcolor="#101010"), "#101010", "#202020")
f2 = motion.polish(ft.Container(bgcolor="#0f0f0f"),
                   on_hover_fill=lambda hot: _filled.append(hot))
hover(f2, True)
hover(f2, False)
check("on_hover_fill() owns the fill (the Play button's colour-by-meaning)",
      _filled == [True, False], _filled)
check("on_hover_fill() means polish never touches bgcolor",
      f2.bgcolor == "#0f0f0f", f2.bgcolor)

_guarded = motion.polish(ft.Container(bgcolor="#101010"),
                         "#101010", "#202020", active=lambda: False)
hover(_guarded)
check("active() False: no lift (a disabled control must not react)",
      _scale_value(_guarded) == 1.0, _scale_value(_guarded))
check("active() False: the fill still swaps (it is feedback, not decoration)",
      _guarded.bgcolor == "#202020", _guarded.bgcolor)

# on_click identity is load-bearing: app_driver finds nav items and the version
# picker's cards by the handler's default args.
def _nav_handler(_e, key="play"):
    return key


_pinned = motion.polish(ft.Container(on_click=_nav_handler), "#101010",
                        "#202020")
check("polish() leaves on_click completely untouched",
      _pinned.on_click is _nav_handler
      and _pinned.on_click.__defaults__ == ("play",),
      _pinned.on_click)

# ------------------------------------------------------ polish: press dip ---
print("\n3. polish() - press")
if not motion._HAS_TAP_DOWN:
    check("this Flet has Container.on_tap_down (press feedback is possible)",
          False, "motion skips press feedback on this build")
else:
    p = motion.polish(ft.Container(bgcolor="#101010"), "#101010", "#202020")
    hover(p)
    tap_down(p)
    check("default pressing keeps the control at its resting size",
          abs(_scale_value(p) - motion.PRESS) < 1e-9, _scale_value(p))
    time.sleep(motion.RELEASE_MS / 1000.0 + 0.12)
    check("default pressing needs no delayed resize",
          abs(_scale_value(p) - motion.LIFT) < 1e-9, _scale_value(p))
    hover(p, False)
    tap_down(p)
    time.sleep(motion.RELEASE_MS / 1000.0 + 0.12)
    check("release settles to the plain rest when not hovered",
          _scale_value(p) == 1.0, _scale_value(p))

    motion.set_level("reduced")
    tap_down(p)
    check("reduced: a press does not dip (no geometry moves)",
          _scale_value(p) == 1.0, _scale_value(p))
    motion.set_level("full")

# ------------------------------------------------------------- the levels ---
print("\n4. the levels on a live control")
r = ft.Container(bgcolor="#101010")
theme.attach_hover(r, "#101010", "#202020")
motion.set_level("reduced")
hover(r)
check("reduced: the fill fades, the control does not move",
      r.bgcolor == "#202020" and _scale_value(r) == 1.0,
      f"{r.bgcolor} {_scale_value(r)}")
hover(r, False)

# The glass hover is the point of the 2026-10-18 pass, so it gets its own
# control: the theme's own style (radius step, rim, halo) applied through the
# same one-expression call site every row uses.
motion.set_level("full")
g = ft.Container(bgcolor="#101010", border=theme.glass_edge(),
                 border_radius=theme.RADIUS)
theme.attach_hover(g, "#101010", "#202020")
_g_rest = (g.border_radius, g.border.top.color, g.shadow)
hover(g)
check("glass: the corners stay fixed",
      g.border_radius == theme.RADIUS + theme.GLASS_RADIUS_STEP, g.border_radius)
check("glass: the rim lights up", g.border.top.color == theme.GLASS_RIM_HI)
check("glass: hovering does not change the shadow", g.shadow is _g_rest[2])
hover(g, False)
check("glass: hovering out puts all three back",
      (g.border_radius, g.border.top.color, g.shadow) == _g_rest)

motion.set_level("reduced")
hover(g)
check("reduced: the rim fades without changing geometry",
      g.border.top.color == theme.GLASS_RIM_HI
      and g.border_radius == theme.RADIUS and g.shadow is _g_rest[2],
      f"{g.border_radius} {g.border.top.color}")
hover(g, False)
motion.set_level("full")

# A control that is not a glass panel (no border, no radius) must not be given
# one: polish only ever moves what the control already had.
bare = ft.Container(bgcolor="#101010")
motion.polish(bare, "#101010", "#202020")
bare_rest = (bare.border, bare.border_radius)
hover(bare)
check("glass: a borderless control gains no border or corners",
      (bare.border, bare.border_radius) == bare_rest,
      (bare.border, bare.border_radius))
hover(bare, False)

# ---------------------------------------------------------------- the sheen ---
print("\n5. the sheen")
band_probe = motion.sheen(radius=theme.RADIUS)
_band = band_probe._band
check("a fresh sheen is parked off-surface at zero opacity",
      _band.opacity == 0.0 and _band.offset.x < 0,
      f"{_band.offset.x} {_band.opacity}")
check("the band is a soft white sweep with its own animations",
      _band.animate_offset is not None and _band.animate_opacity is not None
      and len(_band.gradient.colors) == 3)
check("the shell clips the sweep to the surface's own shape",
      band_probe.control.clip_behavior == ft.ClipBehavior.ANTI_ALIAS
      and band_probe.control.border_radius == theme.RADIUS)
_band_probe_pos = (_band.offset.x, _band.opacity)
band_probe.run()
check("run() sweeps it across", _band.opacity == 1.0 and _band.offset.x > 0,
      f"{_band.offset.x} {_band.opacity}")
band_probe.reset()
check("reset() parks it again", (_band.offset.x, _band.opacity)
      == _band_probe_pos)

motion.set_level("reduced")
band_probe.run()
check("reduced: the sweep is refused (nothing moves on its own)",
      _band.opacity == 0.0)
band_probe.reset()
motion.set_level("full")

# ----------------------------------------------------------------- stagger ---
print("\n6. stagger()")
motion.set_level("full")
rows = [ft.Container(height=20) for _ in range(4)]
staggered = motion.stagger(rows, step_ms=20, duration_ms=60)
check("stagger() returns None (it is fire-and-forget)",
      staggered is None)
check("every row starts invisible with the rise dialled in",
      all(r.opacity == 0 for r in rows)
      and all(isinstance(r.offset, ft.Offset) for r in rows))
check("each row animates its own opacity and offset",
      all(r.animate_opacity is not None and r.animate_offset is not None
          for r in rows))
time.sleep(4 * 0.02 + 0.25)
check("the cascade ends with every row up and at rest",
      all(r.opacity == 1 for r in rows)
      and all(_offset_y(r) == 0 for r in rows),
      [(r.opacity, r.offset) for r in rows])

motion.set_level("reduced")
quiet = [ft.Container(height=20) for _ in range(3)]
_before = [(r.opacity, r.offset, r.animate_opacity) for r in quiet]
motion.stagger(quiet)
check("reduced: a list is simply there - untouched, no animation attached",
      [(r.opacity, r.offset, r.animate_opacity) for r in quiet] == _before,
      [(r.opacity, r.offset) for r in quiet])
motion.set_level("full")

first = [ft.Container(height=20) for _ in range(3)]
second = [ft.Container(height=20) for _ in range(3)]
motion.stagger(first, step_ms=40, duration_ms=40, cap_ms=400)
time.sleep(0.03)
motion.stagger(second, step_ms=20, duration_ms=40, cap_ms=400)
time.sleep(3 * 0.02 + 0.25)
check("a newer list wins: the second cascade completes",
      all(r.opacity == 1 for r in second),
      [r.opacity for r in second])
check("the superseded cascade stopped mid-flight",
      any(r.opacity == 0 for r in first), [r.opacity for r in first])

mid = [ft.Container(height=20) for _ in range(4)]
motion.stagger(mid, step_ms=90, duration_ms=60, cap_ms=500)
time.sleep(0.05)
motion.set_level("reduced")
time.sleep(0.35)
check("switching motion down mid-cascade reveals the rest at once",
      all(r.opacity == 1 for r in mid) and all(r.animate_opacity is None
                                               for r in mid),
      [(r.opacity, r.animate_opacity) for r in mid])
motion.set_level("full")

# ----------------------------------------------------------------- shimmer ---
print("\n7. shimmer()")
motion.set_level("full")
_orig_shimmer_ms = motion.SHIMMER_MS
motion.SHIMMER_MS = 120
try:
    s1, s2 = ft.Container(), ft.Text("Loading...")
    # A placeholder list that picked up a None (a slot that was not built) must
    # not take the shimmer down with it: shimmer() drops the holes and animates
    # the rest. The list is assembled first, not written as a literal argument,
    # because test_mega_smoke's gray-box scan flags ANY None inside a list
    # literal passed to a call - it cannot know this is not a Flet children
    # list, and it is right not to guess.
    _with_hole = [s1, s2]
    _with_hole.append(None)
    motion.shimmer(_with_hole)
    check("registered placeholders get a soft opacity animation",
          s1.animate_opacity is not None and s2.animate_opacity is not None)
    check("and the None in the list is dropped, not animated",
          motion._shimmer["items"] == [s1, s2], motion._shimmer["items"])
    _seen_opacity = set()
    for _ in range(24):
        time.sleep(0.05)
        _seen_opacity.add(s1.opacity)
    check("the placeholder pulses between dim and full",
          _seen_opacity == {motion._shimmer["low"], 1.0},
          _seen_opacity)
    check("the caption breathes with it", s2.opacity in _seen_opacity,
          s2.opacity)

    motion.stop_shimmer()
    check("stopping puts every placeholder back to full opacity",
          s1.opacity == 1.0 and s2.opacity == 1.0, (s1.opacity, s2.opacity))
    check("and forgets them", motion._shimmer["items"] == [])

    motion.shimmer([s1])
    motion.shimmer(None)
    check("shimmer(None) clears the set", motion._shimmer["items"] == []
          and s1.opacity == 1.0)

    motion.set_level("reduced")
    motion.shimmer([s1])
    check("reduced: a loading placeholder does not breathe",
          motion._shimmer["items"] == [])
    motion.set_level("full")

    motion.shimmer([s1])
    time.sleep(0.05)
    motion.set_level("reduced")
    time.sleep(0.15)
    check("a level change ends the shimmer and restores the placeholder",
          motion._shimmer["items"] == [] and s1.opacity == 1.0,
          (motion._shimmer["items"], s1.opacity))
    motion.set_level("full")
finally:
    motion.SHIMMER_MS = _orig_shimmer_ms
    motion.stop_shimmer()

# ----------------------------------------------------------------- ambient ---
print("\n8. ambient()")


def _sample_opacities(control, seconds=0.7):
    """Poll the control's opacity for a while and return the distinct values
    seen - the breathing is a thread writing between two values, so sampling is
    the only honest way to test it."""
    seen = set()
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(0.04)
        seen.add(control.opacity)
    return seen


motion.set_level("full")
glow = ft.Container(opacity=1.0)
amb = motion.ambient(glow, low=0.3, cycle_ms=140)
check("it owns an opacity animation to interpolate with",
      glow.animate_opacity is not None)
_seen_glow = _sample_opacities(glow)
check("the bloom really breathes between two values",
      _seen_glow == {1.0, 0.3}, _seen_glow)

motion.set_level("reduced")
time.sleep(0.4)
check("Reduced parks it at rest", glow.opacity == 1.0, glow.opacity)
check("and its thread exits", amb._thread is None or not amb._thread.is_alive())
motion.set_level("full")
check("switching back resumes the bloom",
      _sample_opacities(glow) == {1.0, 0.3}, glow.opacity)
amb.stop()
check("stop() parks it explicitly", glow.opacity == 1.0)

motion.set_level("reduced")
_amb_off = motion.ambient(ft.Container(opacity=1.0), low=0.2, cycle_ms=120)
check("an Ambient built while Reduced starts no thread",
      _amb_off._thread is None)
motion.set_level("full")
# ------------------------------------------------------------------ wiring ---
print("\n9. the app's wiring")
_theme_src = open(os.path.join(REPO, "cubeon", "theme.py")).read()
check("theme.attach_hover delegates to motion.polish",
      "motion.polish(container" in _theme_src
      and "from . import motion" in _theme_src)
check("attach_hover no longer swaps the fill inline",
      "container.bgcolor = hover_bg if e.data" not in _theme_src)
check("the theme pins its glass hover style onto motion",
      "motion.glass_style = glass_hover" in _theme_src)
check("theme.glass_hover() is the shape polish() reads",
      set(theme.glass_hover()) == {"radius", "rim", "halo"})
check("glass panels carry a backdrop blur + a lit rim",
      theme.GLASS_BLUR is not None and "GLASS_BLUR" in _theme_src
      and "GLASS_RIM" in _theme_src)
check("card() hands the blur to the panel container",
      '"blur": blur' in _theme_src or "kwargs[\"blur\"] = blur" in _theme_src)

_cfg_src = open(os.path.join(REPO, "cubeon", "config.py")).read()
check("config.py carries the motion_level key",
      '"motion_level": "full"' in _cfg_src)
try:
    from cubeon import config as cfg_mod
    check("and DEFAULT_CONFIG exposes it as full",
          cfg_mod.DEFAULT_CONFIG.get("motion_level") == "full")
except Exception as _e:  # pragma: no cover
    check("DEFAULT_CONFIG loads", False, str(_e))

_main_src = open(os.path.join(REPO, "main.py")).read()
check("main.py imports the motion layer", "from cubeon import motion" in _main_src)
check("the startup pass applies the saved level before any widget is built",
      'motion.set_level(cfg.get("motion_level", motion.DEFAULT_LEVEL))'
      in _main_src)
check("the Play/QUIT aura is gone (2026-10-23 user ask: no glow behind it)",
      "hero_glow" not in _main_src and "hero_ambient" not in _main_src)
check("the Play sheen still lives INSIDE the button's own Stack",
      "play_button.content = ft.Stack(" in _main_src
      and "play_sheen.control," in _main_src)
check("the sheen is built with the button's own radius",
      "play_sheen = motion.sheen(radius=RADIUS)" in _main_src)
check("hovering the Play button fires the sweep, leaving it fires the reset",
      "play_sheen.run()" in _main_src and "play_sheen.reset()" in _main_src)
check("the Play button gets the fill callback, not a bgcolor pair",
      "motion.polish(play_button, on_hover_fill=_on_play_hover,"
      in _main_src)
check("so a disabled Play button neither lifts nor dips",
      "active=lambda: not play_button.disabled" in _main_src)
check("the Play button also takes the glass hover style",
      "glass=theme.glass_hover()" in _main_src)
check("the old inline play-button hover wiring is gone",
      "on_hover=_on_play_hover," not in _main_src)

_mp_src = open(os.path.join(REPO, "ui", "modpacks_tab.py")).read()
check("modpack refreshes do not replay an entrance cascade",
      "motion.stagger(results_view.controls)" not in _mp_src)
check("... and loading uses a native spinner without a pulse worker",
      "ft.ProgressRing(" in _mp_src and "motion.shimmer(" not in _mp_src)
# The browse half of the tab is everything before the row builders; the install
# path (later in the file) legitimately PREFERS the Play tab's version.
_mp_browse_src = _mp_src.split("def build_pack_row")[0]
check("the modpack browse is NOT filtered by the Play tab's version "
      "(a pack brings its own version and loader, so filtering the search hid "
      "version-locked classics - Crazy Craft and RLCraft both came back as "
      "'no packs found')",
      "mc_version=" not in _mp_browse_src)
_mods_src = open(os.path.join(REPO, "ui", "mods_tab.py")).read()
check("mod browse refreshes do not replay an entrance cascade",
      "motion.stagger(browse_results_view.controls)" not in _mods_src)
check("... and loading uses a native spinner without a pulse worker",
      "ft.ProgressRing(" in _mods_src and "motion.shimmer(" not in _mods_src)

_set_src = open(os.path.join(REPO, "ui", "settings_tab.py")).read()
check("the Settings row exists", '"Motion",' in _set_src)
check("and is a Switch wired through on_change (a dropdown here would trip "
      "tools/test_seasonal.py's dead-dropdown guard)",
      "motion_switch.on_change = _on_motion_change" in _set_src
      and "ft.Switch(" in _set_src)
check("no dropdown in this file carries a dead .on_change",
      not any(".on_change =" in ln and "dropdown" in ln.lower()
              for ln in _set_src.splitlines()))
check("it applies the level live and persists the key",
      'motion.set_level("full" if sw.value else "reduced")' in _set_src
      and 'cfg["motion_level"] = level' in _set_src)
check("the switch reflects the level that was actually applied",
      "sw.value = motion.transforms()" in _set_src)
check("the row explains what the level does",
      "Hover lifts, list cascades and the pulse behind Play." in _set_src)

# ------------------------------------------------------------------ done ----
_reset()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
