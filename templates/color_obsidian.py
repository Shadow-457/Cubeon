"""
--color2  "obsidian" - graphite monochrome.

No hue anywhere in the structure: pure graphite surfaces, off-white accent.
The launcher reads like a professional tool - the Play button becomes a
bright near-white slab, active states are light washes. Semantic colours
(cyan/gold/redstone) survive only where they mean something (download,
warning, delete).
"""

NAME = "obsidian"
DESCRIPTION = "graphite monochrome - off-white accent, zero hue in the structure"

PALETTE = {
    # Neutrals: true graphite, no undertone.
    "BG": "#0C0C0D",
    "SURFACE": "#141416",
    "SURFACE_HI": "#1D1D20",
    "SURFACE_MAX": "#27272B",
    "BORDER": "#29292E",
    "BORDER_HI": "#404048",

    # Text
    "TEXT": "#EDEDEE",
    "TEXT_DIM": "#9C9CA4",
    "TEXT_FAINT": "#6B6B73",

    # Hero: light instead of coloured - the accent IS brightness.
    "ACCENT": "#E4E6E1",
    "ACCENT_HI": "#F6F7F4",
    "ACCENT_DIM": "#8F918C",
    "ON_ACCENT": "#101011",

    # Semantic (kept, because meaning isn't decoration)
    "INFO": "#93B9C6",
    "INFO_HI": "#A9CBD6",
    "INFO_DIM": "#3C5560",
    "ON_INFO": "#0C0C0D",
    "WARNING": "#D3AD57",
    "ON_WARNING": "#0C0C0D",
    "DANGER": "#CB6154",
    "DANGER_HI": "#DC7566",
    "ON_DANGER": "#0C0C0D",

    "CARD_FILL_HERO": "#1B1B1E",
}

AVATAR_COLORS = [
    "#E4E6E1",  # off-white (the "hero" user colour)
    "#93B9C6",  # steel cyan
    "#D3AD57",  # brass
    "#A48BD0",  # muted amethyst
    "#C97B93",  # dusty pink
    "#7FAFA3",  # sage teal
    "#C99270",  # tan
    "#8C9BC0",  # slate blue
]
