"""
Cubeon core package.

Split into focused modules so mod/loader logic isn't buried in one huge
file:

    paths.py        - all on-disk locations (MINECRAFT_DIR, PROFILES_DIR, ...)
    config.py        - launcher config load/save, offline auth, username validation
    versions.py      - installed/available Minecraft version listing + install
    mod_loaders.py   - Fabric/Quilt/Forge/NeoForge install + support checks
    mods.py           - per-profile mod folders, Modrinth search/download, sync-to-game
    skins.py          - custom skin upload/preview/apply
    profile.py        - launcher profile picture (avatar) management
    server.py         - local Minecraft server hosting
    launch.py         - building the launch command and starting the game process

launcher_core.py at the project root re-exports everything from this
package under its old names, so main.py / mods_tab.py / server_tab.py /
skin_tab.py don't need to change their imports.
"""


# --- Color-template plugin hook --------------------------------------------
# The ONLY non-plugin line in the template system. Runs while this package is
# being imported - i.e. before main.py's `from cubeon.theme import ...` binds
# any tokens - so `python main.py --color1` launches with that palette and
# every UI module simply receives the patched values.
#
# TEMPLATES: --color<name> picks a palette for this launch; without it the
# saved Color Studio palette or default green identity boots. Tokens are chosen while the package
# is being imported (see the module map: tokens are bound at import time).
#
# DEFAULT_COLOR_TEMPLATE is the fallback when --color is absent or its template
# fails to load. Set it to None to fall back to theme.py's built-in tokens.
DEFAULT_COLOR_TEMPLATE = "green"


def _diagnose(message: str) -> None:
    """Report a palette problem where it can actually be seen.

    A --windowed exe has no console, so a print() to stderr disappears - which
    is exactly why "the palette does not apply on Windows" was invisible.
    On top of stderr, append a line to <CUBEON_HOME>/palette-debug.log so the
    failure is diagnosable on a user's machine instead of silent.
    """
    import sys
    print(message, file=sys.stderr)
    try:
        import datetime
        import os
        from cubeon.paths import CUBEON_HOME
        os.makedirs(CUBEON_HOME, exist_ok=True)
        with open(os.path.join(CUBEON_HOME, "palette-debug.log"), "a",
                  encoding="utf-8") as fh:
            fh.write(f"{datetime.datetime.now().isoformat()} {message}\n")
    except Exception:      # noqa: BLE001 - diagnostics must never break startup
        pass


def _color_arg(argv):
    """Pulls an explicit --color[=]value out of argv, or None."""
    name = None
    for i, arg in enumerate(argv):
        if arg == "--color" and i + 1 < len(argv):
            name = argv[i + 1]
        elif arg.startswith("--color="):
            name = arg.split("=", 1)[1]
        elif arg.startswith("--color") and len(arg) > len("--color"):
            name = arg[len("--color"):]
        if name:
            break
    return name


def _load_color_template():
    import sys

    if '--cubeon-installer' in sys.argv:
        from cubeon.color_templates import apply_template
        apply_template('green')
        return

    explicit = _color_arg(sys.argv[1:])
    name = explicit

    if not name:
        name = DEFAULT_COLOR_TEMPLATE
    if not name:
        return
    try:
        from cubeon.color_templates import apply_template
        apply_template(name)
        if not explicit:
            from cubeon.config import load_config
            from cubeon.color_templates import (CUSTOM_PALETTE_KEY,
                                                normalize_custom_palette,
                                                apply_custom_palette)
            recipe = normalize_custom_palette(load_config().get(CUSTOM_PALETTE_KEY))
            if recipe is not None:
                apply_custom_palette(recipe)
    except SystemExit:
        raise
    except Exception as ex:
        _diagnose(f"[cubeon] color template {name!r}: {ex}")


_load_color_template()
