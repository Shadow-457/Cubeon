"""
--color5  "carbon" - 90% black / 10% green.

Even quieter than --color1: an almost pure-black canvas where green is
rationed down to the bare essentials - the Play button, the active nav
marker, download actions. Even the secondary download colour is demoted to
desaturated steel so no second hue competes, and semantic gold/redstone are
muted until they're actually needed.
"""

NAME = "carbon"
DESCRIPTION = "90% black / 10% green - green rationed to the bare essentials"

PALETTE = {
    # Neutrals: near-pure-black ramp, whisper of warmth.
    "BG": "#0A0B09",
    "SURFACE": "#101210",
    "SURFACE_HI": "#161914",
    "SURFACE_MAX": "#1E221B",
    "BORDER": "#20241B",
    "BORDER_HI": "#323A28",

    # Text
    "TEXT": "#E8EAE2",
    "TEXT_DIM": "#93988A",
    "TEXT_FAINT": "#61665A",

    # Hero: the 10% - one restrained green, nothing else chromatic.
    "ACCENT": "#6FAF3C",
    "ACCENT_HI": "#84C74C",
    "ACCENT_DIM": "#35511E",
    "ON_ACCENT": "#0A0B09",

    # Semantic: deliberately desaturated so green stays the only colour.
    "INFO": "#7C99A0",        # steel - download reads as "secondary", not "cyan"
    "INFO_HI": "#92ACB2",
    "INFO_DIM": "#33454A",
    "ON_INFO": "#0A0B09",
    "WARNING": "#C7A94A",
    "ON_WARNING": "#0A0B09",
    "DANGER": "#C25446",
    "DANGER_HI": "#D2685A",
    "ON_DANGER": "#0A0B09",

    "CARD_FILL_HERO": "#131610",
}

AVATAR_COLORS = [
    "#6FAF3C",  # the one green
    "#7C99A0",  # steel
    "#C7A94A",  # muted gold
    "#9A86B8",  # dusty violet
    "#B8788C",  # dusty rose
    "#5F9C8C",  # muted teal
    "#7E93BC",  # dusty lapis
    "#A0A68E",  # sage
]
