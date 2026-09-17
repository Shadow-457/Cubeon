"""
Seasonal furniture: the top-bar badge, the little companion, and the ambient
weather strip.

These are the *runtime* half of the seasonal layer. The palette half lives at
import time (cubeon/seasonal.py + templates/color_<season>.py) and cannot change
while the window is open; everything in this file can, because it is drawn from
tokens that were already chosen.

ANIMATION BUDGET - the rules this file obeys
--------------------------------------------
1. The pet's own motion lives in its animated GIF. Flutter loops it with ZERO
   Python involvement, so a pet costs nothing per frame.
2. Anything that genuinely needs a clock shares ONE daemon ticker
   (SeasonalAnimator). It is not one thread per effect.
3. Every tick paints with a single thread_safe_ui.refresh(<one container>) -
   never page.update(). One strip repaint carries every particle in it, which is
   the difference between ~1 diff per frame and ~10.
4. The ticker never raises: a lost repaint is not worth a traceback, and the
   session-end hook (main.py) stops it so a closed window stops costing CPU.
5. The pet WANDERS a short perch lane next to the wordmark: walk at a fixed
   amble, pause a jittered while (sometimes with an idle hop), turn around at
   the lane's ends and walk back. Predictable by character, never by clock -
   a companion that bobs in lockstep with a clock reads as a screensaver.

Ambient particles are opt-in (cfg["season_ambience"]) and default to OFF until
measured with CUBEON_PERF=1; see the module map.
"""
from __future__ import annotations

import random
import threading

import flet as ft

from cubeon import seasonal
from cubeon import thread_safe_ui
from cubeon.theme import (
    ACCENT, ACCENT_TINT, ROW_HOVER, RADIUS, TEXT_DIM,
    attach_hover,
)

# The companion sprite per season. Summer reuses assets/parrot.gif - the mascot
# the account panel already perches on the avatar - so only three sprites have
# to be generated (tools/make_season_pets.py).
PET_FILES = {
    seasonal.AUTUMN: "pets/autumn_fox.gif",
    seasonal.WINTER: "pets/winter_golem.gif",
    seasonal.SPRING: "pets/spring_bee.gif",
    seasonal.SUMMER: "parrot.gif",
}
PET_NAMES = {
    seasonal.AUTUMN: "Autumn fox",
    seasonal.WINTER: "Snow golem",
    seasonal.SPRING: "Spring bee",
    seasonal.SUMMER: "Parrot",
}
PET_LINES = {
    seasonal.AUTUMN: "The fox moved in when the leaves did.",
    seasonal.WINTER: "The golem is keeping the bar cold for you.",
    seasonal.SPRING: "The bee came back with the blossom.",
    seasonal.SUMMER: "The parrot is on holiday with you.",
}
# The icon the badge wears. Chosen to match the palette's one-voice rule: the
# badge is tinted with ACCENT, so the glyph is the season, not decoration.
SEASON_ICONS = {
    seasonal.AUTUMN: ft.Icons.PARK_ROUNDED,            # a tree losing its leaves
    seasonal.WINTER: ft.Icons.AC_UNIT_ROUNDED,         # a snowflake
    seasonal.SPRING: ft.Icons.LOCAL_FLORIST_ROUNDED,   # a blossom
    seasonal.SUMMER: ft.Icons.WB_SUNNY_ROUNDED,        # the sun
}
TROPIC_ICONS = {
    seasonal.SPRING: ft.Icons.WATER_DROP_ROUNDED,      # wet season
    seasonal.SUMMER: ft.Icons.WB_SUNNY_ROUNDED,        # dry season
}
# One short line per season, said when the pet is clicked. The pet is a mood,
# not a feature - so it answers with a mood.
QUIPS = {
    seasonal.AUTUMN: "Leaves are down. The whole launcher went orange.",
    seasonal.WINTER: "Cold one today - ice blue, on the house.",
    seasonal.SPRING: "Everything's blooming, including the buttons.",
    seasonal.SUMMER: "Long days. Gold Play button, no extra charge.",
}
TROPIC_QUIPS = {
    seasonal.SPRING: "Wet season. Everything outside is loud and green.",
    seasonal.SUMMER: "Dry season. Sun's out, palette's warm.",
}

