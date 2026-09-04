"""
--color7  "diamond" - ice cyan.

The default recipe inverted: diamond takes over as the hero colour while
lapis blue steps down into the secondary/download role. Cool slate surfaces
with a faint teal undertone keep the whole launcher reading as one world.
"""

NAME = "diamond"
DESCRIPTION = "cool slate surfaces + diamond-cyan accent, lapis demoted to secondary"

PALETTE = {
    # Neutrals: cool slate ramp, faint teal undertone.
    "BG": "#0A0E10",
    "SURFACE": "#101619",
    "SURFACE_HI": "#182125",
    "SURFACE_MAX": "#212E33",
    "BORDER": "#24343A",
    "BORDER_HI": "#39525B",

    # Text
    "TEXT": "#E9F0F1",
    "TEXT_DIM": "#9DB4B9",
    "TEXT_FAINT": "#687F84",

    # Hero: diamond.
    "ACCENT": "#6FD3E7",
    "ACCENT_HI": "#8FE2F2",
    "ACCENT_DIM": "#2A6273",
    "ON_ACCENT": "#0A0E10",

    # Semantic - lapis blue takes the slot cyan used to hold.
    "INFO": "#6E9BE0",
    "INFO_HI": "#8BB3EA",
    "INFO_DIM": "#2B4A7A",
    "ON_INFO": "#0A0E10",
    "WARNING": "#E0B04C",
    "ON_WARNING": "#0A0E10",
    "DANGER": "#DB5A4B",
    "DANGER_HI": "#E86E5F",
    "ON_DANGER": "#0A0E10",

    "CARD_FILL_HERO": "#131C20",
}

AVATAR_COLORS = [
    "#6FD3E7",  # diamond
    "#6E9BE0",  # lapis
    "#E0B04C",  # gold
    "#B57BD6",  # amethyst
    "#E06B93",  # pink
    "#3FB292",  # teal
    "#E0894A",  # copper
    "#9CB07E",  # moss
]
