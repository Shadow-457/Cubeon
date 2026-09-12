"""
Cubeon color templates.

Each color_<name>.py module defines one self-contained palette as a PALETTE
dict. They are plugins: nothing in the launcher's UI code knows about them.
`cubeon/color_templates.py` loads one and patches the design tokens in
cubeon.theme before any UI module binds them, which is wired up by the small
hook at the bottom of cubeon/__init__.py so you can simply run:

    python main.py --color1     # green    - true black + green (default identity)
    python main.py --color2     # obsidian - graphite monochrome, off-white accent
    python main.py --color3     # lapis    - deep navy + lapis blue
    python main.py --color4     # redstone - red-tinted dark + redstone accent
    python main.py --color5     # carbon   - 90% black, green rationed to essentials
    python main.py --color6     # amethyst - violet-dark + amethyst accent
    python main.py --color7     # diamond  - cool slate + diamond-cyan accent

Names work too: --color=green, --color obsidian, etc.

A palette must provide the full base token set (BG, SURFACE, SURFACE_HI,
SURFACE_MAX, BORDER, BORDER_HI, TEXT, TEXT_DIM, TEXT_FAINT, ACCENT, ACCENT_HI,
ACCENT_DIM, ON_ACCENT, INFO, INFO_HI, INFO_DIM, ON_INFO, WARNING, ON_WARNING,
DANGER, DANGER_HI, ON_DANGER, CARD_FILL_HERO). The translucent derivatives
(CARD_FILL, CARD_BORDER, ROW_HOVER, ACCENT_TINT, ACCENT_TINT_HI) are computed
from the bases automatically - keep contrast in mind: TEXT clears AA on
SURFACE, TEXT_DIM stays readable, ON_ACCENT must contrast with ACCENT.
"""
