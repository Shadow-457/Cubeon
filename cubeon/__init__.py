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
# DEFAULT: with no --color argument, the "green" template (--color1) is
# applied, making it the app's default palette. An explicit --color<name> still
# overrides it. Set DEFAULT_COLOR_TEMPLATE to None to fall back to theme.py's
# built-in green tokens instead.
DEFAULT_COLOR_TEMPLATE = "green"


def _load_color_template():
    import sys

    argv = sys.argv[1:]
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
    # No explicit flag -> use the default template (carbon). Tools and tests
    # import cubeon without a --color arg too, but patching only the theme
    # palette is harmless there (they don't build the themed UI), and keeps
    # "what the app looks like by default" defined in one place.
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
        print(f"[cubeon] color template {name!r}: {ex}", file=sys.stderr)


_load_color_template()
