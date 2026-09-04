"""
Every on-disk location Cubeon touches, in one place.

Keeping paths centralized (instead of scattered across mods/skins/server
modules) means there's exactly one definition of "where the profile mods
folder is" - which matters a lot here, since the #1 class of "mods just
don't load" bugs in the old code came from different functions building
that path slightly differently.
"""
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "Cubeon"


def _default_minecraft_dir() -> str:
    """Cubeon's own private game folder, ~/.cubeon_minecraft on every OS.

    This used to be the standard shared .minecraft (mll's
    get_minecraft_directory) so versions/mods/saves were shared with
    TLauncher, the vanilla launcher, and every mod loader installer. That
    sharing is exactly the collision this replaces: another launcher's
    install or update could wipe/replace folders Cubeon was actively using,
    and Cubeon's per-launch mods sync was stomping folders other launchers
    read. Now everything Minecraft-related Cubeon touches lives under one
    private root it owns outright.

    CUBEON_GAME_DIR, when set, wins over the default - the test suite uses
    it to point every cubeon module at a throwaway directory without
    touching a real HOME.
    """
    override = os.environ.get("CUBEON_GAME_DIR")
    if override:
        return override
    return str(Path.home() / ".cubeon_minecraft")


MINECRAFT_DIR = _default_minecraft_dir()
MODS_DIR = os.path.join(MINECRAFT_DIR, "mods")

# The visible global mod store: ONE physical, human-named copy of every mod
# jar Cubeon has ever installed, browsable by the user like any folder
# (sodium-fabric-0.9.2.jar, not a hash). Profiles link into it instead of
# holding their own bytes, so a mod already in the store is reused by every
# other profile/instance with no network and no duplicate download.
#
# This deliberately lives OUTSIDE MODS_DIR: the game folder's mods/ is wiped
# and rebuilt from the active profile at every launch, so the store must be a
# sibling the sync never touches.
GLOBAL_MODS_DIR = os.path.join(MINECRAFT_DIR, "global_mods")

# Resource packs and shaders are NOT per-version the way mods are: Minecraft
# reads them straight out of these two shared folders regardless of which
# version launches, and the game itself decides which are actually applied
# (via the in-game menu / options.txt). So unlike MODS_DIR there's no
# per-profile copy or launch-time sync step - installing here is all it takes
# for the game to see them. Shaders additionally need Iris or OptiFine present
# to have any effect, but the file still just lives here either way.
RESOURCEPACKS_DIR = os.path.join(MINECRAFT_DIR, "resourcepacks")
SHADERPACKS_DIR = os.path.join(MINECRAFT_DIR, "shaderpacks")

CUBEON_HOME = str(Path.home() / ".cubeon_launcher")
CONFIG_PATH = os.path.join(CUBEON_HOME, "config.json")
CACHE_DIR = os.path.join(CUBEON_HOME, "cache")

SKINS_DIR = os.path.join(CUBEON_HOME, "skins")
SKINS_META_PATH = os.path.join(SKINS_DIR, "skins.json")

CAPES_DIR = os.path.join(CUBEON_HOME, "capes")

# CustomSkinLoader (the client-side skin mod Cubeon installs) - these are the
# real on-disk locations from CSL's own docs. Note there is no "config/"
# component and the folder is capitalized; getting this wrong means CSL
# silently never sees the file, which is exactly the bug this replaced.
#   .minecraft/CustomSkinLoader/LocalSkin/{skins,capes,elytras}/<USERNAME>.png
# CSL also reads extra skin-source definitions out of ExtraList/, which is the
# supported way to register a skin server without rewriting the user's own
# CustomSkinLoader.json.
#
# IMPORTANT: LocalSkin textures are visible only to the local player - CSL's
# docs state "LocalSkin won't be seen by others". Making other players see a
# skin requires the network skin API (see agents/docs/phase1-skins-capes.md).
CSL_DIR = os.path.join(MINECRAFT_DIR, "CustomSkinLoader")
CSL_CONFIG_PATH = os.path.join(CSL_DIR, "CustomSkinLoader.json")
CSL_LOCAL_SKINS_DIR = os.path.join(CSL_DIR, "LocalSkin", "skins")
CSL_LOCAL_CAPES_DIR = os.path.join(CSL_DIR, "LocalSkin", "capes")
CSL_EXTRALIST_DIR = os.path.join(CSL_DIR, "ExtraList")

PFP_DIR = os.path.join(CUBEON_HOME, "profile")

SERVERS_DIR = os.path.join(CUBEON_HOME, "servers")

# Helper executables Cubeon downloads rather than bundles. Kept out of the
# app directory so a Cubeon reinstall or update doesn't force a re-download,
# and out of .minecraft so it's never mistaken for a mod.
BIN_DIR = os.path.join(CUBEON_HOME, "bin")

# Mod profiles - each (mc_version, loader) combo gets its own mods folder,
# so "installed" is always literally true for what's currently selected
# instead of being guessed/version-matched after the fact.
#
# Profiles now hold LINKS into GLOBAL_MODS_DIR (one real copy of each mod,
# shared by every profile that wants it), plus per-jar .cubeon.json sidecars.
# Jars that predate the store still sit here as plain files and keep working.
PROFILES_DIR = os.path.join(CUBEON_HOME, "mod_profiles")

MOD_META_SUFFIX = ".cubeon.json"
PROFILE_META_FILENAME = "_profile.json"


def ensure_disk_space(dest_dir: str, needed_bytes: int, what: str = "download") -> None:
    """Refuse a big download/copy when the destination drive is obviously too
    full, with a human sentence instead of a half-written file and a cryptic
    OSError deep in the install.

    A 10% margin is added on top of `needed_bytes` because archives extract,
    servers grow worlds, and "exactly enough" is how partial installs happen.
    Unmeasurable volumes (or a missing dir) stay silent - this is a guard,
    not a gate.
    """
    import shutil
    try:
        directory = dest_dir or os.getcwd()
        if not os.path.isdir(directory):
            directory = os.path.dirname(directory) or os.getcwd()
        free = shutil.disk_usage(directory).free
    except OSError:
        return
    needed = int(needed_bytes * 1.1) + 64 * 1024 * 1024
    if free < needed:
        mb = lambda b: max(1, b // (1024 * 1024))
        raise RuntimeError(
            f"Not enough disk space for the {what}: it needs about "
            f"{mb(needed_bytes)} MB, but only {mb(free)} MB is free. "
            f"Free up some space and try again.")


def ensure_dirs() -> None:
    """Creates every directory Cubeon needs up front, so no module has to
    remember to os.makedirs() its own corner before first use.

    Never raises. This runs at import time, which means an exception here
    happens before there is any window to show it in - the user would get a
    console traceback and a launcher that doesn't open, over something as
    recoverable as one unwritable folder. Each feature already fails with its
    own specific message when its directory is missing, and that message is
    vastly more useful than a stack trace at startup.
    """
    for d in (
        MINECRAFT_DIR, MODS_DIR, GLOBAL_MODS_DIR, CUBEON_HOME, CACHE_DIR, SKINS_DIR,
        CAPES_DIR, PFP_DIR, SERVERS_DIR, PROFILES_DIR, BIN_DIR,
        RESOURCEPACKS_DIR, SHADERPACKS_DIR,
    ):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as ex:
            log.warning("couldn't create %s (%s) - features needing it will "
                        "report their own error", d, ex.__class__.__name__)


ensure_dirs()
