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
Cubeon is a launcher for a game made of cubes, so the UI keeps a calm, tidy
Minecraft-adjacent feel: one small radius family (RADIUS = 8px on controls,
RADIUS_LG = 12px on cards/panels) softly rounds every corner. It used to be dead
square (RADIUS = 2px) - softened on 2026-10-15 because the hard edges read as
sharp rather than crisp. A single token family still drives buttons, inputs,
cards, chips, nav and dialogs so the rounding is uniform rather than a
per-widget guess.

Colour follows a disciplined dark-UI system:

  * 60 / 30 / 10.  ~60% is the near-black canvas (BG), ~30% is structural
    surface/border neutrals, and only ~10% is chromatic - so the accent actually
    reads as emphasis instead of noise. Chroma is a scarce resource spent on the
    ONE thing that matters on each screen (the primary action, the active tab).

  * One hero, a small harmonious cast.  ACCENT is grass green - the launcher's
    identity, reserved for primary/positive/active. The secondary semantic colours
    are pulled from Minecraft's own blocks so they read as native, not bolted on:
    INFO = diamond cyan (download / informational), WARNING = gold ingot (caution),
    DANGER = redstone (destructive / error). Cyan sits near green's complement, so
    it POPS as a secondary action without fighting the green.

  * True black + green.  The canvas is true black (#050505) and every surface
    above it is black with only the faintest green cast - so the UI reads as
    "black and green", never grey. Chroma is a scarce resource: the single
    accent green carries all emphasis, and it never floods the chrome.

  * Contrast is checked, not eyeballed.  Body text pairs (TEXT/TEXT_DIM on the
    dark surfaces) clear WCAG AA (>= 4.5:1); ON_ACCENT on ACCENT clears AAA. The
    faint tier (TEXT_FAINT) is only ever used for non-essential hints/placeholders.

  * on_* colours are explicit.  Every fill has a matching foreground token chosen
    for contrast (ON_ACCENT, ON_INFO, ...), so "green button, dark text" is a
    decision recorded once, not re-derived (and mis-derived) at each call site.
"""
import flet as ft

from . import motion

# --- Neutral ramp ----------------------------------------------------------
# True black + green. The canvas is the user's #050505, and every surface above
# it is black with only the faintest green cast so the UI reads as "black and
# green", never grey. Stepped so each level of elevation is distinguishable
# without shadows.
BG = "#050505"           # app canvas - true black
# Translucent canvas (Max FPS-era look, 2026-10-14): the same colours with an
# alpha channel, ARGGGAARRGG - wait, ARGB "#AARRGGBB". page.window.bgcolor
# with alpha makes the NATIVE window translucent; the page then paints
# BG_GLASS over it. Flutter's convention is #AARRGGBB (alpha first).
BG_GLASS = "#E6050505"       # ~90% opaque canvas
SURFACE_GLASS = "#E60B0D0A"  # ~90% panels
SURFACE = "#0B0D0A"      # panels, cards, containers
SURFACE_HI = "#131711"   # hovered/elevated panels, inputs - one step up
SURFACE_MAX = "#1A2015"  # top elevation - dialogs, menus, popovers
BORDER = "#242B1E"       # low-contrast structural border - dividers and outlines
BORDER_HI = "#39422F"    # emphasized/hover border, quiet focus ring on neutrals

# --- Text ------------------------------------------------------------------
TEXT = "#DDF6D5"         # pale green-white - primary text (AAA on all surfaces)
TEXT_DIM = "#9DB394"     # muted green-grey - labels, captions (AA on SURFACE)
TEXT_FAINT = "#68755F"   # tertiary - hints, placeholders, disabled (non-essential)

# --- Brand / hero ----------------------------------------------------------
ACCENT = "#46BA34"       # green - primary action, active state, positive
ACCENT_HI = "#5FD24B"    # brighter green - hover / pressed on the hero
ACCENT_DIM = "#2BAF00"   # saturated deep green - quiet accents, subtle borders
ACCENT_DEEP = "#052400"  # near-black green - selected fills / pressed states
ON_ACCENT = "#04120A"    # text/icon placed ON an ACCENT fill (high contrast)

# --- Semantic (Minecraft-native, used sparingly) ---------------------------
INFO = "#4FB4C7"         # diamond cyan - download / secondary action / info
INFO_HI = "#63C7D8"      # brighter cyan - hover / pressed on an INFO fill
INFO_DIM = "#274F58"     # deep cyan - subtle info fills and borders
ON_INFO = "#050505"      # dark text on an INFO fill
WARNING = "#E6B23C"      # gold ingot - caution, "heads up"
ON_WARNING = "#050505"   # dark text on a WARNING fill
DANGER = "#DB5A4B"       # redstone red - destructive actions and errors
DANGER_HI = "#E86E5F"    # brighter red - hover / pressed on danger
ON_DANGER = "#050505"    # dark text on a DANGER fill (higher contrast than white)

# Semantic alias: success shares the hero green (positive == on-brand here).
SUCCESS = ACCENT

# Which color template is live, set by cubeon.color_templates.apply_template()
# while the package is imported. None until then (and for a plain green boot
# with no template at all). UI that should follow the palette - e.g. main.py
# choosing the seasonal backdrop - reads this rather than re-deriving the
# season, so an explicit --color is honoured too.
ACTIVE_TEMPLATE = None

# --- Categorical palette ---------------------------------------------------
# Used to colour per-user avatars/identicons on the Friends tabs. A categorical
# set follows different rules than the semantic palette: hues are spread evenly
# around the wheel at comparable lightness/chroma so no single user's colour
# dominates or disappears, and the first entry is the hero green so a lone friend
# still looks "Cubeon". Lives here (not duplicated per tab) so the set can't drift.
AVATAR_COLORS = [
    "#46BA34",  # green
    "#4FB4C7",  # diamond cyan
    "#E6B23C",  # gold
    "#B57BD6",  # amethyst
    "#E06B93",  # pink
    "#3FB292",  # teal
    "#E0894A",  # copper orange
    "#6E9BE0",  # lapis blue
]

# --- Depth / "liquid glass" layer -------------------------------------------
# Surfaces go translucent over the canvas and borders drop to a fraction of
# their opacity, so panels read as layered rather than flat slabs. Use these
# through the helpers below (card(), ...) rather than hand-writing opacities at
# call sites - the exact fractions ARE the look, and having them in one place
# keeps every screen consistent.
#
# 2026-10-18 ("liquid glass"): a panel is no longer merely see-through, it is
# FROSTED. `GLASS_BLUR` is a real backdrop filter - Flet compiles Container.blur
# to a BackdropFilter, i.e. it softens what is painted BEHIND the panel (the
# backdrop artwork; never the panel's own text) - and that is the one ingredient
# that turns "a slightly transparent rectangle" into glass. The fills also came
# down (55% -> 42%, and the hero panel is no longer opaque) so there is
# something for the blur to actually show through.
#
# Two consequences of a backdrop filter, worth knowing before you add one:
#   * it CLIPS. Flet wraps a blurred Container in a ClipRRect (container.dart),
#     so a panel carrying one can never let a child or a glow bleed past its own
#     bounds - do not put it on a control that needs to overflow;
#   * it COSTS. The filter re-runs whenever the pixels behind the panel change,
#     so it belongs on panels whose backdrop is the static canvas - never on a
#     row inside a scrolling list.

CARD_FILL = ft.Colors.with_opacity(0.42, SURFACE)     # translucent panel fill
CARD_FILL_HERO = ft.Colors.with_opacity(0.55, "#0C0F0B")  # hero panel: a step brighter, still glass
CARD_BORDER = ft.Colors.with_opacity(0.55, BORDER)    # low-opacity outline for panels
ROW_HOVER = ft.Colors.with_opacity(0.65, SURFACE_HI)  # quiet hover lift for borderless rows
ACCENT_TINT = ft.Colors.with_opacity(0.12, ACCENT)    # selected-state wash (nav/chips/tiles)
ACCENT_TINT_HI = ft.Colors.with_opacity(0.20, ACCENT) # hovered version of the same wash

# The frosted panel itself. Borders stay UNIFORM on purpose: Flet passes
# bgcolor/border/radius/shadow to one BoxDecoration, and a non-uniform border
# combined with a rounded rect (and a hover shadow) is exactly the shape of
# decoration Flutter refuses to paint - one stray side colour would turn every
# hovered panel into an error screen. The specular highlight is animated instead
# (cubeon/motion.py's Sheen), which is where the eye actually reads "glass".
GLASS_BLUR = ft.Blur(14, 14, ft.BlurTileMode.MIRROR)       # cards, dialogs, panels
GLASS_BLUR_SOFT = ft.Blur(10, 10, ft.BlurTileMode.MIRROR)  # large, list-bearing surfaces
GLASS_RIM = ft.Colors.with_opacity(0.12, "#FFFFFF")        # panel outline: a lit rim
GLASS_RIM_HI = ft.Colors.with_opacity(0.30, "#FFFFFF")     # ... and its hovered state
GLASS_HALO = ft.Colors.with_opacity(0.30, ACCENT)          # green bloom under a hovered panel
GLASS_HALO_PX = 20
GLASS_RADIUS_STEP = 3        # how far a hovered panel's corners open up


def glass_edge():
    """The outline of a glass panel: a whisper of white over the structural
    border, so the panel catches light on all four sides the way an edge of
    frosted glass does. Uniform by necessity (see the note above)."""
    return ft.border.Border.all(1, GLASS_RIM)


def card(*, padding=24, hero=False, blur=GLASS_BLUR):
    """Kwargs for a liquid-glass panel Container: frosted backdrop, translucent
    fill, lit rim, softly rounded radius. `hero=True` uses the slightly brighter
    fill reserved for the single dominant panel on a screen (the Play tab's
    launcher). Pass `blur=None` for a panel that must stay flat, or that needs a
    child to bleed outside it (a blurred Container clips)."""
    kwargs = {
        "bgcolor": CARD_FILL_HERO if hero else CARD_FILL,
        "border": glass_edge(),
        "border_radius": RADIUS_LG,
        "padding": padding,
    }
    if blur is not None:
        kwargs["blur"] = blur
    return kwargs


def glass_hover():
    """The hover state of a glass control, as the plain dict cubeon/motion.py's
    polish() reads: the corners open up, the rim catches the light and a green
    halo rises underneath. Kept here (not in motion) because it is palette.

    motion.py looks this up through the pinned slot at the bottom of the module
    rather than importing this module: theme imports motion, so the reverse
    import has to stay lazy."""
    return {
        "radius": GLASS_RADIUS_STEP,
        "rim": GLASS_RIM_HI,
        "halo": ft.BoxShadow(blur_radius=GLASS_HALO_PX, spread_radius=0,
                             color=GLASS_HALO),
    }


def card_border():
    """Just the low-opacity panel border, for containers that manage their own
    fill rather than using card()."""
    return ft.border.Border.all(1, CARD_BORDER)


# --- Shape (the "softly rounded" system) -----------------------------------
# ONE small radius family drives the whole app. Corners are gently rounded now
# (2026-10-15, user request - the old 2px read as sharp/harsh), not dead square;
# big surfaces take a touch more than small ones so a card doesn't look
# under-rounded next to its own padding. RADIUS_NONE stays 0 for flush insets.
RADIUS = 8          # default - buttons, inputs, chips, nav items, small elements
RADIUS_LG = 12      # cards, dialogs, large panels
RADIUS_PILL = 999   # former pills/chips - genuinely round now (clamped by size)
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
    feel dead under the cursor. This is the single hover mechanism in the app:
    ~35 call sites across every tab, all of them the same one expression.

    The work itself lives in cubeon/motion.py (2026-10-18). On top of the
    original fill swap it now fades the fill instead of snapping it, lifts the
    control a hair while hovered, and dips it while pressed - so every row,
    card and hand-built button in the launcher responds the same way, and
    Settings > Display > Motion can calm it (or switch it off) app-wide.
    Returns the container so it can be used inline where it is created.
    """
    return motion.polish(container, base_bg, hover_bg)


def apply_page_theme(page):
    """Install the design system onto the Page.

    This is where the "softly rounded + on-palette" treatment lands for Flet's
    OWN controls - the ones we don't build by hand. Custom `ft.Container` widgets
    get their look from explicit `bgcolor`/`border`/`border_radius`, but real
    Flet controls (TextButton, Dropdown menus, AlertDialog, Card, Chip, Slider,
    Checkbox, scrollbars, text selection, focus rings) take their shape and
    colour from the page theme. Setting it once here means:

      * every dialog and button shares the app's rounded corner
        (shape = block(), i.e. RADIUS), instead of Flet's own default rounding;
      * default controls pull warm Cubeon surfaces/greens from the ColorScheme
        instead of Material's stock purple-tinted greys and blue accents (this is
        what kills the off-palette blue on a bare "Cancel" TextButton);
      * a plain TextButton defaults to neutral TEXT, so an un-styled "Cancel"
        reads as secondary while an explicitly-coloured "Save"(ACCENT) / "Delete"
        (DANGER) carries the meaning - colour = intent, not decoration.
    """
    shape = block()
    # Neutral style shared by the text/icon buttons that don't declare their own
    # colour. overlay_color = a faint green wash on hover/press.
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
        # All button families share the app corner; text buttons default neutral.
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
        ink=False,
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
        ink=False,
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


# --- the one back-reference -------------------------------------------------
# theme imports motion at module scope (attach_hover delegates to it), so motion
# can never import theme. Instead it looks the glass hover state up here, at
# event time, through this slot. Pinned rather than a lazy `from . import theme`
# inside a hot handler so a rename here fails loudly in tools/test_motion.py
# instead of silently dropping the glass hover at runtime.
motion.glass_style = glass_hover
