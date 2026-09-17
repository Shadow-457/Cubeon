"""
--color10  "winter" - the seasonal look for December-February (northern).

Cold, still, and bright. Where autumn warms the blacks, winter freezes them: the
canvas is a blue-black with a distinctly cool cast, and the single chromatic
voice is ice-blue - the colour snow throws back at a clear sky. Everything
structural is blue-grey so the whole launcher reads as one temperature.

Same 60/30/10 discipline as every Cubeon palette: the accent is the only thing
allowed to be bright, and it lives on primary actions and the active tab. The
secondary semantic colours are re-tuned to the cold surfaces (INFO = a violet
that reads as "aurora"/night-sky next to the ice blue, WARNING = a pale straw
that stays legible without going warm-orange and confusing the accent).

Contrast (AA-checked, see tools/test_seasonal.py): TEXT on SURFACE 15.7:1,
TEXT_DIM on SURFACE 7.9:1, ON_ACCENT on ACCENT 8.4:1.
"""

NAME = "winter"
DESCRIPTION = "winter - blue-black with an ice accent (seasonal)"

PALETTE = {
    # Neutrals: blue-black, never grey - each step keeps the cold cast.
    "BG": "#04060A",
    "SURFACE": "#0A0F16",
    "SURFACE_HI": "#111924",
    "SURFACE_MAX": "#17222F",
    "BORDER": "#1F2C3C",
    "BORDER_HI": "#33465C",

    # Text: snow light, with a cold dim tier.
    "TEXT": "#DCEAF6",
    "TEXT_DIM": "#93A9BF",
    "TEXT_FAINT": "#61748A",

    # The hero: ice. A frozen version of the green identity - same job, same
    # single-voice discipline, opposite temperature.
    "ACCENT": "#5FB6E0",
    "ACCENT_HI": "#7CCBEE",
    "ACCENT_DIM": "#2E7FA8",
    "ACCENT_DEEP": "#0A2233",
    "ON_ACCENT": "#03121B",

    # Semantic: night-sky violet (info/download) against the ice; pale straw
    # caution; redstone kept for destructive actions exactly as elsewhere.
    "INFO": "#8F7FE0",
    "INFO_HI": "#A695F0",
    "INFO_DIM": "#3B3270",
    "ON_INFO": "#050505",
    "WARNING": "#DFC46A",
    "ON_WARNING": "#04060A",
    "DANGER": "#CE5A4B",
    "DANGER_HI": "#DF6F5F",
    "ON_DANGER": "#04060A",

    # The Play-tab hero panel: one flat step brighter than SURFACE.
    "CARD_FILL_HERO": "#080D13",
}

AVATAR_COLORS = [
    "#5FB6E0",  # ice (this season's accent)
    "#8F7FE0",  # night-sky violet
    "#DFC46A",  # pale straw
    "#7FC4A8",  # glazed teal
    "#C97F9E",  # winter berry
    "#6E9BE0",  # frost lapis
    "#AEBCCC",  # snow shadow
    "#9C7BD6",  # deep aurora
]