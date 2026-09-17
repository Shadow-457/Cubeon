"""
--color8  "autumn" - the seasonal look for September-November (northern).

WHY IT LOOKS LIKE THIS

Autumn's own colours already follow the launcher's colour discipline, which is
why it needs no compromises: a deciduous tree is a near-black silhouette with a
single blazing chromatic voice against it. So the canvas stays a true black
carrying a brown/amber cast (like every Cubeon surface, it is *not* grey - it is
black with warmth), and one ember-orange accent does all the talking. The
"colorful" part of autumn isn't three hues fighting for attention; it's that
orange, spent generously on the things that DO something - Play, the active tab,
downloads, links - against a much warmer darkness than the usual black-green.

Not a rainbow, on purpose: 60% warm black, 30% brown-cast structure, 10%
orange. The secondary semantic colours are pulled from Minecraft's autumn blocks
so they sit in the palette instead of on top of it (INFO = a deep pond/teal for
downloads, WARNING = hay gold, DANGER = redstone, unchanged in spirit from the
default identity).

Contrast (WCAG, computed with the same formula as the test in
tools/test_seasonal.py): TEXT on SURFACE 15.8:1, TEXT_DIM on SURFACE 8.0:1,
ON_ACCENT on ACCENT 6.4:1 - all above AA 4.5:1. TEXT_FAINT is hints-only, as
everywhere else in the app.
"""

NAME = "autumn"
DESCRIPTION = "autumn - warm near-black with a single ember-orange accent (seasonal)"

PALETTE = {
    # Neutrals: true black, warmed with a brown/amber cast on elevation.
    "BG": "#0A0705",
    "SURFACE": "#120D08",
    "SURFACE_HI": "#1B130A",
    "SURFACE_MAX": "#231808",
    "BORDER": "#2F2113",
    "BORDER_HI": "#463122",

    # Text: parchment, not white - carries the warmth without going beige.
    "TEXT": "#F7E6D2",
    "TEXT_DIM": "#C1A184",
    "TEXT_FAINT": "#7E6B58",

    # The hero: ember orange. Primary action, brighter hover, deeper
    # saturated secondary for selected/pressed fills.
    "ACCENT": "#E0762A",
    "ACCENT_HI": "#F79A3C",
    "ACCENT_DIM": "#A8531A",
    "ACCENT_DEEP": "#2B1204",
    "ON_ACCENT": "#140801",

    # Semantic: teal pond (download/info) is the one cool voice and therefore
    # POPS against the orange - same trick the default identity plays with
    # diamond cyan, but rotated to autumn's complement.
    "INFO": "#5FA9A0",
    "INFO_HI": "#74BDB3",
    "INFO_DIM": "#24504B",
    "ON_INFO": "#050505",
    "WARNING": "#E6B23C",       # hay gold
    "ON_WARNING": "#0A0705",
    "DANGER": "#C4553F",        # redstone, warmed
    "DANGER_HI": "#D96E58",
    "ON_DANGER": "#0A0705",

    # The Play-tab hero panel: one flat step brighter than SURFACE.
    "CARD_FILL_HERO": "#170F08",
}

AVATAR_COLORS = [
    "#E0762A",  # ember orange (this season's accent)
    "#5FA9A0",  # pond teal
    "#E6B23C",  # hay gold
    "#C4553F",  # redstone
    "#9C6B4A",  # bark
    "#D98E5A",  # maple
    "#8FA85C",  # moss
    "#B57BD6",  # amethyst
]