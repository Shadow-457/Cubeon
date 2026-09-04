"""
Color-template loader: applies a palette from templates/ onto cubeon.theme
at startup, before any UI module binds the design tokens.

This is the entire mechanism - there is no other colour plumbing:

    python main.py --color1        # green    (70% black / green on main things)
    python main.py --color2        # obsidian (graphite monochrome)
    python main.py --color3        # lapis    (navy + lapis blue)

`--color=<name>` / `--color <name>` work too, as does `--color list`.
The hook that calls apply_template() lives at the bottom of cubeon/__init__.py,
which runs before main.py's `from cubeon.theme import ...` executes - so the
patched values are what every tab builder receives. Nothing in main.py, the
tab modules, or theme.py knows templates exist.

How patching works: cubeon.theme is imported once, then every palette key is
setattr()-ed onto the module and the THEME dict (consumed by tab builders via
**THEME) is updated in place. Functions inside theme.py (apply_page_theme,
section_label, ...) read module globals at call time, so they pick the patch
up automatically. The translucent derivatives (CARD_FILL, ACCENT_TINT, ...) are
derived here from the palette's bases so a template only declares raw colours.

Known limitation: one literal in main.py (the loader-switch thumb, "#32431D")
is a dark olive pill hardcoded outside the token system. On non-green
templates it still reads as a dark segmented thumb - subtle, but not
recoloured. Fixing it means touching main.py, which templates deliberately
never do.
"""
import importlib

# Imported lazily inside functions where possible; cubeon.theme itself is
# imported at module scope because patching it is this module's whole job.
from cubeon import theme as _theme


# Registry: template key -> module path, plus the numeric CLI aliases
# (--color1/2/3). Adding a template = drop templates/color_<key>.py and
# register it here. That's it.
TEMPLATE_MODULES = {
    "green": "templates.color_green",
    "obsidian": "templates.color_obsidian",
    "lapis": "templates.color_lapis",
    "redstone": "templates.color_redstone",
    "carbon": "templates.color_carbon",
    "amethyst": "templates.color_amethyst",
    "diamond": "templates.color_diamond",
}
ALIASES = {
    "1": "green", "2": "obsidian", "3": "lapis", "4": "redstone",
    "5": "carbon", "6": "amethyst", "7": "diamond",
}
ALIAS_OF = {
    "green": "1", "obsidian": "2", "lapis": "3", "redstone": "4",
    "carbon": "5", "amethyst": "6", "diamond": "7",
}

# Keys a palette must define (everything else is derived).
REQUIRED_KEYS = (
    "BG", "SURFACE", "SURFACE_HI", "SURFACE_MAX", "BORDER", "BORDER_HI",
    "TEXT", "TEXT_DIM", "TEXT_FAINT",
    "ACCENT", "ACCENT_HI", "ACCENT_DIM", "ON_ACCENT",
    "INFO", "INFO_HI", "INFO_DIM", "ON_INFO",
    "WARNING", "ON_WARNING",
    "DANGER", "DANGER_HI", "ON_DANGER",
    "CARD_FILL_HERO",
)


def resolve(name: str) -> str:
    """Maps a CLI argument ("1", "green", "OBSIDIAN", ...) to a template key."""
    key = str(name).strip().lower()
    key = ALIASES.get(key, key)
    if key == "list":
        print_templates()
        raise SystemExit(0)
    if key not in TEMPLATE_MODULES:
        raise ValueError(
            f"unknown color template {name!r} - known: "
            + ", ".join(f"{k} (--color{ALIAS_OF[k]})" for k in TEMPLATE_MODULES)
        )
    return key


def _derive(palette: dict) -> dict:
    """Fills in the translucent tokens the theme system expects, computed
    from the template's own bases (same fractions as cubeon.theme)."""
    import flet as ft

    palette.setdefault("CARD_FILL", ft.Colors.with_opacity(0.55, palette["SURFACE"]))
    palette.setdefault("CARD_BORDER", ft.Colors.with_opacity(0.55, palette["BORDER"]))
    palette.setdefault("ROW_HOVER", ft.Colors.with_opacity(0.65, palette["SURFACE_HI"]))
    palette.setdefault("ACCENT_TINT", ft.Colors.with_opacity(0.14, palette["ACCENT"]))
    palette.setdefault("ACCENT_TINT_HI", ft.Colors.with_opacity(0.24, palette["ACCENT"]))
    return palette


def apply_template(name: str) -> str:
    """Loads templates/color_<key>.py and patches cubeon.theme with it.
    Returns the resolved template key. Raises for unknown/broken templates -
    the caller (the __init__ hook) reports and continues with defaults."""
    key = resolve(name)
    mod = importlib.import_module(TEMPLATE_MODULES[key])
    palette = _derive(dict(getattr(mod, "PALETTE", {})))

    missing = [k for k in REQUIRED_KEYS if k not in palette]
    if missing:
        raise ValueError(f"template {key!r} is missing tokens: {', '.join(missing)}")

    # 1) Module attributes - everything that reads cubeon.theme.<TOKEN> at
    #    call time (apply_page_theme, the glass helpers, main.py's imports).
    for attr, value in palette.items():
        setattr(_theme, attr, value)
    _theme.SUCCESS = _theme.ACCENT  # semantic alias, kept in sync

    # 2) The THEME dict - tab builders receive **THEME at call time, so the
    #    dict's *values* must be patched in place (main.py holds this exact
    #    object from its own import).
    for k in _theme.THEME:
        if k in palette:
            _theme.THEME[k] = palette[k]

    # 3) Optional per-template avatar palette (first entry should be the
    #    template's accent so a lone friend still reads as this theme).
    avatars = getattr(mod, "AVATAR_COLORS", None)
    if avatars:
        _theme.AVATAR_COLORS[:] = list(avatars)

    return key


def print_templates():
    """Lists the available templates with their accent colours."""
    print("available color templates:")
    for key, path in TEMPLATE_MODULES.items():
        try:
            mod = importlib.import_module(path)
            desc = getattr(mod, "DESCRIPTION", "")
            accent = mod.PALETTE.get("ACCENT", "?")
            alias = ALIAS_OF.get(key, "-")
            print(f"  --color{alias}  {key:<9} accent {accent}  {desc}")
        except Exception as ex:
            print(f"  --color{ALIAS_OF.get(key, '-')}  {key:<9} <broken: {ex}>")


if __name__ == "__main__":
    # Standalone inspection: python3 -m cubeon.color_templates
    print_templates()
