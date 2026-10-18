"""
Motion - the launcher's animation layer ("premium polish", 2026-10-18).

WHAT THIS IS

One place that decides how the launcher moves, so every surface moves the
same way and a single Settings switch can calm the whole app down. It is
deliberately small: four primitives and a level.

    polish(control, ...)   hover tint + a small lift + a press dip + the liquid
                           glass hover (corners open, rim lights up, green halo),
                           applied to any hand-built Container (theme.attach_hover
                           delegates here, so the ~35 existing call sites get it
                           without changing a line)
    sheen(...)             the specular highlight that sweeps across a glass
                           surface on hover
    stagger(controls)      a freshly-built list reveals as a short cascade
                           (fade + a few pixels of rise) instead of all at once
    shimmer(controls)      a loading placeholder breathes while it waits
    ambient(control)       a slow bloom with a mind of its own (the hero panel)

THE RULES THIS MODULE INHERITS (read these before "improving" anything here)

1. ONE FLUSH PER GESTURE. A Flet property written in the same frame animates
   FROM the value the client already holds, so a "dip then settle" needs two
   flushes and the second one has to come from a timer - which the owner read
   as "stucky" (2026-10-17). Everything here therefore animates a property
   that was set AT BUILD TIME (a hover lift starts from the resting scale, a
   cascade starts from opacity 0) and each gesture writes ONE property once.
   The press dip is the single exception, and it is a real gesture with a real
   settle (press -> release), not a delayed content mutation.

2. AN ANIMATION NEEDS A CONTROL THE CLIENT ALREADY KNOWS ABOUT. Never rebuild
   the thing you are animating (see ui/settings_tab.py's rail).

3. NEVER RAISE, NEVER BLOCK THE UI. Every handler here runs on a Flet event
   and a timer/cascade runs on a daemon thread; both go through
   thread_safe_ui.refresh() so a repaint from a worker thread actually lands
   (Flet 0.86 loses raw control.update() calls from foreign threads) and a
   failure is dropped instead of killing the thread.

4. THE LEVEL IS CHECKED AT EVENT TIME, NOT BUILD TIME. Switching Motion to
   Reduced motion in Settings has to affect the controls that are already
   on screen, so the handlers ask `transforms()` while they run.

LEVELS

    full     everything: fades, lifts, presses, cascades, shimmer, ambience
    reduced  fades only - no lifts, no presses, no cascade, nothing that moves
             on its own (the standard "Reduce Motion" reading: colour and
             opacity may change, geometry may not)

The level is the config key `motion_level` (cubeon/config.py) and Settings >
Display's Motion switch writes it through cubeon/motion.set_level()
(ui/settings_tab.py). The default is `full`.

Why there is no third "off": see `transforms()` - a control's fill transition
is decided when the control is built, so an off level could only be honoured
on newly-built controls, i.e. it would need a restart and would leave the tabs
that are already open animating. Two levels means the switch does exactly what
it says the moment it is flipped.
"""
import dataclasses
import threading
import time

import flet as ft

from .thread_safe_ui import refresh as _refresh

# --- vocabulary -------------------------------------------------------------
# Durations land on a 60/120/180/300 rung so nothing is a one-off guess, and
# every curve is an ease-out: motion that starts fast and settles reads as a
# response to the user, motion that eases IN reads as lag.
EASE = ft.AnimationCurve.EASE_OUT_CUBIC     # the app's standard settle
EASE_SOFT = ft.AnimationCurve.EASE_IN_OUT   # self-moving/looping things

FAST_MS = 150     # hover, press - must feel immediate but not be over before
                  # the eye catches it (120ms simply read as "nothing happened")
BASE_MS = 180     # a control changing state
SLOW_MS = 300     # panels

FAST = ft.Animation(FAST_MS, EASE)
BASE = ft.Animation(BASE_MS, EASE)
SLOW = ft.Animation(SLOW_MS, EASE)

# How far a hovered control lifts and how far a pressed one dips. Small on
# purpose: the lift should read as "the panel noticed you", not as a bounce.
LIFT = 1.028
PRESS = 0.975

