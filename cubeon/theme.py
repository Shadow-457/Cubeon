"""
Design tokens, the design system, and the small shared components built from them.

WHY THIS MODULE EXISTS

Every tab builder in this app takes the same twelve colour/font arguments:

    build_mods_tab(page, cfg, state, version_dropdown, *, section_label,
                   BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                   TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO)

That threading is pure overhead - the values are constants, identical at every
call site, and adding one token meant editing every signature and every call.
Importing the tokens instead removes ~50 arguments across the tab builders and
makes drift impossible. The keyword arguments still work - this module is the
single source of truth they're passed *from*.

Tokens live here rather than in main.py so a tab module can import them without
importing main.py, which would be a circular import (main.py imports the tabs).

--------------------------------------------------------------------------------
THE DESIGN SYSTEM  (colour theory + why it looks the way it does)
--------------------------------------------------------------------------------
Cubeon is a launcher for a game made of cubes, so the UI is deliberately BLOCKY:
one small corner radius (RADIUS = 2px) on everything - crisp, grid-like, never
pill-shaped. A single radius token drives buttons, inputs, cards, chips, nav and
dialogs so the "blockiness" is uniform rather than a per-widget guess.

Colour follows a disciplined dark-UI system:

  * 60 / 30 / 10.  ~60% is the warm near-black canvas (BG), ~30% is structural
    surface/border neutrals, and only ~10% is chromatic - so the accent actually
    reads as emphasis instead of noise. Chroma is a scarce resource spent on the
    ONE thing that matters on each screen (the primary action, the active tab).

  * One hero, a small harmonious cast.  ACCENT is grass green - the launcher's
    identity, reserved for primary/positive/active. The secondary semantic colours
    are pulled from Minecraft's own blocks so they read as native, not bolted on:
    INFO = diamond cyan (download / informational), WARNING = gold ingot (caution),
    DANGER = redstone (destructive / error). Cyan sits near green's complement, so
    it POPS as a secondary action without fighting the green.

  * Warm, not neutral-grey.  The neutrals carry a faint olive undertone (hue ~80).
    A pure-grey launcher next to Minecraft looks like a different product; a warm
    ramp reads as part of the same world. The ramp is perceptually stepped so
    elevation (BG -> SURFACE -> SURFACE_HI -> SURFACE_MAX) is legible on a flat,
    shadowless design.

  * Contrast is checked, not eyeballed.  Body text pairs (TEXT/TEXT_DIM on the
    dark surfaces) clear WCAG AA (>= 4.5:1); ON_ACCENT on ACCENT clears AAA. The
    faint tier (TEXT_FAINT) is only ever used for non-essential hints/placeholders.

  * on_* colours are explicit.  Every fill has a matching foreground token chosen
    for contrast (ON_ACCENT, ON_INFO, ...), so "green button, dark text" is a
    decision recorded once, not re-derived (and mis-derived) at each call site.
"""
import flet as ft

# --- Neutral ramp ----------------------------------------------------------
# A dark, slightly olive scheme rather than neutral grey. Stepped so each level
# of elevation is distinguishable without relying on shadows (this is a flat UI).
BG = "#0E110A"           # app canvas - near-black, faint olive undertone
SURFACE = "#181C12"      # panels, cards, containers
SURFACE_HI = "#242A1B"   # hovered/elevated panels, inputs - one step up
SURFACE_MAX = "#2E3421"  # top elevation - dialogs, menus, popovers
BORDER = "#343B22"       # low-contrast structural border - dividers and outlines
BORDER_HI = "#4C5731"    # emphasized/hover border, quiet focus ring on neutrals

# --- Text ------------------------------------------------------------------
TEXT = "#EDEFE4"         # warm off-white - primary text (AAA on all surfaces)
TEXT_DIM = "#A7AD97"     # secondary text - labels, captions (AA on SURFACE)
TEXT_FAINT = "#6E7659"   # tertiary - hints, placeholders, disabled (non-essential)

