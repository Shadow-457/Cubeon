"""
--color9  "spring" - the seasonal look for March-May (northern).

Spring is the one season that could wreck the palette if it were taken
literally: "spring colours" usually means pastel everything, which is exactly
the rainbow the app's colour theory forbids. So it doesn't. The canvas stays a
true black with a faint plum cast (the last of winter's dark), and the single
chromatic voice is blossom pink - a colour that is unmistakably spring while
still being ONE voice, spent only on the things that do something.

The supporting semantic colours lean green (INFO = new leaf) so the spring
palette reads as "growing" rather than "Easter", and the pink never has to
share the spotlight with a second bright hue.

Contrast (AA-checked, see tools/test_seasonal.py): TEXT on SURFACE 16.4:1,
TEXT_DIM on SURFACE 8.5:1, ON_ACCENT on ACCENT 6.6:1.
"""

NAME = "spring"
DESCRIPTION = "spring - plum-black with a blossom accent (seasonal)"

PALETTE = {
    # Neutrals: true black with the faintest plum/blossom cast.
    "BG": "#060505",
    "SURFACE": "#100B0D",
    "SURFACE_HI": "#191013",
    "SURFACE_MAX": "#221519",
    "BORDER": "#2D1D22",
    "BORDER_HI": "#442E34",

    # Text: warm off-white with a rose dim tier.
    "TEXT": "#F9E7EC",
    "TEXT_DIM": "#C4A2AC",
    "TEXT_FAINT": "#806A72",

    # The hero: blossom. Bright without being pastel, so it still carries
    # emphasis the way the default green does.
    "ACCENT": "#E86A9A",
    "ACCENT_HI": "#F784AF",
    "ACCENT_DIM": "#B34B76",
    "ACCENT_DEEP": "#2E0B1C",
    "ON_ACCENT": "#160510",

    # Semantic: new leaf (info/download), hay gold (caution), redstone.
    "INFO": "#7FC48F",
    "INFO_HI": "#93D6A2",
    "INFO_DIM": "#2F5B3A",
    "ON_INFO": "#050505",
    "WARNING": "#DFAE44",
    "ON_WARNING": "#060505",
    "DANGER": "#CE5A4B",
    "DANGER_HI": "#DF6F5F",
    "ON_DANGER": "#060505",

    # The Play-tab hero panel: one flat step brighter than SURFACE.
    "CARD_FILL_HERO": "#150E10",
}

AVATAR_COLORS = [
    "#E86A9A",  # blossom (this season's accent)
    "#7FC48F",  # new leaf
    "#DFAE44",  # gold
    "#B57BD6",  # crocus
    "#6E9BE0",  # rain sky
    "#E0894A",  # robin breast
    "#3FB292",  # teal
    "#C98BB0",  # lilac blossom
]