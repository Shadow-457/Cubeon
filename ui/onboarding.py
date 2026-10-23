"""First-run onboarding: a full-bleed, three-beat welcome.

The first version of this screen was a generic left-rail wizard - numbered
steps in a sidebar, four rows of feature copy, a card inside a card. It read
like a SaaS signup: the launcher's own character (the blocky display type, the
grass block, the seasonal companion, the glass backdrop) was nowhere in it.

This one is deliberately the opposite shape:

* NO sidebar. The whole window is the stage; the only chrome is a small brand
  mark, four progress ticks, and the two footer buttons.
* The app's real backdrop (the same glass_<season>.jpg the window wears) sits
  behind a dark scrim, so the tour looks like Cubeon, not like a web form.
* Each beat has ONE strong prop - the rotating grass block, a Minecraft-style
  nametag, four feature tiles, the season's companion - and as little copy as
  the point needs.
* Motion is layered but cheap: the overlay fades and scales up once, the step
  body cross-fades while drifting up 1.2% of its own height, and the progress
  ticks stretch in place. The only timers are one 30ms settle per step and the
  fade-out retire, both generation-guarded.
"""
from __future__ import annotations

import threading

import flet as ft

from cubeon import thread_safe_ui
from cubeon.theme import (
    ACCENT, ACCENT_TINT, BG, BORDER, FONT_DISPLAY, FONT_MONO,
    ON_ACCENT, RADIUS, RADIUS_LG, SURFACE_HI, TEXT, TEXT_DIM, TEXT_FAINT,
)
from ui.seasonal_ui import (
    pet_line as season_pet_line,
    pet_name as season_pet_name,
    pet_src as season_pet_src,
)

STEP_COUNT = 4
FADE_MS = 220
DRIFT_MS = 320
RETIRE_MS = 340
MAX_CONTENT_W = 880
# Every beat gets the same stage height so switching steps never re-centers the
# headline/footer (that vertical jump was the "not seamless" part, 2026-10-23).
# Tall enough for the four feature tiles, short enough for the 640px minimum
# window (top bar + stage + footer + padding fits).
STAGE_H = 372


# ---------------------------------------------------------------------------
# Small pieces
# ---------------------------------------------------------------------------

def _field_error(field, message):
    """Set/clear a TextField error across both Flet spellings.

    The project pins Flet 0.86 (where the attribute is `error_text`) while
    newer Flet renamed it to `error`; assigning the wrong one raises
    AttributeError from inside an on_change handler, which is exactly how the
    mega-smoke caught this. Prefer the modern name, fall back to the pinned
    one.
    """
    if hasattr(field, "error"):
        field.error = message
    else:
        field.error_text = message


def _has_field_error(field) -> bool:
    return bool(getattr(field, "error", None)
                or getattr(field, "error_text", None))


def _eyebrow(text: str) -> ft.Text:
    return ft.Text(
        text.upper(), size=10.5, color=ACCENT, font_family=FONT_MONO,
        weight=ft.FontWeight.W_700,
        style=ft.TextStyle(letter_spacing=1.8),
    )


def _headline(text: str, size: int = 46) -> ft.Text:
    return ft.Text(text, size=size, color=TEXT, font_family=FONT_DISPLAY,
                   weight=ft.FontWeight.W_600)


def _body(text: str) -> ft.Text:
    return ft.Text(text, size=14, color=TEXT_DIM)


def _prop_glow() -> ft.Container:
    """The soft green halo behind a hero prop (the grass block, a pet).

    A radial gradient is cheaper than a shadow and fades all the way to
    transparent, so it reads as light on the backdrop rather than as a disc.
    """
    return ft.Container(
        width=300, height=300, border_radius=150,
        gradient=ft.RadialGradient(
            colors=[ft.Colors.with_opacity(0.30, ACCENT),
                    ft.Colors.with_opacity(0.0, ACCENT)],
            radius=0.55,
        ),
    )