# --- Brand / hero ----------------------------------------------------------
ACCENT = "#83C13D"       # grass green - primary action, active state, positive
ACCENT_HI = "#98D653"    # brighter green - hover / pressed on the hero
ACCENT_DIM = "#42611F"   # deep green - subtle fills, borders, quiet accents
ON_ACCENT = "#0E110A"    # text/icon placed ON an ACCENT fill (9:1 - AAA)

# --- Semantic (Minecraft-native, used sparingly) ---------------------------
INFO = "#4FB4C7"         # diamond cyan - download / secondary action / info
INFO_HI = "#63C7D8"      # brighter cyan - hover / pressed on an INFO fill
INFO_DIM = "#274F58"     # deep cyan - subtle info fills and borders
ON_INFO = "#0E110A"      # dark text on an INFO fill
WARNING = "#E6B23C"      # gold ingot - caution, "heads up"
ON_WARNING = "#0E110A"   # dark text on a WARNING fill
DANGER = "#DB5A4B"       # redstone red - destructive actions and errors
DANGER_HI = "#E86E5F"    # brighter red - hover / pressed on danger
ON_DANGER = "#0E110A"    # dark text on a DANGER fill (higher contrast than white)

# Semantic alias: success shares the hero green (positive == on-brand here).
SUCCESS = ACCENT

# --- Categorical palette ---------------------------------------------------
# Used to colour per-user avatars/identicons on the Friends tabs. A categorical
# set follows different rules than the semantic palette: hues are spread evenly
# around the wheel at comparable lightness/chroma so no single user's colour
# dominates or disappears, and the first entry is the hero green so a lone friend
# still looks "Cubeon". Lives here (not duplicated per tab) so the set can't drift.
AVATAR_COLORS = [
    "#83C13D",  # grass green
    "#4FB4C7",  # diamond cyan
    "#E6B23C",  # gold
    "#B57BD6",  # amethyst
    "#E06B93",  # pink
    "#3FB292",  # teal
    "#E0894A",  # copper orange
    "#6E9BE0",  # lapis blue
]

# --- Depth / "glass" layer --------------------------------------------------
# Surfaces go translucent over the canvas and borders drop to a fraction of
# their opacity, so panels read as layered rather than flat slabs - without
# gradients or glow. Use these through the helpers below (card(), ...) rather
# than hand-writing opacities at call sites - the exact fractions ARE the
# look, and having them in one place keeps every screen consistent.

CARD_FILL = ft.Colors.with_opacity(0.55, SURFACE)     # translucent panel fill
CARD_FILL_HERO = "#1B2113"                            # hero panel: one flat step brighter
CARD_BORDER = ft.Colors.with_opacity(0.55, BORDER)    # low-opacity outline for panels
ROW_HOVER = ft.Colors.with_opacity(0.65, SURFACE_HI)  # quiet hover lift for borderless rows
ACCENT_TINT = ft.Colors.with_opacity(0.14, ACCENT)    # selected-state wash (nav/chips/tiles)
ACCENT_TINT_HI = ft.Colors.with_opacity(0.24, ACCENT) # hovered version of the same wash


def card(*, padding=24, hero=False):
    """Kwargs for a glassy panel Container: translucent fill, faint border,
    blocky radius. `hero=True` uses the slightly brighter flat fill reserved
    for the single dominant panel on a screen (the Play tab's launcher)."""
    return {
        "bgcolor": CARD_FILL_HERO if hero else CARD_FILL,
        "border": ft.border.Border.all(1, CARD_BORDER),
        "border_radius": RADIUS_LG,
        "padding": padding,
    }


def card_border():
    """Just the low-opacity panel border, for containers that manage their own
    fill rather than using card()."""
    return ft.border.Border.all(1, CARD_BORDER)


# --- Shape (the "blocky" system) -------------------------------------------
# ONE small radius drives the whole app. Minecraft is cubic; the UI is too. The
# aliases are all equal on purpose - they exist so a hand-written call site can
# say what it means (RADIUS_PILL on a former pill) while the value stays uniform.
RADIUS = 2          # default - buttons, inputs, chips, nav items, small elements
RADIUS_LG = 2       # cards, dialogs, large panels (kept equal for uniformity)
RADIUS_PILL = 2     # former pills/chips - now blocky like everything else
RADIUS_NONE = 0     # flush insets - progress bars, dividers, image edges

