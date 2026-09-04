"""
--color1  "green" - 70% black / 30% green.

Near-black neutral canvas (the olive undertone pulled way back) with green
reserved strictly for the things that DO something: the Play button, the
active nav item, download actions, links. Structure - panels, borders,
inputs, chips - stays monochrome dark, so the accent reads as emphasis
instead of paint.
"""

NAME = "green"
DESCRIPTION = "70% black / 30% green - green only on main things (default identity)"

PALETTE = {
    # Neutrals: warm near-black ramp, barely-green structure.
    "BG": "#0B0C09",
    "SURFACE": "#13150F",
    "SURFACE_HI": "#1B1E15",
    "SURFACE_MAX": "#252919",
    "BORDER": "#262A1C",
    "BORDER_HI": "#3B4229",

    # Text
    "TEXT": "#ECEDE5",
    "TEXT_DIM": "#9BA08D",
    "TEXT_FAINT": "#666C57",

    # Hero: green lives here and almost nowhere else.
    "ACCENT": "#7DC143",
    "ACCENT_HI": "#95D65E",
    "ACCENT_DIM": "#3D5B21",
    "ON_ACCENT": "#0B0C09",

    # Semantic
    "INFO": "#5FB6C6",       # diamond cyan - the one sanctioned secondary
    "INFO_HI": "#75C8D6",
    "INFO_DIM": "#285059",
    "ON_INFO": "#0B0C09",
    "WARNING": "#DFAE44",
    "ON_WARNING": "#0B0C09",
    "DANGER": "#CE5A4B",
    "DANGER_HI": "#DF6F5F",
    "ON_DANGER": "#0B0C09",

    # The Play-tab hero panel: one flat step brighter than SURFACE.
    "CARD_FILL_HERO": "#161910",
}

AVATAR_COLORS = [
    "#7DC143",  # accent green
    "#5FB6C6",  # diamond cyan
    "#DFAE44",  # gold
    "#B57BD6",  # amethyst
    "#E06B93",  # pink
    "#3FB292",  # teal
    "#E0894A",  # copper
    "#6E9BE0",  # lapis
]
