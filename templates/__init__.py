"""
Cubeon color templates.

Each color_<name>.py module defines one self-contained palette as a PALETTE
dict. They are plugins: nothing in the launcher's UI code knows about them.
`cubeon/color_templates.py` loads one and patches the design tokens in
cubeon.theme before any UI module binds them, which is wired up by the small
hook at the bottom of cubeon/__init__.py so you can simply run:

    python main.py --color1     # green    - true black + green (default identity)
    python main.py --color8     # autumn   - warm black + ember orange
    python main.py --color9     # spring   - plum black + blossom pink
    python main.py --color10    # winter   - cold black + ice blue
    python main.py --color11    # summer   - sun-warmed black + gold

Names work too: --color=green, --color autumn, etc.

A palette must provide the full base token set (BG, SURFACE, SURFACE_HI,
SURFACE_MAX, BORDER, BORDER_HI, TEXT, TEXT_DIM, TEXT_FAINT, ACCENT, ACCENT_HI,
ACCENT_DIM, ON_ACCENT, INFO, INFO_HI, INFO_DIM, ON_INFO, WARNING, ON_WARNING,
DANGER, DANGER_HI, ON_DANGER, CARD_FILL_HERO). The translucent derivatives
(CARD_FILL, CARD_BORDER, ROW_HOVER, ACCENT_TINT, ACCENT_TINT_HI) are computed
from the bases automatically - keep contrast in mind: TEXT clears AA on
SURFACE, TEXT_DIM stays readable, ON_ACCENT must contrast with ACCENT.
"""
