"""
--color3  "lapis" - deep navy + lapis blue.

The same dark-launcher discipline as the default, re-tuned to Minecraft's
lapis ore instead of grass: blue-slate surfaces, electric lapis accent.
Cyan stays the secondary (download) colour; everything structural cools down
with it, so it reads as one world rather than a re-skin.
"""

NAME = "lapis"
DESCRIPTION = "deep navy surfaces + lapis blue accent"

PALETTE = {
    # Neutrals: blue-slate ramp.
    "BG": "#0A0D13",
    "SURFACE": "#111620",
    "SURFACE_HI": "#1A212D",
    "SURFACE_MAX": "#242D3C",
    "BORDER": "#273041",
    "BORDER_HI": "#3D4A60",

    # Text
    "TEXT": "#E8EBF1",
    "TEXT_DIM": "#9AA5B6",
    "TEXT_FAINT": "#667186",

    # Hero: lapis blue.
    "ACCENT": "#5E8BFF",
    "ACCENT_HI": "#7CA4FF",
    "ACCENT_DIM": "#2D4B90",
    "ON_ACCENT": "#0A0D13",

    # Semantic
    "INFO": "#4FC3D9",
    "INFO_HI": "#70D3E5",
    "INFO_DIM": "#205662",
    "ON_INFO": "#0A0D13",
    "WARNING": "#E0B04C",
    "ON_WARNING": "#0A0D13",
    "DANGER": "#E06555",
    "DANGER_HI": "#EB7A6B",
    "ON_DANGER": "#0A0D13",

    "CARD_FILL_HERO": "#141A26",
}

AVATAR_COLORS = [
    "#5E8BFF",  # lapis
    "#4FC3D9",  # cyan
    "#E0B04C",  # gold
    "#B57BD6",  # amethyst
    "#E06B93",  # pink
    "#3FB292",  # teal
    "#E0894A",  # copper
    "#9FB0C9",  # silver
]
