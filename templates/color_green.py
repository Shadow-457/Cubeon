"""
--color1  "green" - neutral black, FastClient-style, with the orange swapped to green.

Neutrals are copied from the reference launcher: a true neutral black canvas
(#0B0B0B), flat neutral-grey cards (#161616) and hairline borders (#262626) with
no colour cast at all. The only chromatic voice is the accent, the same
saturation and lightness as the reference's orange but turned to green. It lives
on the things that DO something: Play, the active nav item, downloads, links.
"""

NAME = "green"
DESCRIPTION = "neutral black with a single green accent (FastClient-style)"

PALETTE = {
    # Neutrals: copied from the reference - pure neutral greys, no colour cast.
    "BG": "#0B0B0B",
    "SURFACE": "#121212",
    "SURFACE_HI": "#161616",
    "SURFACE_MAX": "#222222",
    "BORDER": "#262626",
    "BORDER_HI": "#3A3D40",

    # Text: white, then neutral dim and faint tiers.
    "TEXT": "#FFFFFF",
    "TEXT_DIM": "#A0A0A0",
    "TEXT_FAINT": "#6A6D72",

    # Hero: the reference orange turned to green (same saturation and
    # lightness): primary, lighter hover, darker pressed, deep selected fill.
    "ACCENT": "#25A530",
    "ACCENT_HI": "#40C94C",
    "ACCENT_DIM": "#1E8D27",
    "ACCENT_DEEP": "#0B2B0E",
    "ON_ACCENT": "#06120A",

    # Semantic: unchanged from before.
    "INFO": "#78B6B7",       # misty cyan - the one sanctioned secondary
    "INFO_HI": "#90CAC8",
    "INFO_DIM": "#294A47",
    "ON_INFO": "#0B0B0B",
    "WARNING": "#D9B46E",    # soft sand
    "ON_WARNING": "#0B0B0B",
    "DANGER": "#D07466",     # dusty clay
    "DANGER_HI": "#DF887F",
    "ON_DANGER": "#0B0B0B",

    # The Play-tab hero panel: one gentle step brighter than SURFACE.
    "CARD_FILL_HERO": "#0E0E0E",
}

AVATAR_COLORS = [
    "#82BF68",  # sage
    "#78B6B7",  # misty cyan
    "#D9B46E",  # sand
    "#A683C8",  # dusty violet
    "#D2819D",  # dusty rose
    "#70B887",  # soft teal
    "#D69967",  # terracotta
    "#81A3D1",  # slate blue
]