# Ticker cadence. 0.12s is smooth enough for slow-drifting leaves and slow
# enough that a laptop fan never notices; the GIF pets add motion of their own
# in between.
TICK = 0.12
# The perch lane: the pet strolls back and forth inside a short strip mounted
# next to the wordmark (PERCH_W px wide, pet sprite PERCH_CELL px). Offsets are
# plain pixels inside the lane's Stack - pixel-art motion, like the ambience
# particles, NOT animate_position (that would smooth away the blocky look).
PERCH_W = 96
PERCH_CELL = 30
# Walk cadence in px per tick - one tick is 0.12s, so ~15 px/s. Slow on
# purpose: a companion that sprints reads as a bug, one that ambles reads as
# a pet. It pauses for a jittered while between walks, so the rhythm is
# "walk ... think ... walk the other way", never a metronome.
WALK_SPEED = 1.0
# Idle hops: sometimes it just bounces in place while "thinking". Short air
# leg, like the old hop beat.
HOP_AIR_TICKS = 2
HOP_LIFT_PX = 6
# Direction bookkeeping: dir is -1 (left) / +1 (right); the sprite mirrors
# with scale_x so it always walks facing the way it moves.
DIR_LEFT, DIR_RIGHT = -1, 1


def pet_src(info: seasonal.SeasonInfo) -> str:
    return PET_FILES.get(info.season, PET_FILES[seasonal.SUMMER])


def pet_name(info: seasonal.SeasonInfo) -> str:
    return PET_NAMES.get(info.season, "Companion")


def icon_for(info: seasonal.SeasonInfo):
    if info.climate == "tropical":
        return TROPIC_ICONS.get(info.season, ft.Icons.WB_SUNNY_ROUNDED)
    return SEASON_ICONS.get(info.season, ft.Icons.AUTO_AWESOME_ROUNDED)


def quip_for(info: seasonal.SeasonInfo) -> str:
    if info.climate == "tropical":
        return TROPIC_QUIPS.get(info.season, QUIPS.get(info.season, "Nice day."))
    return QUIPS.get(info.season, "Nice day.")


def build_badge(info: seasonal.SeasonInfo, on_click=None) -> ft.Container:
    """The small season chip for the top bar: glyph + label, quietly tinted.

    It is also the *discovery* path for the whole feature: clicking it opens the
    Settings > Seasonal pane, which is where a user goes when the detection
    guessed the wrong hemisphere.
    """
    tip = info.label
    if info.zone:
        tip += f" - {info.place} ({info.zone})"
    tip += "\nClick to change"
    return attach_hover(
        ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon_for(info), size=15, color=ACCENT),
                    ft.Text(info.label, size=12, color=TEXT_DIM,
                            weight=ft.FontWeight.W_600),
                ],
                spacing=7, tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ACCENT_TINT,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=10, vertical=6),
            ink=False,
            tooltip=tip,
            on_click=on_click,
        ),
        ACCENT_TINT, ROW_HOVER,
    )


