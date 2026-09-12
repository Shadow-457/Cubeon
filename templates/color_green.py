"""
--color1  "green" - true black / green.

The default identity: a true-black (#050505) canvas with every surface above it
black carrying only the faintest green cast, so the launcher reads as "black and
green", never grey. Green is the single chromatic voice and lives on the things
that DO something - the Play button, the active nav item, download actions,
links. The deep green secondary holds selected fills and pressed states without
introducing a second hue.
"""

NAME = "green"
DESCRIPTION = "true black / green - green only on main things (default identity)"

PALETTE = {
    # Neutrals: true black, faint green cast on elevation. Never grey.
    "BG": "#050505",
    "SURFACE": "#0B0D0A",
    "SURFACE_HI": "#131711",
    "SURFACE_MAX": "#1A2015",
    "BORDER": "#242B1E",
    "BORDER_HI": "#39422F",

    # Text
    "TEXT": "#DDF6D5",
    "TEXT_DIM": "#9DB394",
    "TEXT_FAINT": "#68755F",

    # Hero: the greens. Primary action green, brighter hover, saturated deep
    # accent, and the near-black green secondary for selected/pressed fills.
    "ACCENT": "#46BA34",
    "ACCENT_HI": "#5FD24B",
    "ACCENT_DIM": "#2BAF00",
    "ACCENT_DEEP": "#052400",
    "ON_ACCENT": "#04120A",

    # Semantic
    "INFO": "#5FB6C6",       # diamond cyan - the one sanctioned secondary
    "INFO_HI": "#75C8D6",
    "INFO_DIM": "#285059",
    "ON_INFO": "#050505",
    "WARNING": "#DFAE44",
    "ON_WARNING": "#050505",
    "DANGER": "#CE5A4B",
    "DANGER_HI": "#DF6F5F",
    "ON_DANGER": "#050505",

    # The Play-tab hero panel: one flat step brighter than SURFACE.
    "CARD_FILL_HERO": "#0C0F0B",
}

AVATAR_COLORS = [
    "#46BA34",  # accent green
    "#5FB6C6",  # diamond cyan
    "#DFAE44",  # gold
    "#B57BD6",  # amethyst
    "#E06B93",  # pink
    "#3FB292",  # teal
    "#E0894A",  # copper
    "#6E9BE0",  # lapis
]