# --- Spacing scale ---------------------------------------------------------
# A 4px base grid. Consistent spacing is what makes a dense settings screen read
# as "organised" rather than "cramped"; these are the rungs to snap padding and
# gaps to instead of ad-hoc numbers.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32

# --- Type ------------------------------------------------------------------
# Minecraftia is the blocky pixel display face, used for LARGE text only
# (titles, the wordmark, big buttons) - that's where a pixel font reads crisp
# and looks right. At small sizes Minecraftia anti-aliases to a blur (Flet
# can't turn AA off), so all the small labels/data/console text uses Inter,
# which stays readable at 11-13px. Both files are bundled under assets/fonts
# and loaded from the local asset dir (never fetched over the network), so the
# window appears instantly even offline.
FONT_DISPLAY = "Minecraftia"   # blocky pixel display face - titles and big text
FONT_BODY = "Inter"            # readable body/label text (small and long-form)
FONT_MONO = "Inter"            # small labels, version ids, console - too small
                               # for a pixel face, so it shares Inter

# Registered next to the family names above so a font can't be referenced
# without also being registered here. Values are asset-relative paths (resolved
# against assets_dir by Flet), NOT URLs - bundling them is what makes startup
# instant and offline-friendly.
FONT_URLS = {
    "Minecraftia": "fonts/Minecraftia-Regular.ttf",
    "Inter": "fonts/Inter.ttf",
}

# Every token name a tab builder currently accepts as a keyword argument.
# Passing `**THEME` is what lets the existing signatures keep working unchanged.
#
# IMPORTANT: do NOT add keys here. The tab builders take these as *fixed* keyword
# arguments (not **kwargs), so an extra key would raise TypeError at every call
# site. New tokens (INFO, RADIUS, ON_ACCENT, ...) are module-level constants that
# a file imports directly - e.g. `from cubeon.theme import INFO, RADIUS`.
THEME = {
    "BG": BG,
    "SURFACE": SURFACE,
    "SURFACE_HI": SURFACE_HI,
    "BORDER": BORDER,
    "ACCENT": ACCENT,
    "ACCENT_DIM": ACCENT_DIM,
    "TEXT": TEXT,
    "TEXT_DIM": TEXT_DIM,
    "DANGER": DANGER,
    "FONT_DISPLAY": FONT_DISPLAY,
    "FONT_MONO": FONT_MONO,
}


def block(radius=RADIUS):
    """The app's corner shape as an OutlinedBorder, for anywhere Flet wants a
    `shape=` (buttons, dialogs, cards) rather than a `border_radius=`."""
    return ft.RoundedRectangleBorder(radius=radius)


def attach_hover(container, base_bg, hover_bg):
    """Give a hand-built `ft.Container` button a hover state.

    Custom Container "buttons" (the app builds most of them by hand) get no
    hover feedback for free the way real Flet buttons do - so without this they
    feel dead under the cursor. This wires an on_hover that swaps the fill and
    self-updates, the single affordance rule applied consistently. Returns the
    container so it can be used inline where the Container is created.
    """
    def _h(e):
        container.bgcolor = hover_bg if e.data == "true" else base_bg
        container.update()
    container.on_hover = _h
    return container