def build_perch(info: seasonal.SeasonInfo, on_click=None):
    """The companion's stroll lane - a fixed strip mounted in the top bar.

    Returns (lane, pet_dict). `lane` is the Stack the bar mounts (clipped so a
    mid-walk sprite never bleeds over the wordmark); `pet_dict` is what
    SeasonalAnimator.add_pet() consumes to make the pet wander. The pet is a
    Container sitting at plain left/top inside the lane, so the animator moves
    it in pixels - the same pixel-art contract as the ambience particles.
    """
    inner = ft.Container(
        content=ft.Image(src=pet_src(info), width=PERCH_CELL, height=PERCH_CELL,
                         fit=ft.BoxFit.CONTAIN),
        tooltip=f"{pet_name(info)} - {PET_LINES.get(info.season, '')}",
        on_click=on_click,
    )
    pet = {
        "ctrl": inner,
        "season": info.season,
        "x": PERCH_W // 2.0,
        "dir": DIR_RIGHT,
        "state": "rest",        # rest | walk | air
        "wait": 0,              # ticks left in the current rest
        "air": 0,
        "rest_left": 20,
        "rest_right": 46,
    }
    lane = ft.Stack(
        [inner], width=PERCH_W, height=PERCH_CELL,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    return lane, pet


def update_badge(badge: ft.Container, info: seasonal.SeasonInfo) -> None:
    """Re-skins the top-bar chip in place for the new season (icon + label +
    tooltip). Live, like the pet: only the palette waits for a relaunch."""
    row = badge.content
    icon, label = row.controls[0], row.controls[1]
    icon.name = icon_for(info)
    label.value = info.label
    tip = info.label
    if info.zone:
        tip += f" - {info.place} ({info.zone})"
    tip += "\nClick to change"
    badge.tooltip = tip


def build_pet(info: seasonal.SeasonInfo, on_click=None, size: int = 30) -> ft.Container:
    """Legacy in-place pet: just the sprite, no lane.

    Kept for callers/tests that want a plain pet control; the bar now mounts
    build_perch() instead so the companion can wander.
    """
    return ft.Container(
        content=ft.Image(src=pet_src(info), width=size, height=size,
                         fit=ft.BoxFit.CONTAIN),
        padding=ft.padding.Padding.symmetric(horizontal=2),
        ink=False,
        tooltip=f"{pet_name(info)} - {PET_LINES.get(info.season, '')}",
        on_click=on_click,
        offset=ft.Offset(0, 0),
        animate_offset=ft.Animation(130, ft.AnimationCurve.EASE_OUT),
    )


# How each season's weather behaves: (colours, particle size px, speed px/tick,
# sway px/tick, rising?). Summer's specks RISE - they are fireflies under a warm
# sky, not rain, which is what keeps the summer ambience from reading as gloom.
def update_pet(pet: dict, info: seasonal.SeasonInfo) -> None:
    """Swaps the wanderer's sprite in place for a new season.

    Called live from Settings (the sprite is runtime furniture - only the
    PALETTE needs a relaunch). Mutates the pet dict rather than rebuilding the
    lane, so the animator's registration survives the season change.
    """
    pet["season"] = info.season
    pet["ctrl"].content.src = pet_src(info)
    pet["ctrl"].tooltip = f"{pet_name(info)} - {PET_LINES.get(info.season, '')}"


WEATHER = {
    seasonal.AUTUMN: (("#E0762A", "#E6B23C", "#C4553F", "#A8531A"),
                      7, 1.0, 0.9, False),
    seasonal.WINTER: (("#EAF2F8", "#B9CBD9", "#5FB6E0"),
                      5, 0.7, 0.35, False),
    seasonal.SPRING: (("#E86A9A", "#F784AF", "#7FC48F"),
                      6, 0.8, 1.1, False),
    seasonal.SUMMER: (("#E4B23C", "#F4C95A", "#4FBFAE"),
                      4, 0.45, 0.7, True),
}
PARTICLE_COUNT = 9


def build_ambience(info: seasonal.SeasonInfo, *, width: int = 250,
                   height: int = 150, seed=None):
    """The corner weather strip.

    Returns (strip, particles, bounds). `strip` is the ONE control the animator
    repaints per frame; the particles sit inside its Stack at plain left/top.
    They are deliberately NOT `animate_position`: stepping by a pixel reads as
    pixel-art motion, while animate_position would smooth away the blocky look
    the rest of the app is built on - and it would add a second layer of
    client-side animation for nine controls.
    """
    colors, size, speed, sway, rising = WEATHER.get(
        info.season, WEATHER[seasonal.AUTUMN])
    rng = random.Random(seed)
    particles = []
    for _ in range(PARTICLE_COUNT):
        x = rng.uniform(0, max(0, width - size))
        y = rng.uniform(0, height)
        particles.append({
            "x": x,
            "y": y,
            "phase": rng.uniform(0, 6.28),
            "ctrl": ft.Container(width=size, height=size,
                                 bgcolor=rng.choice(colors),
                                 border_radius=2, left=x, top=y,
                                 opacity=0.85),
        })
    stack = ft.Stack([p["ctrl"] for p in particles], width=width, height=height)
    strip = ft.Container(
        content=stack, width=width, height=height,
        alignment=ft.Alignment.TOP_LEFT,
    )
    return strip, particles, (width, height, size, speed, sway, rising)


def reflow_ambience(particles, bounds, info: seasonal.SeasonInfo):
    """Re-seeds the weather strip in place for a new season.

    Keeps the same particle CONTROLS (so the strip's Stack stays valid) but
    re-skins them: the season's palette/size/behavior and fresh random
    positions. Returns the NEW bounds tuple - the caller stores it in
    _season_rt and the apply() flow re-registers it with the animator.
    """
    colors, size, speed, sway, rising = WEATHER.get(
        info.season, WEATHER[seasonal.AUTUMN])
    w, h = bounds[0], bounds[1]
    rng = random.Random()
    for p in particles:
        p["x"] = rng.uniform(0, max(0, w - size))
        p["y"] = rng.uniform(0, h)
        p["phase"] = rng.uniform(0, 6.28)
        ctrl = p["ctrl"]
        ctrl.bgcolor = rng.choice(colors)
        ctrl.width = size
        ctrl.height = size
    return (w, h, size, speed, sway, rising)


def step_ambience(particles, bounds, tick: int = 0) -> None:
    """Advances every particle one frame. Pure geometry - no Flet layout calls,
    so it is unit-testable without a page."""
    width, height, size, speed, sway, rising = bounds
    for p in particles:
        p["phase"] += 0.06
        p["y"] += (-speed if rising else speed)
        p["x"] += sway * (1 if int(p["phase"] * 1.7) % 2 else -1) * 0.5
        # Wrap rather than bounce: a leaf that bounces off the floor looks like a
        # bug, one that leaves the frame and returns does not.
        leaving = p["y"] < -size if rising else p["y"] > height
        if leaving:
            p["y"] = height if rising else -size
            p["x"] = (p["x"] * 1.7 + 13) % max(1, width - size)
        if p["x"] < -size:
            p["x"] = width
        elif p["x"] > width:
            p["x"] = -size
        ctrl = p["ctrl"]
        ctrl.left = round(p["x"])
        ctrl.top = round(p["y"])
class SeasonalAnimator:
    """One daemon ticker for every seasonal effect in the window.

    Owned by main.py: created when a pet or the ambience strip exists, and
    stopped from the session-end hook (main.py's `_session_end`) so a closed
    window stops consuming a thread. Every frame is a single refresh() per
    registered container - see the module docstring's animation budget.
    """

    def __init__(self, on_error=None):
        self._stop = threading.Event()
        self._thread = None
        self._pets = []
        self._windows = []
        self._lock = threading.Lock()
        self._tick = 0
        self._rng = random.Random()
        self._on_error = on_error

    # --- registration -----------------------------------------------------
    def add_pet(self, pet) -> None:
        """Registers a pet dict from build_perch() for the wander state
        machine (see _wander). Accepts a bare control too - that legacy shape
        gets the old in-place hop."""
        with self._lock:
            if isinstance(pet, dict):
                self._pets.append(pet)
            else:
                self._pets.append({
                    "ctrl": pet, "x": 0.0, "dir": DIR_RIGHT,
                    "state": "rest", "wait": 0, "air": 0,
                    "lane_w": 0, "rest_left": 20, "rest_right": 46,
                    "legacy_hop": True,
                })

    def add_ambience(self, strip, particles, bounds) -> None:
        with self._lock:
            self._windows.append({"ctrl": strip, "particles": particles,
                                  "bounds": bounds})

    @property
    def has_work(self) -> bool:
        return bool(self._pets or self._windows)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # --- lifecycle --------------------------------------------------------
    def start(self) -> "SeasonalAnimator":
        if self.running or not self.has_work:
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="seasonal-anim",
                                       daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Idempotent and silent: called from the session-end hook."""
        self._stop.set()
        self._thread = None

    def clear(self) -> None:
        """Drops every registration.

        Used when a setting changes: the caller rebuilds the (one or two)
        registrations from the new state rather than diffing them, so there is
        no way for the ticker to keep holding a control the user just hid.
        The ticker itself keeps running until stop() - callers follow this with
        start()/stop() as appropriate.
        """
        with self._lock:
            self._pets.clear()
            self._windows.clear()

    # --- one frame --------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.wait(TICK):
            self._tick += 1
            try:
                self._frame()
            except Exception:      # noqa: BLE001 - never kill a thread over a repaint
                if self._on_error is not None:
                    self._on_error()

    def _frame(self) -> None:
        with self._lock:
            pets, windows = list(self._pets), list(self._windows)
        for pet in pets:
            if pet.get("legacy_hop"):
                self._legacy_hop(pet)
            else:
                self._wander(pet)
        for win in windows:
            step_ambience(win["particles"], win["bounds"], self._tick)
            thread_safe_ui.refresh(win["ctrl"])

    def _legacy_hop(self, pet: dict) -> None:
        """The old in-place hop, kept for bare-control registrations."""
        pet["air"] = pet.get("air", 0)
        pet.setdefault("wait", 0)
        if pet["air"] > 0:
            pet["air"] -= 1
            if pet["air"] == 0:
                pet["ctrl"].offset = ft.Offset(0, 0)
                thread_safe_ui.refresh(pet["ctrl"])
            return
        pet["wait"] += 1
        if pet["wait"] >= pet.get("rest_right", 46):
            pet["wait"] = 0
            pet["air"] = HOP_AIR_TICKS
            pet["ctrl"].offset = ft.Offset(0, -0.22)
            thread_safe_ui.refresh(pet["ctrl"])

    def _wander(self, pet: dict) -> None:
        """Advances one pet's wander state machine: rest -> walk -> rest,
        turning around at the lane's ends, with idle hops sprinkled into the
        rests.

        PREDICTABLE BY CHARACTER, NOT BY CLOCK - the design rule the old hop
        already obeyed, kept here: the pet always stays on its lane, always
        walks at the same amble, always comes back. What jitters is only the
        waiting (24-60 ticks of rest) and whether a rest becomes an idle hop
        (~1 in 4). A metronome reads as a screensaver; this reads as a pet
        that decided to move.

        Geometry is plain pixels on `ctrl.left/top` inside the clipped lane
        Stack - one refresh per moved pet, same budget as everything else.
        The sprite mirrors with scale_x so it faces the way it walks; scale_x
        is only written when it CHANGES so the Flet diff stays empty while it
        strolls straight.
        """
        ctrl = pet["ctrl"]
        lane_w = pet.get("lane_w") or PERCH_W
        span = max(1, lane_w - PERCH_CELL)
        pet["rest_left"] = max(pet.get("rest_left", 20), HOP_AIR_TICKS + 1)
        pet["rest_right"] = max(pet.get("rest_right", 46),
                                pet["rest_left"] + 1)

        # Airborne leg of an idle hop (or a bounce off a lane wall): rise, then
        # settle back to the floor of the lane.
        if pet["air"] > 0:
            pet["air"] -= 1
            if pet["air"] == 0:
                ctrl.top = 0
                thread_safe_ui.refresh(ctrl)
            return

        state = pet["state"]
        if state == "rest":
            pet["wait"] -= 1
            if pet["wait"] > 0:
                # Sometimes the rest becomes a little idle hop instead.
                if self._rng.random() < 0.04:
                    pet["air"] = HOP_AIR_TICKS
                    ctrl.top = -HOP_LIFT_PX
                    thread_safe_ui.refresh(ctrl)
                return
            state = "walk"
        elif state == "walk":
            x = pet["x"] + pet["dir"] * WALK_SPEED
            # Lane end: turn around (mirroring the sprite) and bounce off the
            # wall with a tiny hop - a turn that also lifts reads as playful,
            # one that just flips reads as a bouncing DVD logo.
            if x <= 0:
                x = 0
                pet["dir"] = DIR_RIGHT
                pet["air"] = HOP_AIR_TICKS
                ctrl.top = -HOP_LIFT_PX
                pet["state"] = "rest"
                pet["wait"] = self._rng.randint(pet["rest_left"],
                                                pet["rest_right"])
                self._apply_facing(pet)
                thread_safe_ui.refresh(ctrl)
                return
            if x >= span:
                x = span
                pet["dir"] = DIR_LEFT
                pet["air"] = HOP_AIR_TICKS
                ctrl.top = -HOP_LIFT_PX
                pet["state"] = "rest"
                pet["wait"] = self._rng.randint(pet["rest_left"],
                                                pet["rest_right"])
                self._apply_facing(pet)
                thread_safe_ui.refresh(ctrl)
                return
            pet["x"] = x
            ctrl.left = round(x)
            thread_safe_ui.refresh(ctrl)
            return

        # Entering a walk from a rest: pick a direction (away from the wall we
        # are closest to, when there is one) and set off.
        pet["state"] = "walk"
        pet["dir"] = (DIR_LEFT if pet["x"] >= span * 0.75
                      else DIR_RIGHT if pet["x"] <= span * 0.25
                      else self._rng.choice((DIR_LEFT, DIR_RIGHT)))
        self._apply_facing(pet)
        ctrl.left = round(pet["x"])
        thread_safe_ui.refresh(ctrl)

    def _apply_facing(self, pet: dict) -> None:
        """Mirrors the sprite to its walking direction - only on change, so a
        straight stroll produces no diffs at all."""
        want = -1 if pet["dir"] == DIR_LEFT else 1
        scale = pet["ctrl"].scale
        cur = scale.scale_x if scale is not None else 1
        if cur != want:
            pet["ctrl"].scale = ft.Scale(scale_x=want)