# The specular sheen (see Sheen below): how long one sweep takes, how bright the
# highlight band gets, and how far past the surface's own edges it travels -
# more than one width each way, so the band enters and leaves cleanly.
SHEEN_MS = 560
SHEEN_PEAK = 0.13
SHEEN_TRAVEL = 1.35

# How far a hovered glass panel's corners open up, when the caller does not
# override it through the glass style (theme.glass_hover()).
GLASS_RADIUS_STEP = 3

# The cascade: per-item gap and how long one item takes to arrive. `STAGGER_CAP_MS`
# bounds the whole cascade, so a 40-row list compresses its gap instead of
# making the user wait a second and a half for the last row.
STAGGER_STEP_MS = 26
STAGGER_MS = 220
STAGGER_CAP_MS = 300
STAGGER_RISE = 0.045    # fraction of the control's own height

RELEASE_MS = 150        # press dip -> back to rest
SHIMMER_MS = 820
AMBIENT_MS = 3400       # one leg of the hero bloom's breath

LEVELS = ("full", "reduced")
DEFAULT_LEVEL = "full"
# Spellings a person might type into config.json by hand. "off" is the one that
# actually gets typed, and it means "less motion" rather than "ignore me", so it
# lands on reduced (see coerce).
_ALIASES = {"off": "reduced", "none": "reduced", "false": "reduced",
            "no": "reduced", "0": "reduced",
            "on": "full", "true": "full", "yes": "full", "1": "full"}

# Does this Flet have Container.on_tap_down? 0.86-era builds may not, and an
# unexpected kwarg raises at build time - i.e. everywhere at once. Detect once
# and simply run without press feedback where it isn't available.
_HAS_TAP_DOWN = any(f.name == "on_tap_down"
                    for f in dataclasses.fields(ft.Container))

_state = {"level": DEFAULT_LEVEL}
_listeners = []


# --- level ------------------------------------------------------------------
def level() -> str:
    """The current motion level: "full" or "reduced"."""
    return _state["level"]


def coerce(value) -> str:
    """Normalise a stored/typed level.

    Unrecognised values fall back to the default, but the common spellings of
    "calm down" (a hand-edited config saying "off", "false", "0") land on
    "reduced" rather than being silently promoted back to full - someone who
    typed that wants less motion, not to be ignored. Note `value is None`, not
    `value or ""`: a JSON `false` or `0` is exactly the spelling this is for, and
    truthiness would throw both away as "empty".
    """
    lv = ("" if value is None else str(value)).strip().lower()
    if lv in LEVELS:
        return lv
    return _ALIASES.get(lv, DEFAULT_LEVEL)


def set_level(value) -> str:
    """Set the level and tell every registered animator. Returns the level
    actually applied (i.e. the coerced one). Never raises - a listener blowing
    up must not take the Settings click with it."""
    lv = coerce(value)
    if lv == _state["level"]:
        return lv
    _state["level"] = lv
    for cb in list(_listeners):
        try:
            cb(lv)
        except Exception:
            pass
    return lv


def on_change(callback):
    """Register a level listener (called with the new level). Returns it, so
    `register = motion.on_change(fn)` reads at the call site."""
    _listeners.append(callback)
    return callback


def transforms() -> bool:
    """Is the app allowed to move its controls - to change their SIZE or
    POSITION, to cascade a list in, to run the hero bloom's pulse?

    True only on "full". "reduced" keeps colour/opacity transitions (a hover
    tint fading in) but refuses everything that moves geometry or that moves on
    its own - the standard reading of a system's Reduce Motion setting.

    There is deliberately no third "nothing moves at all" level: a control's
    fill transition is a property of that control, so switching it off would
    have to be decided when the control is BUILT, i.e. the switch would need a
    restart and would leave already-open tabs half-converted. Dropping it keeps
    every rule in this module checkable while the user is looking at the app.
    """
    return _state["level"] == "full"


# --- hover + press ----------------------------------------------------------
# The glass hover state (radius step, rim colour, halo shadow) is palette, so it
# lives in cubeon/theme.py, which imports this module and pins its glass_hover()
# here at import time (see the note at the bottom of theme.py). Until it does,
# this stays None and the hover degrades to the fill swap plus the lift.
glass_style = None


