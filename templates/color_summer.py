"""
--color11  "summer" - the seasonal look for June-August (northern).

High sun on dark leaves: the canvas is a black with a deep green cast (so it
belongs to the same family as the default identity rather than fighting it), and
the single chromatic voice is sun-gold - warm, bright, and the only thing that
glows. It is deliberately NOT a beach palette: no turquoise slabs, no coral
everywhere. The cool voice is one pond-teal, spent on downloads and
informational actions so "go get it" still reads as a different kind of action
than "play".

Also stands in for the DRY season in the tropics (see cubeon/seasonal.py), which
is why the label in the UI can read "Dry season" - the palette itself is
unchanged.

Contrast (AA-checked, see tools/test_seasonal.py): TEXT on SURFACE 17.3:1,
TEXT_DIM on SURFACE 9.5:1, ON_ACCENT on ACCENT 9.7:1.
"""

NAME = "summer"
DESCRIPTION = "summer - deep-leaf black with a sun-gold accent (seasonal)"

PALETTE = {
    # Neutrals: true black with a deep green shade cast, never grey.
    "BG": "#050706",
    "SURFACE": "#0A100E",
    "SURFACE_HI": "#111A17",
    "SURFACE_MAX": "#17241F",
    "BORDER": "#1F2E28",
    "BORDER_HI": "#33493F",

    # Text: sun-bleached off-white.
    "TEXT": "#EAF6E9",
    "TEXT_DIM": "#A5BCA6",
    "TEXT_FAINT": "#6C8270",

    # The hero: sun gold. AAA on its own foreground, so the Play button is
    # unmistakable even in daylight.
    "ACCENT": "#E4B23C",
    "ACCENT_HI": "#F4C95A",
    "ACCENT_DIM": "#A87C1E",
    "ACCENT_DEEP": "#2B2005",
    "ON_ACCENT": "#141002",

    # Semantic: pond teal (cool counterweight), clay orange caution, redstone.
    "INFO": "#4FBFAE",
    "INFO_HI": "#66D2C1",
    "INFO_DIM": "#20574F",
    "ON_INFO": "#050505",
    "WARNING": "#E0894A",
    "ON_WARNING": "#050706",
    "DANGER": "#CE5A4B",
    "DANGER_HI": "#DF6F5F",
    "ON_DANGER": "#050706",

    # The Play-tab hero panel: one flat step brighter than SURFACE.
    "CARD_FILL_HERO": "#0E1512",
}

AVATAR_COLORS = [
    "#E4B23C",  # sun gold (this season's accent)
    "#4FBFAE",  # pond teal
    "#E0894A",  # clay
    "#8FBF4A",  # leaf
    "#6E9BE0",  # sky
    "#D96E93",  # hibiscus
    "#3FB292",  # jungle
    "#C4A24A",  # dry grass
]