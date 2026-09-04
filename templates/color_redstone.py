"""
--color4  "redstone" - the machine that's ON.

Warm red-tinted charcoal with a bright redstone-red accent: the power/energy
face of Minecraft. Because the accent itself is red, danger is re-tuned to a
much deeper brick tone (with light text) so destructive actions read darker
and heavier than primary ones instead of competing with them.
"""

NAME = "redstone"
DESCRIPTION = "red-tinted dark + bright redstone accent; danger deepened to brick"

PALETTE = {
    # Neutrals: red-tinted dark ramp.
    "BG": "#0E0B0A",
    "SURFACE": "#171210",
    "SURFACE_HI": "#201917",
    "SURFACE_MAX": "#2B211E",
    "BORDER": "#2F2522",
    "BORDER_HI": "#4A3733",

    # Text
    "TEXT": "#F0EAE8",
    "TEXT_DIM": "#B0A29D",
    "TEXT_FAINT": "#7A6C67",

    # Hero: live redstone.
    "ACCENT": "#E0524A",
    "ACCENT_HI": "#EE6A60",
    "ACCENT_DIM": "#7A2E28",
    "ON_ACCENT": "#0E0B0A",

    # Semantic - cyan stays the cool counterpoint; danger goes DARK brick
    # (with light text) so it can't be mistaken for the bright accent.
    "INFO": "#58B7C9",
    "INFO_HI": "#6FC9DA",
    "INFO_DIM": "#274E58",
    "ON_INFO": "#0E0B0A",
    "WARNING": "#E0B04C",
    "ON_WARNING": "#0E0B0A",
    "DANGER": "#A63A2E",
    "DANGER_HI": "#BC4A3C",
    "ON_DANGER": "#F5EDEA",

    "CARD_FILL_HERO": "#1B1512",
}

AVATAR_COLORS = [
    "#E0524A",  # redstone
    "#58B7C9",  # cyan
    "#E0B04C",  # gold
    "#B57BD6",  # amethyst
    "#E06B93",  # pink
    "#3FB292",  # teal
    "#6E9BE0",  # lapis
    "#9CB07E",  # moss
]