def _glass_lookup():
    fn = glass_style
    if fn is None:
        return {}
    try:
        return dict(fn() or {})
    except Exception:
        return {}


def _read_radius(value):
    """A control's corner radius as one of the two shapes Flet accepts (a
    number or an ft.BorderRadius), or None when it has none."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if getattr(value, "top_left", None) is not None:
        return value
    return None


def _grow_radius(value, step):
    """`value` with every corner opened by `step`, or None when there is no
    radius to grow (a control that was built square stays square)."""
    if value is None or not step:
        return None
    try:
        if isinstance(value, (int, float)):
            return value + step
        return ft.BorderRadius(
            top_left=value.top_left + step,
            top_right=value.top_right + step,
            bottom_left=value.bottom_left + step,
            bottom_right=value.bottom_right + step,
        )
    except Exception:
        return None


def _rim_border(border, colour):
    """A copy of the control's own border with every side recoloured to
    `colour`. Uniform-width borders only: a non-uniform one combined with a
    rounded rect (and a shadow) is a decoration Flutter refuses to paint."""
    if border is None or colour is None:
        return None
    try:
        sides = [border.top, border.right, border.bottom, border.left]
        if any(s is None for s in sides):
            return None
        return ft.border.Border(
            top=ft.BorderSide(sides[0].width, colour),
            right=ft.BorderSide(sides[1].width, colour),
            bottom=ft.BorderSide(sides[2].width, colour),
            left=ft.BorderSide(sides[3].width, colour),
        )
    except Exception:
        return None


def polish(container, base_bg=None, hover_bg=None, *,
           lift=LIFT, press=PRESS, scale=1.0, anchor=None,
           on_hover_fill=None, active=None, glass=None):
    """Wire hover and press feedback onto a hand-built Container.

    Flet's real buttons get hover/press for free; the app builds nearly all of
    its clickable things by hand, which is why they can feel dead. This adds,
    in one call:

      * the fill swap (base_bg <-> hover_bg), faded instead of snapped,
      * a small lift while hovered,
      * a small dip while pressed,
      * the liquid-glass hover (2026-10-18): the corners open up a little, the
        rim catches the light and a soft green halo rises underneath - all on
        properties the control already had, so Flet interpolates them with the
        same one-flush rule as the fill.

    The lift and the dip need `full` (see transforms) and are checked WHEN THE
    EVENT FIRES, so the Settings switch applies to every row that is already on
    screen. Returns the container, so `attach_hover(...)`-style call sites can
    stay one expression.

    Two escape hatches for controls that don't fit the plain pattern:

      on_hover_fill(hot)  the caller owns the fill (e.g. the Play button, whose
                          colour depends on its current meaning); pass
                          base_bg/hover_bg as None and this is called instead of
                          touching bgcolor.
      active()            False while the control is disabled, so a disabled
                          button neither lifts nor dips.

    `glass` is the hover style dict (theme.glass_hover()); omit it and the
    palette's own is used.
    """
    anchor = anchor or ft.Alignment.CENTER
    st = {"hover": False, "down": False, "timer": None}
    # Nothing here is decided by the motion level at BUILD time, which is the
    # point: the fill transition belongs to the control and the level is asked
    # when an event fires, so the Settings switch reaches rows that already
    # exist. The resting scale is written unconditionally too (an identity
    # transform costs nothing), so a row built while motion was reduced can
    # still lift the moment it is switched back to full - no rebuild, no
    # swapping the control's type under the client.
    #
    # Only take ownership of `scale` if nobody else has: some controls (the top
    # nav's icon and underline) use it for their own affordance.
    owns_scale = container.scale is None
    if owns_scale:
        try:
            container.scale = ft.Scale(scale, alignment=anchor)
        except Exception:
            owns_scale = False
    if container.animate is None:
        container.animate = FAST              # fills fade, never snap
    if owns_scale and container.animate_scale is None:
        container.animate_scale = FAST

    # Read the control's resting glass state once, here, so every gesture below
    # is a swap between two prepared values - the client already holds the
    # resting one, so it interpolates instead of snapping (rule 1).
    style = _glass_lookup() if glass is None else dict(glass or {})
    base_radius = _read_radius(getattr(container, "border_radius", None))
    hot_radius = _grow_radius(base_radius,
                              style.get("radius", GLASS_RADIUS_STEP))
    base_border = getattr(container, "border", None)
    hot_border = _rim_border(base_border, style.get("rim"))
    base_shadow = getattr(container, "shadow", None)
    halo = style.get("halo")
    hot_shadow = halo if halo is not None else base_shadow

    def _allowed():
        try:
            return active is None or bool(active())
        except Exception:
            return False

    def _rest():
        """Stop the dip. Also the safety net for a press whose release event
        never arrives (Flet's Container has no on_tap_up to hook)."""
        st["down"] = False
        _paint()

    def _glass(hot):
        """The liquid-glass half of a hover. Colour and light (the rim, the
        halo) fade on any motion level; the corner morph is geometry, so it
        belongs to `full` like the lift does."""
        try:
            if transforms() and hot_radius is not None:
                container.border_radius = hot_radius if hot else base_radius
            if hot_border is not None:
                container.border = hot_border if hot else base_border
            if hot_shadow is not base_shadow:
                container.shadow = hot_shadow if hot else base_shadow
        except Exception:
            pass

    def _paint():
        if owns_scale and transforms() and _allowed():
            target = scale
            if st["down"]:
                target = scale * press
            elif st["hover"]:
                target = scale * lift
            try:
                container.scale = ft.Scale(target, alignment=anchor)
            except Exception:
                pass
        _refresh(container)

    def _on_hover(e):
        hovering = getattr(e, "data", None) == "true"
        # `hot` is the premium state (lift, dip, glass); `hovering` is the raw
        # pointer. They differ for a disabled control, which still gets the
        # quiet fill feedback - colour says "the row is here", geometry says
        # "you can use this", and only the second one has to be earned.
        hot = hovering and _allowed()
        st["hover"] = hot
        if not hot and st["down"]:
            # The pointer left mid-press: release now rather than waiting for
            # the timer, so the control can't be left squashed.
            st["down"] = False
        try:
            if on_hover_fill is not None:
                on_hover_fill(hot)
            elif hover_bg is not None or base_bg is not None:
                container.bgcolor = hover_bg if hovering else base_bg
        except Exception:
            pass
        _glass(hot)
        _paint()

    container.on_hover = _on_hover

    if _HAS_TAP_DOWN:
        def _on_tap_down(e):
            if not transforms() or not _allowed():
                return
            st["down"] = True
            _paint()
            timer = st.get("timer")
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass
            t = threading.Timer(RELEASE_MS / 1000.0, _rest)
            t.daemon = True
            st["timer"] = t
            t.start()

        container.on_tap_down = _on_tap_down

    return container


# --- sheen (the specular sweep) ---------------------------------------------
class Sheen:
    """The highlight that sweeps across a glass surface when the pointer
    arrives: the animated half of the frosted look, where theme.glass_edge() is
    the static half.

    Build one, put `s.control` UNDER the content in an ft.Stack that matches the
    surface's own shape, and call run()/reset() from the surface's hover handler.
    Flet's Stack children are painted in order, so "under" means first.

    Why it is built this way: the highlight is a soft white band in the middle of
    a transparent box the exact size of the surface, slid sideways by `offset` -
    paint only, so a sweep can never reflow or resize anything around it (rule 2
    at the top of this module). The box before it is what clips, which is why the
    band can travel more than its own width without ever being seen off-panel.

    reset() parks the band off the left edge at zero opacity, so the next run()
    is again ONE write and the return trip is invisible - the same
    two-prepared-states trick the hover polish uses. Both are no-ops on reduced
    motion (a self-moving decoration the reader did not ask for).
    """

    def __init__(self, *, ms=SHEEN_MS, peak=SHEEN_PEAK, travel=SHEEN_TRAVEL,
                 radius=None):
        self._travel = travel
        self._band = ft.Container(
            left=0, top=0, right=0, bottom=0,
            opacity=0.0,
            offset=ft.Offset(-travel, 0),
            animate_offset=ft.Animation(ms, EASE),
            animate_opacity=ft.Animation(FAST_MS, EASE),
            gradient=ft.LinearGradient(
                begin=ft.Alignment(-1, 0), end=ft.Alignment(1, 0),
                colors=[
                    ft.Colors.with_opacity(0.0, "#FFFFFF"),
                    ft.Colors.with_opacity(peak, "#FFFFFF"),
                    ft.Colors.with_opacity(0.0, "#FFFFFF"),
                ],
                stops=[0.34, 0.5, 0.66],
            ),
        )
        self.control = ft.Container(
            left=0, top=0, right=0, bottom=0,
            border_radius=radius,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Stack([self._band], expand=True,
                             clip_behavior=ft.ClipBehavior.NONE),
        )

    def run(self):
        """Sweep once (hover in)."""
        if not transforms():
            return
        try:
            self._band.opacity = 1.0
            self._band.offset = ft.Offset(self._travel, 0)
        except Exception:
            return
        _refresh(self._band)

    def reset(self):
        """Park the band off the left edge again (hover out). It fades out on
        the way back, so the return trip is never visible."""
        try:
            self._band.opacity = 0.0
            self._band.offset = ft.Offset(-self._travel, 0)
        except Exception:
            return
        _refresh(self._band)


def sheen(**kwargs) -> Sheen:
    """Build a Sheen (see the class). Put `control` under the content of a
    Stack that matches the surface's shape, then call run()/reset() on hover."""
    return Sheen(**kwargs)


# --- cascade (list/grid entrance) -------------------------------------------
_cascade_lock = threading.Lock()
_cascade_gen = {"n": 0}


def stagger(controls, *, step_ms=STAGGER_STEP_MS, duration_ms=STAGGER_MS,
            rise=STAGGER_RISE, cap_ms=STAGGER_CAP_MS):
    """Reveal a freshly-built list as a cascade: each item fades in and rises a
    few pixels, one after another, in a few hundred milliseconds.

    Call it AFTER the items exist and BEFORE the parent repaint, with the list's
    controls - it sets them to opacity 0 and schedules the reveals on a daemon
    thread. Not a cross-fade and not a per-gesture dip: the controls are new to
    the client, so this is their entrance, and the whole cascade is one logical
    gesture (see rule 1 at the top of this module).

    A newer call supersedes an older one (the generation counter): switching
    pages of a search result must not leave the previous page's cascade running
    against recycled controls. On reduced motion this is a no-op and the list is
    simply there, in one flush.
    """
    items = [c for c in (controls or []) if c is not None]
    if not transforms() or not items:
        return

    # Compress the gap rather than stretch the cascade on long lists, and keep
    # a floor so a 60-item grid doesn't flash every row in the same frame.
    step_ms = int(max(12, min(step_ms, cap_ms // len(items))))

    for c in items:
        if c.animate_opacity is None:
            c.animate_opacity = ft.Animation(duration_ms, EASE)
        c.opacity = 0
        if rise:
            if c.animate_offset is None:
                c.animate_offset = ft.Animation(duration_ms, EASE)
            c.offset = ft.Offset(0, rise)

    with _cascade_lock:
        _cascade_gen["n"] += 1
        generation = _cascade_gen["n"]

    def _run():
        for i, c in enumerate(items):
            time.sleep(step_ms / 1000.0)
            with _cascade_lock:
                if _cascade_gen["n"] != generation:
                    return      # a newer list replaced this one
            if not transforms():
                # Motion was switched down mid-cascade. The controls already
                # exist, so they must simply BE there: no transition, no wait -
                # otherwise the rest of the list would stay invisible.
                for rest in items[i:]:
                    try:
                        rest.animate_opacity = None
                        rest.animate_offset = None
                        rest.opacity = 1
                        if rise:
                            rest.offset = ft.Offset(0, 0)
                    except Exception:
                        continue
                    _refresh(rest)
                return
            try:
                c.opacity = 1
                if rise:
                    c.offset = ft.Offset(0, 0)
            except Exception:
                return
            _refresh(c)

    threading.Thread(target=_run, name="cubeon-motion-cascade",
                     daemon=True).start()


# --- shimmer (loading placeholders) ----------------------------------------
_shimmer_lock = threading.Lock()
_shimmer = {"items": [], "low": 0.42, "wake": threading.Event(),
            "thread": None, "stop": True}


def shimmer(controls, *, low=0.42):
    """Make a loading placeholder breathe while it waits.

    One shared daemon thread drives every registered control (there is only
    ever one loading state visible at a time), so a spinner row plus its
    caption pulse together at ~1 repaint per second instead of each running its
    own loop. Calling this again replaces the set; `shimmer(None)` - or a new
    loading state - clears it, and anything cleared is put back to full opacity
    so a placeholder can never be left stuck half-faded. No-op unless motion is
    `full`.
    """
    items = [c for c in (controls or []) if c is not None]
    if not transforms() or not items:
        stop_shimmer()
        return
    with _shimmer_lock:
        _shimmer["items"] = items
        _shimmer["low"] = low
        _shimmer["stop"] = False
        for c in items:
            if c.animate_opacity is None:
                c.animate_opacity = ft.Animation(SHIMMER_MS, EASE_SOFT)
        if _shimmer["thread"] is None or not _shimmer["thread"].is_alive():
            t = threading.Thread(target=_shimmer_loop,
                                 name="cubeon-motion-shimmer", daemon=True)
            _shimmer["thread"] = t
            t.start()
    _shimmer["wake"].set()


def stop_shimmer():
    """End the current loading shimmer (the state it belonged to is gone)."""
    with _shimmer_lock:
        items = list(_shimmer["items"])
        _shimmer["items"] = []
        _shimmer["stop"] = True
        _shimmer["wake"].set()
    for c in items:
        try:
            c.opacity = 1.0
        except Exception:
            continue
        _refresh(c)


def _shimmer_loop():
    dim = False
    while True:
        _shimmer["wake"].wait(SHIMMER_MS / 1000.0)
        _shimmer["wake"].clear()
        with _shimmer_lock:
            if _shimmer["stop"] or not _shimmer["items"]:
                return
            items, low = list(_shimmer["items"]), _shimmer["low"]
        dim = not dim
        for c in items:
            try:
                c.opacity = low if dim else 1.0
            except Exception:
                continue
            _refresh(c)


# --- ambience (self-moving decoration) --------------------------------------
class Ambient:
    """A slow breathing effect on one control, e.g. the bloom behind the hero
    panel. Self-moving, so it only runs on `full`; on reduced it parks at
    its resting opacity and the thread exits.

    Exactly one writer, two writes per cycle, each animated by the control's
    own animate_opacity - roughly 0.6 repaints a second, which is why this is
    affordable where a per-frame animation would not be.
    """

    def __init__(self, control, *, base=1.0, low=0.45, cycle_ms=AMBIENT_MS):
        self.control = control
        self.base = base
        self.low = low
        self.cycle_s = max(0.2, cycle_ms / 1000.0)
        self._stop = threading.Event()
        self._thread = None
        if control.animate_opacity is None:
            control.animate_opacity = ft.Animation(cycle_ms, EASE_SOFT)
        self.sync()

    # -- lifecycle
    def sync(self, _level=None):
        """Start or park according to the live level."""
        if transforms():
            self.start()
        else:
            self.stop()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        t = threading.Thread(target=self._run, name="cubeon-motion-ambient",
                             daemon=True)
        self._thread = t
        t.start()

    def stop(self, *, reset=True):
        self._stop.set()
        self._thread = None
        if reset:
            self._write(self.base)

    def _write(self, value):
        try:
            self.control.opacity = value
        except Exception:
            return
        _refresh(self.control)

    def _run(self):
        while not self._stop.is_set():
            self._write(self.low)
            if self._stop.wait(self.cycle_s):
                break
            self._write(self.base)
            if self._stop.wait(self.cycle_s):
                break


def ambient(control, **kwargs) -> Ambient:
    """Build an Ambient on `control` and keep it in step with the motion level
    for the rest of the session. Returns it so the caller can stop it early."""
    amb = Ambient(control, **kwargs)
    on_change(amb.sync)
    return amb


# --- when the level changes -------------------------------------------------
def _level_changed(_level):
    """A level change has to reach the animators that own no lifetime of their
    own. Ambient registers itself (see `ambient`); the shimmer belongs to
    whatever loading state happens to be on screen, so it is ended here.
    Cascades check `transforms()` themselves while they run."""
    stop_shimmer()


on_change(_level_changed)
