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
# SEASONS: when no --color is given, the palette is chosen by cubeon/seasonal.py
# from the user's timezone + today's date (autumn/spring/winter/summer), unless
# the user has turned the seasonal look off in Settings. An explicit --color
# always wins and is reported to the UI as "pinned" - it pauses the seasonal
# layer for that launch, because a palette can only be chosen while the package
# is being imported (see the module map: tokens are bound at import time).
#
# DEFAULT_COLOR_TEMPLATE is the fallback for (a) --color given, (b) the seasonal
# look turned off, and (c) a seasonal template that fails to load. Set it to
# None to fall back to theme.py's built-in green tokens instead.
DEFAULT_COLOR_TEMPLATE = "green"


def _diagnose(message: str) -> None:
    """Report a palette problem where it can actually be seen.

    A --windowed exe has no console, so a print() to stderr disappears - which
    is exactly why "the seasonal colours don't show on Windows" was invisible.
    On top of stderr, append a line to <CUBEON_HOME>/seasonal-debug.log so the
    failure is diagnosable on a user's machine instead of silent.
    """
    import sys
    print(message, file=sys.stderr)
    try:
        import datetime
        import os
        from cubeon.paths import CUBEON_HOME
        os.makedirs(CUBEON_HOME, exist_ok=True)
        with open(os.path.join(CUBEON_HOME, "seasonal-debug.log"), "a",
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

    name = _color_arg(sys.argv[1:])
    if name:
        # Pinned by the user for this launch: apply it and tell the seasonal
        # layer, so the badge/settings do not claim the season picked it.
        try:
            from cubeon import seasonal
            seasonal.note_palette_pinned(name)
        except Exception:      # noqa: BLE001 - a broken resolver must not pin-block
            pass
    else:
        # No explicit flag: ask the season. It reads config.json for the
        # seasonal on/off switch and any manual override, and caches its answer
        # for the UI (seasonal.current()). Any failure falls through to the
        # default template - the launcher must always start.
        try:
            from cubeon.seasonal import boot
            name, _info = boot()
        except Exception as ex:
            _diagnose(f"[cubeon] seasonal theme: {ex}")
            # boot() walks the same resolver the UI uses later, but if its
            # import-time call raised, retry it directly before giving up on
            # the season - falling straight to the default template is what
            # made a Windows palette failure look like "seasonal colours are
            # broken" while weather/pet (resolved later, successfully) worked.
            try:
                from cubeon.seasonal import theme_key_for
                name = theme_key_for()
            except Exception as ex2:
                _diagnose(f"[cubeon] seasonal fallback: {ex2}")
                name = None

    if not name:
        name = DEFAULT_COLOR_TEMPLATE
    if not name:
        return
    try:
        from cubeon.color_templates import apply_template
        apply_template(name)
    except SystemExit:
        raise
    except Exception as ex:
        _diagnose(f"[cubeon] color template {name!r}: {ex}")


_load_color_template()