def _feature_tile(icon, title: str, detail: str) -> ft.Container:
    # Fixed height + no cross-axis STRETCH: a Row that STRETCHes inside an
    # unbounded-height Column demands infinite height, and Flutter then lays
    # the whole beat out off-screen (the "empty features page" report,
    # 2026-10-23). A fixed height keeps the four tiles even without it.
    return ft.Container(
        expand=True,
        height=116,
        content=ft.Column(
            [
                ft.Icon(icon, size=22, color=ACCENT),
                ft.Container(height=10),
                ft.Text(title, size=13.5, color=TEXT,
                        weight=ft.FontWeight.W_600),
                ft.Text(detail, size=11.5, color=TEXT_DIM,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ],
            spacing=2, tight=True,
        ),
        bgcolor=ft.Colors.with_opacity(0.34, SURFACE_HI),
        border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS_LG,
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=14),
    )


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------

def build_onboarding(page, *, initial_name: str, info, friends_on: bool,
                     season_on: bool, backdrop=None, validate_name,
                     on_season_toggle, on_finish) -> ft.Container:
    """Build the overlay. The caller appends it to `page.overlay`, then fades it
    in by setting `opacity = 1` (and `scale = 1`) after the window reveal.

    Callbacks
    ---------
    validate_name(name) -> (ok, error)
    on_season_toggle(on: bool)           - saves the seasonal switch immediately
    on_finish(name) -> (ok, error)       - saves cfg + publishes the username;
                                           the overlay only retires on (True, "")
    """
    state = {"index": 0, "done": False, "gen": 0}
    name_value = (initial_name or "").strip()

    # --- top bar: brand, ticks, counter -----------------------------------
    tick_bars = []
    for _ in range(STEP_COUNT):
        bar = ft.Container(
            width=44, height=4, border_radius=2,
            bgcolor=ft.Colors.with_opacity(0.18, TEXT),
            animate=ft.Animation(260, ft.AnimationCurve.EASE_OUT),
        )
        tick_bars.append(bar)

    step_counter = ft.Text("01 / 04", size=10.5, color=TEXT_FAINT,
                           font_family=FONT_MONO)

    top_bar = ft.Row(
        [
            ft.Row(
                [
                    ft.Image(src="cube.svg", width=28, height=28,
                             fit=ft.BoxFit.CONTAIN),
                    ft.Text("Cubeon", size=18, color=TEXT,
                            font_family=FONT_DISPLAY,
                            weight=ft.FontWeight.W_600),
                ],
                spacing=9, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(expand=True),
            ft.Row(tick_bars, spacing=6),
            ft.Container(width=12),
            step_counter,
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # --- beat 1: welcome ---------------------------------------------------
    welcome_visual = ft.Stack(
        [
            ft.Container(
                content=_prop_glow(),
                alignment=ft.Alignment.CENTER,
            ),
            ft.Container(
                content=ft.Image(src="cubeon-rotating.gif", width=200,
                                 height=200, fit=ft.BoxFit.CONTAIN),
                alignment=ft.Alignment.CENTER,
            ),
        ],
        width=300, height=300,
    )
    welcome = ft.Row(
        [
            ft.Column(
                [
                    _eyebrow("Welcome"),
                    ft.Container(height=12),
                    _headline("Minecraft.\nOne click.", 54),
                    ft.Container(height=14),
                    ft.Container(
                        width=520,
                        content=_body(
                            "Cubeon picks the version, fixes the folder, and "
                            "launches the game. You just press play."),
                    ),
                    ft.Container(height=18),
                    ft.Text("Free · No account needed", size=11.5,
                            color=TEXT_FAINT, font_family=FONT_MONO),
                ],
                spacing=0, tight=True, expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            ft.Container(width=28),
            welcome_visual,
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # --- beat 2: the name --------------------------------------------------
    name_field = ft.TextField(
        value=name_value,
        hint_text="Steve",
        prefix_icon=ft.Icons.PERSON_ROUNDED,
        border=ft.InputBorder.NONE,
        bgcolor=ft.Colors.with_opacity(0.40, SURFACE_HI),
        color=TEXT,
        text_style=ft.TextStyle(size=15),
        content_padding=ft.padding.Padding.symmetric(horizontal=18, vertical=18),
        border_radius=RADIUS,
        height=56,
        width=400,
        autocorrect=False,
        enable_suggestions=False,
        on_submit=lambda e: _next(),
    )
    preview_name = ft.Text(name_value or "Player", size=26, color=TEXT,
                           font_family=FONT_DISPLAY,
                           weight=ft.FontWeight.W_600, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS)
    name_preview = ft.Container(
        content=ft.Column(
            [
                ft.Text("IN-GAME", size=9, color=ACCENT, font_family=FONT_MONO,
                        weight=ft.FontWeight.W_700,
                        style=ft.TextStyle(letter_spacing=1.6)),
                preview_name,
            ],
            spacing=2, tight=True,
        ),
        bgcolor=ft.Colors.with_opacity(0.52, "#000000"),
        border=ft.border.Border.all(1, ft.Colors.with_opacity(0.35, ACCENT)),
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=20, vertical=12),
        width=400,
    )

    def _name_changed(e=None):
        value = (name_field.value or "").strip()
        preview_name.value = value or "Player"
        if _has_field_error(name_field):
            _field_error(name_field, None)
            thread_safe_ui.refresh(name_field)
        thread_safe_ui.refresh(preview_name)

    name_field.on_change = _name_changed

    name_step = ft.Row(
        [
            ft.Column(
                [
                    _eyebrow("Your name"),
                    ft.Container(height=12),
                    _headline("Pick a name.", 46),
                    ft.Container(height=12),
                    ft.Container(
                        width=480,
                        content=_body("It's what other players see. Three to "
                                      "sixteen characters."),
                    ),
                    ft.Container(height=22),
                    name_field,
                    ft.Container(height=16),
                    name_preview,
                ],
                spacing=0, tight=True, expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            ft.Container(expand=True),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # --- beat 3: features --------------------------------------------------
    if friends_on:
        fourth = (ft.Icons.FORUM_ROUNDED, "Friends", "Chat and worlds")
    else:
        fourth = (ft.Icons.PALETTE_ROUNDED, "Skins & capes", "Plus a companion")
    tiles = [
        _feature_tile(ft.Icons.DOWNLOAD_ROUNDED, "Any version",
                      "Vanilla to snapshots"),
        _feature_tile(ft.Icons.EXTENSION_ROUNDED, "Mods & packs",
                      "Fabric, Forge, Modrinth"),
        _feature_tile(ft.Icons.DNS_ROUNDED, "Live servers",
                      "Counts before you join"),
        _feature_tile(*fourth),
    ]
    features_step = ft.Column(
        [
            _eyebrow("What's inside"),
            ft.Container(height=12),
            _headline("Four things, done.", 46),
            ft.Container(height=12),
            ft.Container(
                width=560,
                content=_body("The parts you'd normally stitch together from "
                              "four different tools - one tab away."),
            ),
            ft.Container(height=24),
            ft.Row(tiles, spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.START),
        ],
        spacing=0, tight=True,
        alignment=ft.MainAxisAlignment.CENTER,
    )

    # --- beat 4: seasonal --------------------------------------------------
    season_name = season_pet_name(info)
    season_line = season_pet_line(info)
    season_switch = ft.Switch(value=bool(season_on), active_color=ACCENT)
    season_note = ft.Text(
        (f"On - the {info.label.lower()} palette starts with the next launch."
         if season_on else
         "Off - the normal green look. Turn it on to try the seasonal one."),
        size=10.5, color=TEXT_FAINT,
    )

    def _season_changed(e=None):
        on = bool(season_switch.value)
        try:
            on_season_toggle(on)
        except Exception:
            pass
        season_note.value = (
            f"On - the {info.label.lower()} palette starts with the next "
            f"launch."
            if on else
            "Off - the normal green look. Turn it on to try the seasonal one.")
        thread_safe_ui.refresh(season_note)

    season_switch.on_change = _season_changed

    season_prop = ft.Stack(
        [
            ft.Container(content=_prop_glow(), alignment=ft.Alignment.CENTER),
            ft.Container(
                content=ft.Column(
                    [
                        ft.Image(src=season_pet_src(info), width=112,
                                 height=112, fit=ft.BoxFit.CONTAIN),
                        ft.Text(season_name, size=12.5, color=TEXT,
                                weight=ft.FontWeight.W_600),
                        ft.Text(season_line, size=10.5, color=TEXT_FAINT,
                                font_family=FONT_MONO),
                    ],
                    spacing=6, tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                alignment=ft.Alignment.CENTER,
            ),
        ],
        width=260, height=260,
    )
    season_chips = ft.Row(
        [
            ft.Container(
                content=ft.Text("New palette", size=10.5, color=TEXT_DIM,
                                font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.30, SURFACE_HI),
                border=ft.border.Border.all(1, BORDER),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=9, vertical=4),
            ),
            ft.Container(
                content=ft.Text("New companion", size=10.5, color=TEXT_DIM,
                                font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.30, SURFACE_HI),
                border=ft.border.Border.all(1, BORDER),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=9, vertical=4),
            ),
            ft.Container(
                content=ft.Text("4× a year", size=10.5, color=TEXT_DIM,
                                font_family=FONT_MONO),
                bgcolor=ft.Colors.with_opacity(0.30, SURFACE_HI),
                border=ft.border.Border.all(1, BORDER),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=9, vertical=4),
            ),
        ],
        spacing=6, wrap=True,
    )
    season_switch_row = ft.Container(
        content=ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(f"Wear the {info.label.lower()} look",
                                size=13, color=TEXT,
                                weight=ft.FontWeight.W_600),
                        season_note,
                    ],
                    spacing=2, tight=True, expand=True,
                ),
                season_switch,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=ft.Colors.with_opacity(0.34, SURFACE_HI),
        border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=11),
        width=520,
    )
    seasonal_step = ft.Row(
        [
            ft.Column(
                [
                    _eyebrow("Seasonal look"),
                    ft.Container(height=12),
                    _headline(f"{info.label} is here.", 46),
                    ft.Container(height=12),
                    ft.Container(
                        width=480,
                        content=_body(
                            f"Cubeon is dressed for {info.place} - palette, "
                            "companion and weather, all read from your clock. "
                            "No location permission."),
                    ),
                    ft.Container(height=14),
                    season_chips,
                    ft.Container(height=18),
                    season_switch_row,
                ],
                spacing=0, tight=True, expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            ft.Container(width=20),
            season_prop,
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    step_views = [welcome, name_step, features_step, seasonal_step]
    for view in step_views:
        view.offset = ft.Offset(0, 0)
        view.animate_offset = ft.Animation(DRIFT_MS,
                                           ft.AnimationCurve.EASE_OUT_CUBIC)

    # --- footer + switching ------------------------------------------------
    back_btn = ft.TextButton(
        "Back", icon=ft.Icons.ARROW_BACK_ROUNDED,
        visible=False,
        style=ft.ButtonStyle(color=TEXT_DIM, icon_color=TEXT_DIM),
    )
    next_btn = ft.FilledButton(
        "Let's go", icon=ft.Icons.ARROW_FORWARD_ROUNDED,
        style=ft.ButtonStyle(
            color=ON_ACCENT, bgcolor=ACCENT,
            shape=ft.RoundedRectangleBorder(radius=RADIUS),
            padding=ft.padding.Padding.symmetric(horizontal=24, vertical=18),
            text_style=ft.TextStyle(size=13,
                                    weight=ft.FontWeight.W_600),
        ),
    )
    footer = ft.Row(
        [
            back_btn,
            ft.Container(expand=True),
            next_btn,
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    switcher = ft.AnimatedSwitcher(
        content=step_views[0],
        transition=ft.AnimatedSwitcherTransition.FADE,
        duration=FADE_MS,
        reverse_duration=FADE_MS,
        switch_in_curve=ft.AnimationCurve.EASE_OUT,
        switch_out_curve=ft.AnimationCurve.EASE_IN,
    )

    layout = ft.Container(
        left=0, top=0, right=0, bottom=0,
        padding=ft.padding.Padding.symmetric(horizontal=48, vertical=32),
        content=ft.Column(
            [
                top_bar,
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Container(
                        width=MAX_CONTENT_W, height=STAGE_H,
                        alignment=ft.Alignment.CENTER,
                        content=switcher,
                    ),
                ),
                footer,
            ],
            spacing=0, expand=True,
        ),
    )

    # Backdrop layers: the real window backdrop, a scrim, and one green bloom.
    bg_layer = ft.Container(
        left=0, top=0, right=0, bottom=0,
        bgcolor=BG,
        image=(ft.DecorationImage(src=backdrop, fit=ft.BoxFit.COVER,
                                  opacity=0.40,
                                  filter_quality=ft.FilterQuality.MEDIUM)
               if backdrop else None),
    )
    scrim = ft.Container(
        left=0, top=0, right=0, bottom=0,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=[
                ft.Colors.with_opacity(0.58, BG),
                ft.Colors.with_opacity(0.84, BG),
                ft.Colors.with_opacity(0.97, BG),
            ],
            stops=[0.0, 0.52, 1.0],
        ),
    )
    bloom = ft.Container(
        right=-140, top=-160, width=620, height=620, border_radius=310,
        gradient=ft.RadialGradient(
            colors=[ft.Colors.with_opacity(0.22, ACCENT),
                    ft.Colors.with_opacity(0.0, ACCENT)],
            radius=0.55,
        ),
    )

    overlay = ft.Container(
        left=0, top=0, right=0, bottom=0,
        visible=True,
        opacity=0.0,
        scale=ft.Scale(0.985),
        ink=False,
        # Catch taps on empty space so the Play tab behind the tour can't be
        # clicked through. Children still win their own hits.
        on_click=lambda e: None,
        animate_opacity=ft.Animation(320, ft.AnimationCurve.EASE_OUT),
        animate_scale=ft.Animation(420, ft.AnimationCurve.EASE_OUT_CUBIC),
        content=ft.Stack(
            [bg_layer, scrim, bloom, layout],
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        ),
    )

    # --- behaviour ---------------------------------------------------------
    def _sync_chrome():
        current = state["index"]
        for i, bar in enumerate(tick_bars):
            if i == current:
                bar.width = 72
                bar.bgcolor = ACCENT
            elif i < current:
                bar.width = 44
                bar.bgcolor = ft.Colors.with_opacity(0.55, ACCENT)
            else:
                bar.width = 44
                bar.bgcolor = ft.Colors.with_opacity(0.18, TEXT)
            thread_safe_ui.refresh(bar)
        step_counter.value = f"0{current + 1} / 0{STEP_COUNT}"
        thread_safe_ui.refresh(step_counter)
        back_btn.visible = current > 0
        next_btn.content = ("Start playing" if current == STEP_COUNT - 1
                            else ("Let's go" if current == 0 else "Continue"))
        next_btn.icon = (ft.Icons.PLAY_ARROW_ROUNDED
                         if current == STEP_COUNT - 1
                         else ft.Icons.ARROW_FORWARD_ROUNDED)
        thread_safe_ui.refresh(back_btn)
        thread_safe_ui.refresh(next_btn)

    def _go(index: int):
        index = max(0, min(index, STEP_COUNT - 1))
        state["index"] = index
        state["gen"] += 1
        gen = state["gen"]
        view = step_views[index]
        # Mount it a hair low, then let its own animate_offset lift it into
        # place while the switcher cross-fades. The 30ms settle gives Flet one
        # flush to record the start value; without it the drift is skipped.
        view.offset = ft.Offset(0, 0.012)
        switcher.content = view
        thread_safe_ui.refresh(switcher)
        _sync_chrome()

        def _settle():
            if state["gen"] != gen or state["done"]:
                return
            view.offset = ft.Offset(0, 0)
            thread_safe_ui.refresh(view)

        threading.Timer(0.03, _settle).start()

        if index == 1:
            try:
                run_task = getattr(page, "run_task", None)
                if callable(run_task):
                    run_task(name_field.focus)
            except Exception:
                pass

    def _finish():
        if state["done"]:
            return
        ok, err = on_finish((name_field.value or "").strip())
        if not ok:
            if state["index"] != 1:
                _go(1)
            _field_error(name_field, err or "Please check that name")
            thread_safe_ui.refresh(name_field)
            return
        state["done"] = True
        overlay.opacity = 0
        overlay.scale = ft.Scale(0.99)
        thread_safe_ui.refresh(overlay)

        def _retire():
            if not state["done"] or overlay.opacity != 0:
                return
            try:
                overlay.visible = False
                thread_safe_ui.refresh(overlay)
            except Exception:
                pass

        threading.Timer(RETIRE_MS / 1000.0, _retire).start()

    def _next(e=None):
        index = state["index"]
        if index == 1:
            name = (name_field.value or "").strip()
            ok, err = validate_name(name)
            if not ok:
                _field_error(name_field, err)
                thread_safe_ui.refresh(name_field)
                return
        if index == STEP_COUNT - 1:
            _finish()
            return
        _go(index + 1)

    back_btn.on_click = lambda e: _go(state["index"] - 1)
    next_btn.on_click = _next
    _sync_chrome()
    return overlay