def apply_page_theme(page):
    """Install the design system onto the Page.

    This is where the "blocky + on-palette" treatment lands for Flet's OWN
    controls - the ones we don't build by hand. Custom `ft.Container` widgets get
    their look from explicit `bgcolor`/`border`/`border_radius`, but real Flet
    controls (TextButton, Dropdown menus, AlertDialog, Card, Chip, Slider,
    Checkbox, scrollbars, text selection, focus rings) take their shape and
    colour from the page theme. Setting it once here means:

      * every dialog and button is squared off (shape = block()), matching the
        hand-built Containers instead of Flet's default ~8-20px rounding;
      * default controls pull warm Cubeon surfaces/greens from the ColorScheme
        instead of Material's stock purple-tinted greys and blue accents (this is
        what kills the off-palette blue on a bare "Cancel" TextButton);
      * a plain TextButton defaults to neutral TEXT, so an un-styled "Cancel"
        reads as secondary while an explicitly-coloured "Save"(ACCENT) / "Delete"
        (DANGER) carries the meaning - colour = intent, not decoration.
    """
    shape = block()
    # Neutral, blocky style shared by the text/icon buttons that don't declare
    # their own colour. overlay_color = a faint green wash on hover/press.
    neutral_btn = ft.ButtonStyle(
        shape=shape,
        color=TEXT,
        overlay_color=ft.Colors.with_opacity(0.10, ACCENT),
    )
    shaped_btn = ft.ButtonStyle(shape=shape)

    scheme = ft.ColorScheme(
        # Hero
        primary=ACCENT, on_primary=ON_ACCENT,
        primary_container=ACCENT_DIM, on_primary_container=TEXT,
        # Secondary action / info
        secondary=INFO, on_secondary=ON_INFO,
        secondary_container=INFO_DIM, on_secondary_container=TEXT,
        # Caution
        tertiary=WARNING, on_tertiary=ON_WARNING,
        # Destructive / error
        error=DANGER, on_error=ON_DANGER,
        # Surfaces - map Material's elevation ramp onto our warm neutrals so
        # menus, dropdown popups and dialogs sit on Cubeon surfaces, not grey.
        surface=SURFACE, on_surface=TEXT, on_surface_variant=TEXT_DIM,
        surface_container_lowest=BG,
        surface_container_low=SURFACE,
        surface_container=SURFACE_HI,
        surface_container_high=SURFACE_MAX,
        surface_container_highest=BORDER,
        surface_dim=BG, surface_bright=SURFACE_HI,
        surface_tint=SURFACE,          # no primary-tinted elevation (flat design)
        # Lines and inverses
        outline=BORDER, outline_variant=ACCENT_DIM,
        shadow="#000000", scrim="#000000",
        inverse_surface=TEXT, on_inverse_surface=BG, inverse_primary=ACCENT_DIM,
    )

    page.theme = ft.Theme(
        font_family=FONT_BODY,
        use_material3=True,
        color_scheme=scheme,
        # Squared-off, warm dialogs (SURFACE_MAX = top elevation), flat.
        dialog_theme=ft.DialogTheme(
            shape=shape, bgcolor=SURFACE_MAX, elevation=0,
            title_text_style=ft.TextStyle(
                color=TEXT, font_family=FONT_DISPLAY, size=20),
            content_text_style=ft.TextStyle(color=TEXT_DIM, font_family=FONT_BODY, size=13),
        ),
        # All button families squared off; text buttons default to neutral.
        text_button_theme=ft.TextButtonTheme(style=neutral_btn),
        icon_button_theme=ft.IconButtonTheme(style=shaped_btn),
        filled_button_theme=ft.FilledButtonTheme(style=shaped_btn),
        outlined_button_theme=ft.OutlinedButtonTheme(style=shaped_btn),
        card_theme=ft.CardTheme(shape=shape),
        chip_theme=ft.ChipTheme(shape=shape),
        # A quiet, on-brand scrollbar instead of the stock translucent white.
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color=ft.Colors.with_opacity(0.35, BORDER_HI),
            thickness=8, radius=RADIUS,
        ),
    )
    page.theme_mode = ft.ThemeMode.DARK
    return page.theme


def pixel_divider(color=BORDER, height=1):
    """A thin horizontal rule."""
    return ft.Container(height=height, bgcolor=color)


def section_label(text):
    """Small uppercase heading above each block of settings. Rendered in Inter
    (FONT_MONO is Inter now that small text avoids Minecraftia), so it can take
    a real semibold weight - no synthesized faux-bold, no tracking needed."""
    return ft.Text(
        text.upper(),
        size=12,
        weight=ft.FontWeight.W_600,
        color=TEXT_DIM,
        font_family=FONT_MONO,
    )


def quiet_chip(label, selected=False, on_click=None):
    """A category filter that whispers. Unselected chips are bare text - no
    fill, no border - so a row of them reads as one quiet line of filters
    instead of a strip of buttons; the selected chip is a faint green wash
    with green text. This is the fix for 'box inside box inside box': filters
    stop competing with the content they filter."""
    return ft.Container(
        content=ft.Text(
            label,
            size=12,
            color=ACCENT if selected else TEXT_DIM,
            weight=ft.FontWeight.W_700 if selected else ft.FontWeight.W_500,
        ),
        bgcolor=ACCENT_TINT if selected else None,
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=10, vertical=5),
        ink=True,
        on_click=on_click,
        animate=150,
    )


def text_tab(label, selected=False, on_click=None):
    """A top-level segment styled as an underline tab rather than a button -
    the selected section gets a small accent rule underneath and full-brightness
    text; everything else is quiet dim text. Removes another class of boxes
    from the chrome above the actual content."""
    return ft.Container(
        content=ft.Container(
            content=ft.Text(
                label,
                size=13,
                color=TEXT if selected else TEXT_DIM,
                weight=ft.FontWeight.W_700 if selected else ft.FontWeight.W_500,
            ),
            padding=ft.padding.Padding.only(bottom=7),
            border=ft.border.Border.only(
                bottom=ft.border.BorderSide(2, ACCENT if selected else "transparent")),
        ),
        padding=ft.padding.Padding.symmetric(horizontal=2),
        ink=True,
        on_click=on_click,
    )


def _toggle_pop(switch, base_scale):
    """The little spring a toggle does when it flips.

    The switch briefly grows to 1.15x its rest size, then settles back. The
    grow is immediate (so it reads as a reaction to the click); the settle is
    on a background timer because there is no second event to hook - the
    switch's own animate_scale handles the smoothness of BOTH legs, this just
    supplies the keyframes. The timer thread only flips a float and calls
    update(), so it is fire-and-forget: if the tab was rebuilt in those 120ms
    the update raises harmlessly and is swallowed.
    """
    switch.scale = base_scale * 1.15
    try:
        switch.update()
    except Exception:
        pass  # not mounted yet - the scale keyframes still get scheduled

    def _settle():
        switch.scale = base_scale
        try:
            switch.update()
        except Exception:
            pass  # page gone or control unmounted - the animation is over anyway

    import threading
    threading.Timer(0.12, _settle).start()


def animated_switch(value=False, on_change=None, scale=1.0, **kwargs):
    """A Switch that springs when toggled.

    Drop-in replacement for ft.Switch used everywhere the launcher shows an
    on/off toggle (mods enable/disable, plugin enable/disable, backup
    settings, server properties). Same constructor surface - any ft.Switch
    kwarg passes straight through - plus:

      scale       the switch's rest scale (mods_tab draws its toggles at 0.85;
                  the pop is relative to this, so small toggles stay small)
      on_change   the real handler; it still runs, AFTER the pop starts

    If no on_change is given (toggles whose value is only read back later,
    like the server-properties cards) the pop still runs - the wrapper is
    installed either way.
    """
    sw = ft.Switch(
        value=value,
        scale=scale,
        animate_scale=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        **kwargs,
    )

    def _on_change(e=None):
        _toggle_pop(sw, scale)
        if on_change is not None:
            return on_change(e)

    sw.on_change = _on_change
    return sw


def toggle_wrap(handler, switch, base_scale=1.0):
    """Wraps an EXISTING switch's handler so it pops on toggle.

    For switches whose on_change is only known after the widget is built
    (e.g. the Settings-tab backup switches, whose handlers reference other
    widgets defined later). Assign the wrapped function afterwards:

        switch.on_change = toggle_wrap(my_handler, switch)
    """
    def _wrapped(e=None):
        _toggle_pop(switch, base_scale)
        return handler(e)
    return _wrapped
