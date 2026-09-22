"""
Local server hosting - Paper only (vanilla hosting was removed 2026-08-26).
Installs a Paper server jar for a version - downloaded from papermc.io OR
copied from a jar the user already has on disk (see find_local_paper_jar /
install_server's local_jar_path) - then manages its
server.properties/eula.txt, plugins, and start/stop/talk to the process.
Kept entirely separate from the client install (own folder per version)
since a server jar and a client jar are different downloads.

Paper (https://papermc.io) adds a plugin API on top of vanilla, and every
other part of Cubeon's server story depends on it: plugins are just .jar
files dropped in <server_dir>/plugins/, the plugin manager reuses
Modrinth's API (same one mods.py already talks to) scoped to
project_type:plugin, and the Minekube Connect tunnel (see minekube.py)
is itself a Paper plugin - so vanilla support only ever meant a second,
less capable code path.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import zipfile
import zlib

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")
# minecraft_launcher_lib costs ~116ms to import (it pulls in requests);
# nothing here needs it until the user actually installs/launches, so it
# is imported on first use. `mll.<anything>` is unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
mll = LazyModule("minecraft_launcher_lib")

from .paths import SERVERS_DIR, APP_NAME
from .mod_loaders import SUPPORTED_LOADERS  # noqa: F401 (kept for callers that import it from here)
from .launch import find_java, find_java_for_version, java_major_version, required_java_major
from .mods import modrinth_search_index, rank_search_hits
from . import local_cache
from . import net

MODRINTH_API = "https://api.modrinth.com/v2"
MODRINTH_HEADERS = {"User-Agent": f"Cubeon/{APP_NAME.lower()}/1.0"}


SERVER_TYPE_PAPER = "paper"
SERVER_TYPES = {
    SERVER_TYPE_PAPER: "Paper (plugins)",
}
PLUGIN_META_SUFFIX = ".cubeon.json"

# The Minekube Connect plugin is Cubeon's own infrastructure - the whole
# "start server = shareable" design depends on it being present (see
# minekube.py). It is installed automatically at server start, so a user
# deleting it from the Plugins list would silently kill public addresses
# until they noticed. Protected: the Plugins UI hides its controls and the
# core refuses to delete/disable it even if asked directly.
CONNECT_PLUGIN_NAME = "connect-spigot.jar"
PROTECTED_PLUGINS = {CONNECT_PLUGIN_NAME, "CubeonGate.jar"}

# AuthMe (AuthMeReloaded) is the other managed default: Cubeon servers run
# online-mode=false, which means anyone can connect claiming any username.
# AuthMe adds the /register //login layer that makes offline servers safe
# to share publicly. Auto-installed at server start alongside Connect and
# protected the same way - a deleted AuthMe on a public cracked server is
# an account-takeover waiting to happen, not a performance tweak.
DEFAULT_PLUGIN_SLUGS = ["authmereloaded"]
_PROTECTED_STEM_PREFIXES = ("authme", "cubeongate")


def is_protected_plugin_stem(stem: str) -> bool:
    """Whether a plugin jar's name (without .jar/.jar.disabled) belongs to
    a Cubeon-managed plugin. Exact names for the ones we download under a
    known filename, plus prefixes for managed plugins whose jar name
    carries a version (AuthMe-6.0.0-Paper.jar)."""
    low = (stem or "").lower()
    if f"{low}.jar" in PROTECTED_PLUGINS:
        return True
    return any(low.startswith(p) for p in _PROTECTED_STEM_PREFIXES)


def ensure_default_plugins(version_id: str, status_cb=None) -> dict:
    """Installs the managed default plugins (AuthMe) the server doesn't
    already have. Idempotent and version-scoped: prefers a build tagged
    for the server's MC version, falls back to the latest published build
    (Paper plugins are broadly version-tolerant). Never raises for one
    plugin failing - a dead mirror must not block a server start.

    Returns {"installed": [names], "present": [names], "failed": [(name, reason)]}."""
    result = {"installed": [], "present": [], "failed": [], "tuned": []}
    plugins_dir = get_plugins_dir(version_id)

    have = {p["filename"].lower() for p in list_plugins(version_id)}
    for slug in DEFAULT_PLUGIN_SLUGS:
        already = any(name.startswith("authme") for name in have)
        if already:
            result["present"].append(slug)
            continue
        try:
            if status_cb:
                status_cb("Installing AuthMe (login security)...")
            info = get_plugin_download(slug, mc_version=version_id) \
                or get_plugin_download(slug)
            if not info:
                result["failed"].append((slug, "no build found"))
                continue
            download_plugin(version_id, info["url"], info["filename"], slug=slug)
            result["installed"].append(info["filename"])
        except Exception as ex:
            result["failed"].append((slug, f"{type(ex).__name__}: {ex}"))

    for change in _tune_authme_config(version_id):
        result["tuned"].append(change)
    return result


# AuthMe's stock timings are built for big public servers and feel harsh on
# a friends-and-family one: 60 seconds to type /login before the kick, and
# no session persistence, so EVERY rejoin needs a full /login. Cubeon
# relaxes exactly those dials, every start, surgically - three keys in
# AuthMe's own config.yml, nothing else touched:
#   sessions.enabled  true          rejoining within the session window
#                                   skips /login entirely
#   sessions.timeout  10 (minutes)  how long a login lasts
#   restrictions.timeout 300 (secs) time to type /login before the kick
#   restrictions.maxRegPerIp 0      0 = unlimited registrations per IP.
#                                   REQUIRED for Cubeon hosts: every player
#                                   joining through the Minekube Connect
#                                   tunnel arrives from the SAME apparent
#                                   IP (the tunnel's local connection, e.g.
#                                   127.0.0.1), so AuthMe's stock limit of
#                                   one registration per IP makes the FIRST
#                                   registrant block every friend after
#                                   them with "exceeded the maximum number
#                                   of registrations (1/1 ...) for your
#                                   connection". The per-IP dial is
#                                   meaningless on a tunneled server; the
#                                   password layer itself is still what
#                                   protects accounts.
AUTHME_TUNING = {
    "sessions": {"enabled": "true", "timeout": "10"},
    "restrictions": {"timeout": "300", "maxRegPerIp": "0"},
}


def _tune_authme_config(version_id: str) -> list[str]:
    """Applies AUTHME_TUNING to plugins/AuthMe/config.yml.

    AuthMe generates its config on FIRST boot, so on a brand-new install
    there's nothing to patch yet - this converges on the second start.

    Section tracking uses an indent stack rather than a single "current
    section": AuthMe 6.x (ConfigMe) writes sections at indent 4
    (`settings:` 0, `restrictions:` 4, keys 8) while older builds wrote
    everything at 2. A header is any line ending in ":" (no value); the
    innermost active header names the section, and a `timeout:`/`enabled:`
    key is only patched when that section is in AUTHME_TUNING - so the
    duplicate `timeout:` under both `sessions` and `restrictions` still
    each gets its own value. Never creates the file (a partial AuthMe
    config is worse than none) and never raises - a missing/unreadable
    config just means defaults.
    """
    path = os.path.join(get_plugins_dir(version_id), "AuthMe", "config.yml")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []

    changes = []
    stack: list[tuple[int, str]] = []  # (indent, section name) of open headers
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stripped.endswith(":"):
            stack.append((indent, stripped[:-1].strip()))
            continue
        key = stripped.split(":", 1)[0].strip()
        if not stack:
            continue
        section = stack[-1][1]
        tuning = AUTHME_TUNING.get(section, {})
        if key in tuning:
            new_line = f"{line[:indent]}{key}: {tuning[key]}"
            if line != new_line:
                lines[i] = new_line
                changes.append(f"{section}.{key} = {tuning[key]}")

    if changes:
        try:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                                       prefix=".authme-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, path)
        except OSError:
            return []
    return changes

# A handful of well-known, safe-default plugins shown before the user
# searches anything - mirrors RECOMMENDED_MOD_SLUGS in mods.py but scoped
# to Paper plugins. All are performance/QoL picks that work standalone.
RECOMMENDED_PLUGIN_SLUGS = ["luckperms", "essentialsx", "viaversion", "vault", "worldedit"]

# Curated LOW-PING picks (verified against Modrinth 2026-08-25: every slug
# here ships real paper/bukkit loader builds - unlike e.g. 'spark', whose
# Modrinth project only covers fabric/forge loaders and would 404 our
# paper-scoped download lookup). Each targets a different lag source:
#   lagfixer     - general tick/hop-perf tuning, entity & tile-entity caps
#   chunky       - pre-generates chunks so players never stall on generation
#   farmcontrol  - throttles runaway farms (the #1 cause of entity lag)
#   entityonview - server-side entity culling: entities no player can see
#                  (empty rooms, behind-wall mobs) stop being ticked/tracked
#                  per player - verified single build covers 1.12-1.20.4 and
#                  Paper plugins are broadly version-tolerant (added
#                  2026-08-26 by user request for entity culling)
LOW_PING_PLUGIN_SLUGS = ["lagfixer", "chunky", "farmcontrol", "entityonview"]

# Server-side distance caps. These live in server.properties, and Minecraft
# ENFORCES them per-player server-side: a client can set its own render
# distance to 32 chunks, but the server never sends chunks beyond
# view-distance, and nothing beyond simulation-distance gets ticked. So
# capping these two values IS how you cap every player at once.
VIEW_DISTANCE_RANGE = (2, 32)
SIMULATION_DISTANCE_RANGE = (3, 32)


def clamp_distance(value, bounds, default: int) -> int:
    """Coerce user input into a valid chunk distance. Anything unparseable
    falls back to the default rather than poisoning server.properties with
    a value the jar would reject at boot."""
    lo, hi = bounds
    try:
        v = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))

# High-ping / low-latency preset. Applied on top of whatever the user has
# already configured - never silently overwrites gameplay settings like
# difficulty or whitelist. Values chosen conservatively (still fully
# playable), not maxed-out, since the goal is smoother laggy connections,
# not turning the server into a blank plain.
#
# BUG FIXED 2026-08-22: two of the five original keys here,
# network-compression-threshold=256 and max-tick-time=60000, are *already*
# vanilla's own defaults (verified against a fresh server.properties) - so
# enabling "smooth mode" was silently writing the same value already on
# disk for those two, doing nothing. That's why the toggle felt like it
# "wasn't doing much": only 2 of 5 settings ever actually changed anything
# (view-distance, simulation-distance). Replaced the two no-ops with
# settings that genuinely reduce network chatter for a weak connection:
#   - network-compression-threshold lowered to 64 (compress more traffic,
#     not the vanilla-equal 256) - the actual lever for a slow/lossy link.
#   - max-tick-time raised further to 120000 so a slow client's catch-up
#     doesn't trip the watchdog and force-kill the server, which is what
#     someone with real lag is more likely to hit than a fast connection.
HIGH_PING_PROPERTIES = {
    "view-distance": "6",
    "simulation-distance": "5",
    "network-compression-threshold": "64",
    "entity-broadcast-range-percentage": "60",
    "max-tick-time": "120000",
}

# Aikar's flags - the standard, widely-used G1GC tuning for Minecraft
# servers, aimed at reducing GC-pause stutter (which shows up to players
# as rubber-banding/lag spikes even on a fast connection).
HIGH_PING_JVM_FLAGS = [
    "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled", "-XX:MaxGCPauseMillis=200",
    "-XX:+UnlockExperimentalVMOptions", "-XX:+DisableExplicitGC",
    "-XX:+AlwaysPreTouch", "-XX:G1NewSizePercent=30", "-XX:G1MaxNewSizePercent=40",
    "-XX:G1HeapRegionSize=8M", "-XX:G1ReservePercent=20", "-XX:G1HeapWastePercent=5",
    "-XX:G1MixedGCCountTarget=4", "-XX:InitiatingHeapOccupancyPercent=15",
    "-XX:G1MixedGCLiveThresholdPercent=90", "-XX:G1RSetUpdatingPauseTimePercent=5",
    "-XX:SurvivorRatio=32", "-XX:MaxTenuringThreshold=1",
]

# The "easy edits" exposed in the Server tab. online-mode defaults to false
# because Cubeon signs players in with offline/cracked accounts - leaving
# Mojang auth on would lock everyone out of their own server.
DEFAULT_SERVER_PROPERTIES = {
    "motd": "A Cubeon Server",
    "gamemode": "survival",
    "difficulty": "normal",
    "max-players": "20",
    "online-mode": "false",
    "pvp": "true",
    "level-seed": "",
    "level-name": "world",
    "server-port": "25565",
    "white-list": "false",
    "allow-flight": "false",
    "view-distance": "10",
    "simulation-distance": "10",
    "spawn-protection": "16",
}

# One live subprocess per version at most - keyed by version id.
_server_processes: "dict[str, subprocess.Popen]" = {}
_server_processes_lock = threading.Lock()


def world_lock_holder(version_id: str) -> int | None:
    """The PID of a Minecraft server still holding this world, or None.

    WHY THIS EXISTS - a real failure, captured 2026-08-22:

        [09:40:30] [ServerMain/ERROR]: Failed to start the minecraft server
        net.minecraft.util.DirectoryLock$LockException:
          .../world/session.lock: already locked (possibly by other Minecraft instance?)

    while Cubeon's own UI said "Stopped" and offered a Start button. The cause is
    that `_server_processes` lives in memory only. `start_server` deliberately
    detaches the server with `start_new_session=True` so closing the terminal
    can't kill it - but the flip side is that **restarting Cubeon leaves a
    running server alive and untracked**. `is_server_running()` then answers
    "no", Start is offered, and every attempt dies on the world lock. Three
    sessions in a row failed that way.

    The world lock is the one source of truth that outlives Cubeon's memory,
    because the *server itself* holds it. Java's `FileChannel.lock()` takes a
    POSIX **record** lock (`fcntl`/`lockf`), which - verified here by locking a
    file from a real JVM and probing it from Python - is a completely separate
    mechanism from `flock()`: `flock` reports the file as free while the JVM
    holds it. So this must use `lockf`, and an early version of this check that
    used `flock` reported every locked world as free.

    `F_GETLK` is used rather than a trial lock: it *reports* the holder's PID
    without ever acquiring anything, so this can never steal the lock from a
    live server or leave one held on the way out.

    Returns None when the world is genuinely free, when there's no lock file
    yet, or when the platform can't answer - every one of those means "don't
    block the user", since a false positive here would make Start permanently
    refuse to work.
    """
    lock_path = os.path.join(get_server_dir(version_id),
                             _level_name(version_id), "session.lock")
    if not os.path.exists(lock_path):
        return None

    # Windows has no fcntl and no F_GETLK. There, a locked world simply surfaces
    # as the same Minecraft error as before - no worse than the old behaviour.
    try:
        import fcntl
        import struct
    except ImportError:
        return None

    try:
        with open(lock_path, "rb") as handle:
            # struct flock { short l_type; short l_whence; off_t l_start;
            #                off_t l_len; pid_t l_pid; }
            query = struct.pack("hhqqi", fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0)
            result = fcntl.fcntl(handle.fileno(), fcntl.F_GETLK, query)
            l_type, _, _, _, pid = struct.unpack("hhqqi", result)
    except (OSError, ValueError, struct.error):
        return None

    # F_UNLCK in the reply means "nothing is holding it".
    if l_type == fcntl.F_UNLCK:
        return None
    return pid or None


def _level_name(version_id: str) -> str:
    """The world folder name from server.properties, defaulting to "world"."""
    try:
        props = get_server_properties(version_id)
    except Exception:
        return "world"
    return (props.get("level-name") or "world").strip() or "world"


def _sanitize(part: str) -> str:
    import re
    cleaned = re.sub(r"[^a-zA-Z0-9.+_]", "_", part)
    # "." and ".." are path components (this dir / parent dir), not names:
    # a version_id of ".." would make get_server_dir() resolve outside
    # SERVERS_DIR. Anything that's *only* dots can't be a real folder name,
    # so fall back. A real version id ("1.20.1") keeps its dots - it has
    # digits, so it's never all-dots.
    if not cleaned or set(cleaned) <= {"."}:
        return "unknown"
    return cleaned


def get_server_dir(version_id: str) -> str:
    return os.path.join(SERVERS_DIR, _sanitize(version_id))


def _typed_jar_path(version_id: str, server_type: str) -> str:
    """Each server type gets its own cached jar file (server-vanilla.jar /
    server-paper.jar) so both can be downloaded and kept side by side for
    the same version - switching between them doesn't require throwing
    one away and re-downloading it later."""
    return os.path.join(get_server_dir(version_id), f"server-{server_type}.jar")


def _migrate_legacy_jar(version_id: str) -> None:
    """Older Cubeon versions kept a single unqualified server.jar per
    version. If one of those is still lying around and hasn't been
    migrated yet, rename it into the new server-<type>.jar naming using
    whatever type was recorded for it, so existing installs keep working
    without a silent re-download."""
    server_dir = get_server_dir(version_id)
    legacy_path = os.path.join(server_dir, "server.jar")
    if not os.path.isfile(legacy_path):
        return
    legacy_type = _read_server_type_file(version_id) or SERVER_TYPE_PAPER
    typed_path = _typed_jar_path(version_id, legacy_type)
    if not os.path.isfile(typed_path):
        try:
            os.replace(legacy_path, typed_path)
        except OSError:
            return
    else:
        # Typed file already exists (shouldn't normally happen) - just
        # drop the legacy duplicate rather than risk clobbering it.
        try:
            os.remove(legacy_path)
        except OSError:
            pass


MIN_SERVER_BYTES = 1_000_000


def _server_jar_valid(path: str, *, complete: bool = False) -> bool:
    try:
        if os.path.getsize(path) < MIN_SERVER_BYTES:
            return False
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if not names:
                return False
            if complete:
                manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8")
                manifest = re.sub(r"\r?\n ", "", manifest)
                main = re.search(r"^Main-Class:\s*(\S+)", manifest, re.MULTILINE)
                if not main:
                    return False
                entry = main.group(1).replace(".", "/") + ".class"
                if entry not in names or not (
                    "paperclip" in entry.lower() or entry.startswith("org/bukkit/craftbukkit/")
                ):
                    return False
                return archive.testzip() is None
            return True
    except (OSError, zipfile.BadZipFile, zlib.error, KeyError, UnicodeError, RuntimeError, EOFError):
        return False


def is_server_installed(version_id: str, server_type: str | None = None) -> bool:
    """Whether a server jar is cached for this version. With no
    server_type, checks the currently active type (what Start/Update
    act on); pass a specific type to check that type independently of
    which one is currently active - e.g. to see if Paper is already
    installed while Vanilla is the active type."""
    _migrate_legacy_jar(version_id)
    check_type = server_type or get_server_type(version_id)
    return _server_jar_valid(_typed_jar_path(version_id, check_type))


def get_installed_server_types(version_id: str) -> list[str]:
    """All server types that currently have a cached jar for this
    version, in SERVER_TYPES order."""
    _migrate_legacy_jar(version_id)
    return [t for t in SERVER_TYPES if _server_jar_valid(_typed_jar_path(version_id, t))]


# ---------------------------------------------------------------------------
# Server type (vanilla / Paper) - stored as a sidecar file per version so
# reinstalling/reopening the app remembers which jar the user actually wants
# active (i.e. which one Start/Update/the console act on). Both types can
# have a cached jar at once (see _typed_jar_path); this only tracks which
# one is currently selected.
# ---------------------------------------------------------------------------

def _read_server_type_file(version_id: str) -> str | None:
    path = os.path.join(get_server_dir(version_id), "server_type.txt")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
                if value in SERVER_TYPES:
                    return value
        except OSError:
            pass
    return None


def get_server_type(version_id: str) -> str:
    return _read_server_type_file(version_id) or SERVER_TYPE_PAPER


def set_server_type(version_id: str, server_type: str) -> None:
    if server_type not in SERVER_TYPES:
        raise ValueError(f"Unknown server type: {server_type}")
    server_dir = get_server_dir(version_id)
    os.makedirs(server_dir, exist_ok=True)
    with open(os.path.join(server_dir, "server_type.txt"), "w", encoding="utf-8") as f:
        f.write(server_type)


def switch_server_type(version_id: str, server_type: str) -> bool:
    """Makes server_type the active type - instantly, with no download -
    if (and only if) it's already installed (has a cached jar). Returns
    False without changing anything if it isn't installed yet, so callers
    know to fall back to install_server() instead."""
    if not is_server_installed(version_id, server_type):
        return False
    set_server_type(version_id, server_type)
    return True


def _get_paper_download_url(version_id: str) -> tuple[str, str]:
    """Looks up the latest stable Paper build for version_id via papermc.io's
    Fill v3 API (fill.papermc.io) - the old api.papermc.io/v2 endpoint has
    been sunset and stopped returning current builds. Returns
    (download_url, build_number_as_string)."""
    headers = {"User-Agent": f"{APP_NAME}-launcher/1.0 (https://github.com/{APP_NAME.lower()})"}
    try:
        data = net.get_json(
            f"https://fill.papermc.io/v3/projects/paper/versions/{version_id}/builds",
            headers=headers, timeout=15,
        )
    except requests.HTTPError as ex:
        if getattr(ex.response, "status_code", None) == 404:
            raise RuntimeError(
                f"Paper doesn't publish builds for {version_id} "
                "(try a recent release version).") from ex
        raise
    if isinstance(data, dict) and data.get("ok") is False:
        raise RuntimeError(data.get("message") or f"Paper has no builds for {version_id}.")
    builds = data if isinstance(data, list) else data.get("builds", [])

    stable = [b for b in builds if b.get("channel") == "STABLE"] or builds
    if not stable:
        raise RuntimeError(f"No Paper builds found for {version_id}.")
    # Builds come back oldest-first from Fill, same as the old v2 API.
    build = stable[-1]
    build_number = build.get("id") or build.get("number") or build.get("build")
    download = (build.get("downloads") or {}).get("server:default") or (build.get("downloads") or {}).get("application")
    if not download:
        raise RuntimeError(
            f"Paper build {build_number} for {version_id} has no recognizable download entry "
            f"(downloads keys: {sorted((build.get('downloads') or {}).keys())})."
        )
    download_url = download.get("url")
    if not download_url:
        raise RuntimeError(
            f"Paper build {build_number} for {version_id}'s download entry is missing a 'url' "
            f"(entry keys: {sorted(download.keys())})."
        )
    return download_url, str(build_number)


def eula_accepted(version_id: str) -> bool:
    path = os.path.join(get_server_dir(version_id), "eula.txt")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            return "eula=true" in f.read().lower()
    except OSError:
        return False


def set_eula_accepted(version_id: str, accepted: bool) -> None:
    """The Minecraft EULA (aka.ms/MinecraftEULA) has to be accepted by the
    person running the server, explicitly - Cubeon never sets this on its
    own. This is only called from a checkbox the user ticks themselves."""
    server_dir = get_server_dir(version_id)
    os.makedirs(server_dir, exist_ok=True)
    with open(os.path.join(server_dir, "eula.txt"), "w", encoding="utf-8") as f:
        f.write(f"eula={'true' if accepted else 'false'}\n")


def find_local_paper_jar(search_dirs: list[str] | None = None) -> str | None:
    """A Paper server jar the user already has on disk, or None.

    Cubeon's own folder is searched first (the user was told to drop their
    paper jar there), then ~/.cubeon_launcher, then the servers dir itself.
    Matches any *.jar whose name mentions "paper" (case-insensitive) but
    isn't one of Cubeon's own cached/typed jars, plugin jars, or a partial
    download. Newest file wins when several match.

    WHY bother: downloads fail on bad connections and school networks, and
    Paper publishes big jars. Someone who already has the jar - from a
    friend, another launcher, a previous install - should never be blocked
    by a mirror.
    """
    import glob as _glob

    if search_dirs is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        search_dirs = [app_dir, os.getcwd(), SERVERS_DIR]

    candidates = []
    for directory in search_dirs:
        if not directory or not os.path.isdir(directory):
            continue
        for path in _glob.glob(os.path.join(directory, "*.jar")):
            name = os.path.basename(path).lower()
            if "paper" not in name:
                continue
            # Never mistake Cubeon's own cache, a half-download, or a plugin
            # for the server jar itself.
            if name.startswith("server-") or name.endswith(".part"):
                continue
            try:
                if os.path.getsize(path) < 1_000_000:
                    continue
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            candidates.append((mtime, path))

    if not candidates:
        return None
    return max(candidates)[1]


def install_server(version_id: str, server_type: str = SERVER_TYPE_PAPER,
                    status_cb=None, progress_cb=None, max_cb=None,
                    local_jar_path: str | None = None) -> None:
    """Installs the Paper server jar for a version into its own folder
    under SERVERS_DIR, cached as server-paper.jar. Re-running this later
    just updates that cached jar in place - it never touches an existing
    server.properties/eula.txt/world/plugins.

    The jar comes from `local_jar_path` when given (or from a jar already
    on disk that find_local_paper_jar() can see) - copied, not downloaded.
    Only if there's no local jar anywhere does this download the latest
    stable Paper build for version_id via papermc.io's Fill v3 API. A
    local jar is preferred over a download because it works offline and
    on networks where papermc.io is blocked; its MC version is whatever
    the user chose, so they're responsible for picking one matching the
    selected version.

    The install only "counts" once a complete jar is in place - if this
    raises partway, nothing about the app's recorded state changes."""
    if status_cb:
        status_cb("Looking up Paper server jar")

    local = local_jar_path or find_local_paper_jar()
    using_local = bool(local and os.path.isfile(local))

    server_dir = get_server_dir(version_id)
    os.makedirs(server_dir, exist_ok=True)
    os.makedirs(os.path.join(server_dir, "plugins"), exist_ok=True)

    # Paper jars are ~50 MB and worlds grow well past that; refusing early on
    # a nearly-full drive beats a mid-download failure and a partial jar.
    from .paths import ensure_disk_space
    ensure_disk_space(server_dir, 512 * 1024 * 1024, "server install")

    final_path = _typed_jar_path(version_id, SERVER_TYPE_PAPER)
    fd, tmp_path = tempfile.mkstemp(dir=server_dir, prefix=".server-", suffix=".part")
    os.close(fd)
    try:
        if using_local:
            if status_cb:
                status_cb(f"Using your Paper jar ({os.path.basename(local)})")
            ensure_disk_space(server_dir, os.path.getsize(local), "server jar")
            shutil.copyfile(local, tmp_path)
            if progress_cb and max_cb:
                size = os.path.getsize(local)
                max_cb(size)
                progress_cb(size)
        else:
            url, build = _get_paper_download_url(version_id)
            if status_cb:
                status_cb(f"Downloading Paper {build} server.jar")
            dl_headers = {"User-Agent": f"{APP_NAME}-launcher/1.0 (https://github.com/{APP_NAME.lower()})"}
            try:
                probe = requests.head(url, headers=dl_headers, timeout=10,
                                      allow_redirects=True)
                total = int(probe.headers.get("content-length", 0))
            except (requests.RequestException, ValueError):
                total = 0
            if max_cb and total:
                max_cb(total)
            try:
                size = net.download_to(tmp_path, url, headers=dl_headers, timeout=30,
                                       progress_cb=(lambda done, _total: progress_cb(done))
                                       if progress_cb is not None and total else None)
            except net.DownloadError as ex:
                raise RuntimeError(str(ex)) from ex
            if max_cb and not total:
                max_cb(size)
            if progress_cb and not total:
                progress_cb(size)

        if not _server_jar_valid(tmp_path, complete=True):
            raise RuntimeError("Server download integrity check failed. "
                               "Choose a complete Paper download and try again.")
        os.replace(tmp_path, final_path)
    finally:
        for path in (tmp_path, tmp_path + ".part"):
            try:
                os.unlink(path)
            except OSError:
                pass
    set_server_type(version_id, SERVER_TYPE_PAPER)

    # First-time scaffolding only - an update should never reset settings.
    if not os.path.isfile(os.path.join(server_dir, "server.properties")):
        save_server_properties(version_id, dict(DEFAULT_SERVER_PROPERTIES))
    if not os.path.isfile(os.path.join(server_dir, "eula.txt")):
        set_eula_accepted(version_id, False)

    if status_cb:
        status_cb("Server ready")


def get_server_properties(version_id: str) -> dict:
    """Returns the easy-edit properties for a version's server, filled in
    with defaults for anything not yet present in the file."""
    props = dict(DEFAULT_SERVER_PROPERTIES)
    path = os.path.join(get_server_dir(version_id), "server.properties")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                props[key.strip()] = value.strip()
    return props


def save_server_properties(version_id: str, props: dict) -> None:
    server_dir = get_server_dir(version_id)
    os.makedirs(server_dir, exist_ok=True)
    with open(os.path.join(server_dir, "server.properties"), "w", encoding="utf-8") as f:
        f.write("# Minecraft server properties, managed by Cubeon\n")
        for key, value in props.items():
            f.write(f"{key}={value}\n")


# Vanilla's own defaults for the HIGH_PING_PROPERTIES keys that aren't
# already covered by DEFAULT_SERVER_PROPERTIES (which only tracks the keys
# exposed as "easy edits" in the Server tab). Needed so turning "smooth
# mode" back OFF can actually restore these - without this, disabling the
# toggle left simulation-distance/network-compression-threshold/
# entity-broadcast-range-percentage/max-tick-time stuck at the preset's
# values forever, because set_high_ping_optimization's revert path had
# nothing to fall back to for keys DEFAULT_SERVER_PROPERTIES didn't define.
_VANILLA_DEFAULTS_FOR_HIGH_PING_KEYS = {
    "simulation-distance": "10",
    "network-compression-threshold": "256",
    "entity-broadcast-range-percentage": "100",
    "max-tick-time": "60000",
}


def high_ping_optimization_enabled(version_id: str) -> bool:
    """Whether Smooth mode is ON for this version.

    The state is an explicit per-version flag in Cubeon's config (set by
    set_high_ping_optimization) so it survives tab switches and the
    settings-save path, which rewrites view/simulation-distance from the
    dropdowns and would otherwise make a pure properties-based check read
    False. We fall back to the properties check only for installs that were
    pre-configured out-of-band (e.g. a server.properties already carrying the
    full preset) before this flag existed."""
    from . import config as _cfg
    cfg = _cfg.load_config()
    flags = cfg.get("high_ping_optimization") or {}
    if version_id in flags:
        return bool(flags[version_id])
    # Backward-compat: trust the on-disk preset if we've never recorded a flag.
    props = get_server_properties(version_id)
    return all(props.get(k) == v for k, v in HIGH_PING_PROPERTIES.items())


def set_high_ping_optimization(version_id: str, enabled: bool) -> None:
    """Applies (or reverts to defaults) the low-latency server.properties
    preset. Only touches the specific keys in HIGH_PING_PROPERTIES -
    everything else the user configured (motd, whitelist, difficulty,
    gamemode, etc.) is left exactly as-is. Also records an explicit
    per-version flag so the UI switch stays in sync across tab switches."""
    from . import config as _cfg
    props = get_server_properties(version_id)
    if enabled:
        props.update(HIGH_PING_PROPERTIES)
    else:
        for key in HIGH_PING_PROPERTIES:
            props[key] = (
                DEFAULT_SERVER_PROPERTIES.get(key)
                or _VANILLA_DEFAULTS_FOR_HIGH_PING_KEYS.get(key)
                or props.get(key)
            )
    save_server_properties(version_id, props)
    cfg = _cfg.load_config()
    flags = dict(cfg.get("high_ping_optimization") or {})
    flags[version_id] = bool(enabled)
    cfg["high_ping_optimization"] = flags
    _cfg.save_config(cfg)


def open_server_folder(version_id: str) -> None:
    """Opens the version's server folder in the OS file manager - same
    approach as mods.py's open_mods_folder, so the user can drop in
    plugin config files, edit ops.json by hand, browse the world, etc."""
    server_dir = get_server_dir(version_id)
    os.makedirs(server_dir, exist_ok=True)
    if os.name == "nt":
        os.startfile(server_dir)
    elif os.uname().sysname == "Darwin":
        subprocess.Popen(["open", server_dir])
    else:
        subprocess.Popen(["xdg-open", server_dir])


def is_server_running(version_id: str) -> bool:
    """Whether a server for this version is up - including one Cubeon lost.

    Checks the tracked subprocess first, then the world lock. The second half
    matters because servers are started detached (see start_server), so a
    Cubeon restart leaves a live server that `_server_processes` knows nothing
    about. Reporting that as "Stopped" is what produced three consecutive
    `session.lock: already locked` failures on 2026-08-22.
    """
    process = _server_processes.get(version_id)
    if process and process.poll() is None:
        return True
    return world_lock_holder(version_id) is not None


def is_server_orphaned(version_id: str) -> int | None:
    """PID of a server that's running but NOT tracked by this Cubeon, else None.

    This is the state the UI has to talk about differently: the server is up,
    but Cubeon can't send it commands or read its console, because it belongs to
    a previous Cubeon process. The only honest options are "adopt it by stopping
    it" or "leave it alone".
    """
    process = _server_processes.get(version_id)
    if process and process.poll() is None:
        return None
    return world_lock_holder(version_id)


def stop_orphaned_server(version_id: str, timeout: float = 45.0) -> bool:
    """Stops a server left behind by a previous Cubeon run.

    Signals the PID the *world lock itself* reported, never a name match - a
    `pkill java` here would kill the user's unrelated Java programs, and on a
    machine that also runs a modded client that means killing their game.

    Escalates SIGTERM → SIGKILL: Minecraft handles SIGTERM by saving and
    shutting down cleanly, so that's tried first and given time to finish. Only
    a server that ignores it gets killed outright, because an unclean kill on a
    Minecraft world risks corrupted region files.
    """
    pid = world_lock_holder(version_id)
    if not pid:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if world_lock_holder(version_id) is None:
            return True

    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    for _ in range(20):
        time.sleep(0.25)
        if world_lock_holder(version_id) is None:
            return True
    return world_lock_holder(version_id) is None


def _force_kill(process: subprocess.Popen) -> None:
    """Kills the whole process group the server was started into (see
    start_new_session in start_server), not just its top PID - a plain
    process.kill() only reaches that one process, so anything it spawned
    would survive a force-stop and silently keep holding the server port
    and world files open."""
    if os.name == "nt":
        process.kill()
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()


def start_server(version_id: str, ram_mb: int, java_path: str | None = None,
                  on_output=None, on_exit=None) -> subprocess.Popen:
    """Starts (or reuses) the server process for a version. Output lines are
    streamed to on_output(line) from a background thread as they arrive, so
    the UI can show a live console without blocking."""
    if is_server_running(version_id):
        orphan = is_server_orphaned(version_id)
        if orphan:
            # Distinguished from "already running" because the fix is different:
            # this server can't be stopped from Cubeon's Stop button (it belongs
            # to a previous Cubeon run), so the message has to name the real
            # remedy. Without this, Minecraft's own error was the only clue -
            # "session.lock: already locked" next to a UI saying "Stopped".
            raise RuntimeError(
                f"A Minecraft server for this version is already running "
                f"(process {orphan}) from an earlier Cubeon session. Click "
                f"\"Stop leftover server\" to shut it down, then start again."
            )
        raise RuntimeError("This server is already running.")

    if not is_server_installed(version_id):
        raise RuntimeError("Server isn't installed for this version yet.")
    if not eula_accepted(version_id):
        raise RuntimeError("Accept the Minecraft EULA before starting the server.")

    server_dir = get_server_dir(version_id)
    jar_name = os.path.basename(_typed_jar_path(version_id, get_server_type(version_id)))
    java = find_java_for_version(version_id, java_path)
    # If the only Java we could find is too old, say so directly instead of
    # letting Minecraft print "requires running the server with Java 25 or
    # above" with no hint of how to fix it.
    java_major = java_major_version(java)
    required = required_java_major(version_id)
    if java_major is not None and java_major < required:
        raise RuntimeError(
            f"This Minecraft version needs Java {required} or newer, but the "
            f"best Java Cubeon found is Java {java_major} ({java}). Install a "
            f"Java {required}+ JDK (e.g. from https://adoptium.net) and point "
            f"Cubeon at it in Settings, or it'll fail to start."
        )
    command = [java, f"-Xmx{ram_mb}M", f"-Xms{min(ram_mb, 1024)}M"]
    if high_ping_optimization_enabled(version_id):
        command += HIGH_PING_JVM_FLAGS
    command += ["-jar", jar_name, "nogui"]

    process = subprocess.Popen(
        command, cwd=server_dir,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
        # Detach into its own session/process group. Without this, the
        # server inherits whatever session launched Cubeon (e.g. a
        # terminal running `python main.py`) - closing that terminal, a
        # Ctrl+C, or the terminal emulator's own cleanup on exit can then
        # send a signal to the whole group and take the server down with
        # it, with nothing in Cubeon's own logs to explain why. Detaching
        # means only stop_server() (or an explicit kill of this specific
        # process) can ever stop it.
        start_new_session=(os.name != "nt"),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    with _server_processes_lock:
        _server_processes[version_id] = process

    if on_output:
        def _pump_output():
            for line in process.stdout:
                on_output(line.rstrip("\n"))
        threading.Thread(target=_pump_output, daemon=True).start()

    if on_exit:
        def _watch():
            process.wait()
            with _server_processes_lock:
                if _server_processes.get(version_id) is process:
                    _server_processes.pop(version_id, None)
            on_exit(process.returncode)
        threading.Thread(target=_watch, daemon=True).start()

    return process


def send_server_command(version_id: str, command_text: str, timeout: float = 2.0) -> None:
    """Writes a line to the running server's stdin - same as typing directly
    into the server console (op <name>, whitelist add <name>, say hi, ...).

    Never blocks the caller for long. The server subprocess is started with
    stdin=subprocess.PIPE, and if it isn't reading (mid-startup, GC pause,
    hung), the OS pipe buffer fills and a raw write()/flush() would block
    FOREVER - which used to freeze the whole launcher when this ran on the
    UI thread (Stop = send 'stop'). The write now happens on a helper
    thread and raises RuntimeError if it doesn't complete within `timeout`.
    """
    process = _server_processes.get(version_id)
    if not process or process.poll() is not None or not process.stdin:
        raise RuntimeError("Server isn't running.")
    stdin = process.stdin
    done = threading.Event()
    error: list[BaseException | None] = [None]

    def _write_worker():
        try:
            # stdin is a TEXT-mode pipe (Popen isn't using text=False), so
            # write str - encoding to bytes here raises TypeError.
            stdin.write(command_text.strip() + "\n")
            stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as ex:
            error[0] = ex
        finally:
            done.set()

    threading.Thread(target=_write_worker, daemon=True).start()
    if not done.wait(timeout):
        raise RuntimeError("Server isn't accepting commands right now (try again in a moment).")
    if error[0] is not None:
        raise RuntimeError(f"Couldn't send command: {error[0]}")


def stop_server(version_id: str, timeout: float = 45.0, status_cb=None) -> None:
    """Asks the server to shut down cleanly via the 'stop' console command
    (saves the world first) and only force-kills it if it doesn't respond
    within timeout.

    Two things the old version got wrong, both of which made Stop feel
    unreliable:

    - It sent 'stop' exactly once. If the server was still mid-startup
      (stdin not writable yet), that single attempt silently failed and
      the code fell straight through to a hard 20s wait, ending in a
      force-kill every time - never a clean shutdown. This now retries
      sending 'stop' for a few seconds so a Stop click during startup
      actually gets through once the server's ready for it.
    - It gave the UI zero feedback during the (up to 20s) wait - the
      status stayed on "Running" the whole time, so a Stop click looked
      like it had done nothing. status_cb, when given, reports what's
      actually happening at each stage.
    - The old 20s timeout could force-kill a server that was still in
      the middle of writing the world to disk on a larger world, which
      risks a corrupted/partial save. Default is now 45s, and a
      force-kill only happens after that's genuinely elapsed.
    """
    process = _server_processes.get(version_id)
    if not process or process.poll() is not None:
        return

    def _status(text):
        if status_cb:
            status_cb(text)

    send_window = min(timeout, 10.0)
    send_deadline = time.monotonic() + send_window
    sent = False
    while time.monotonic() < send_deadline:
        if process.poll() is not None:
            return  # exited on its own while we were trying to reach it
        try:
            send_server_command(version_id, "stop")
            sent = True
            break
        except RuntimeError:
            time.sleep(0.5)

    if not sent:
        _status("Server never became responsive to commands. Force stopping.")
        _force_kill(process)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return

    _status("Stop command sent. Saving world...")
    remaining = max(timeout - send_window, 5.0)
    try:
        process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        _status(f"Didn't stop within {timeout:.0f}s. Force stopping.")
        _force_kill(process)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def delete_server(version_id: str) -> None:
    """Deletes a version's entire server folder (jars, world, properties,
    plugins) from SERVERS_DIR.

    User-initiated and explicit, so - like versions.delete_version - it really
    does remove data, but only this one version's server folder under
    SERVERS_DIR, nothing shared. Refuses while the server is running (tracked
    OR a detached leftover still holding the world lock): deleting files out
    from under a live JVM risks corrupting the world and wouldn't release the
    lock anyway. Stop it first.

    Raises RuntimeError if it's running, or ValueError on a bad id / path
    escape / OS failure - both carry a message the UI can surface directly.
    """
    if not version_id:
        raise ValueError("No version selected.")

    if is_server_running(version_id):
        raise RuntimeError(
            "Stop the server before deleting it. It's still running "
            "(or a leftover from an earlier session is holding the world)."
        )

    target = get_server_dir(version_id)
    # get_server_dir already _sanitize()s the id, but re-verify the resolved
    # path really sits inside SERVERS_DIR before any rmtree - same guard style
    # as versions.delete_version, so a surprising id can never escape.
    if os.path.abspath(target) != os.path.normpath(target) \
            or not os.path.abspath(target).startswith(os.path.abspath(SERVERS_DIR) + os.sep):
        raise ValueError("Refusing to delete a path outside the servers folder.")

    if not os.path.isdir(target):
        # Nothing on disk (never installed, or already gone) - clear any stale
        # in-memory handle and treat it as done rather than erroring.
        _server_processes.pop(version_id, None)
        return

    try:
        shutil.rmtree(target)
    except OSError as ex:
        raise ValueError(f"Couldn't delete this server: {ex}") from ex

    _server_processes.pop(version_id, None)


# ---------------------------------------------------------------------------
# Plugin management (Paper only) - .jar files in <server_dir>/plugins/,
# discovered/downloaded via Modrinth's public API scoped to
# project_type:plugin. Mirrors mods.py's list/toggle/delete/install shape
# so this behaves consistently with the Mods tab the user already knows.
# ---------------------------------------------------------------------------

def get_plugins_dir(version_id: str) -> str:
    path = os.path.join(get_server_dir(version_id), "plugins")
    os.makedirs(path, exist_ok=True)
    return path


def _write_plugin_meta(plugins_dir: str, filename: str, slug: str | None) -> None:
    base = filename[:-4] if filename.endswith(".jar") else filename
    meta_path = os.path.join(plugins_dir, base + PLUGIN_META_SUFFIX)
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"slug": slug}, f)
    except OSError:
        pass


def _read_plugin_meta(plugins_dir: str, filename: str) -> dict:
    base = filename[:-4] if filename.endswith(".jar") else filename
    base = base[:-9] if base.endswith(".disabled") else base
    meta_path = os.path.join(plugins_dir, base + PLUGIN_META_SUFFIX)
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def list_plugins(version_id: str) -> list[dict]:
    """Every plugin currently in the server's plugins/ folder, enabled or
    disabled (a '.jar.disabled' suffix is how disabled plugins are
    tracked - same convention mods.py uses)."""
    plugins_dir = get_plugins_dir(version_id)
    results = []
    for fname in sorted(os.listdir(plugins_dir)):
        if fname.endswith(PLUGIN_META_SUFFIX):
            continue
        if not (fname.endswith(".jar") or fname.endswith(".jar.disabled")):
            continue
        enabled = fname.endswith(".jar")
        display_name = fname[:-len(".jar.disabled")] if not enabled else fname[:-len(".jar")]
        meta = _read_plugin_meta(plugins_dir, fname)
        stem = fname[:-len(".jar.disabled")] if not enabled else fname[:-len(".jar")]
        results.append({
            "filename": fname,
            "display_name": display_name,
            "enabled": enabled,
            "slug": meta.get("slug"),
            "protected": is_protected_plugin_stem(stem),
        })
    return results


def toggle_plugin(version_id: str, filename: str, enabled: bool) -> None:
    base = filename.replace(".jar.disabled", "").replace(".jar", "")
    if is_protected_plugin_stem(base):
        raise ValueError(
            "That plugin is managed by Cubeon and can't be disabled. "
            "Server security and sharing depend on it.")
    plugins_dir = get_plugins_dir(version_id)
    src = os.path.join(plugins_dir, filename)
    if enabled and filename.endswith(".jar.disabled"):
        dst = os.path.join(plugins_dir, filename[: -len(".disabled")])
    elif not enabled and filename.endswith(".jar"):
        dst = os.path.join(plugins_dir, filename + ".disabled")
    else:
        return
    os.rename(src, dst)


def delete_plugin(version_id: str, filename: str) -> None:
    base = filename[: -len(".disabled")] if filename.endswith(".disabled") else filename
    if is_protected_plugin_stem(base[:-4] if base.endswith(".jar") else base):
        raise ValueError(
            "That plugin is managed by Cubeon and can't be removed. "
            "Server security and sharing depend on it.")
    plugins_dir = get_plugins_dir(version_id)
    path = os.path.join(plugins_dir, filename)
    if os.path.isfile(path):
        os.remove(path)
    base = filename[: -len(".disabled")] if filename.endswith(".disabled") else filename
    base = base[:-4] if base.endswith(".jar") else base
    meta_path = os.path.join(plugins_dir, base + PLUGIN_META_SUFFIX)
    if os.path.isfile(meta_path):
        os.remove(meta_path)


def install_local_plugin(version_id: str, src_path: str) -> str:
    """Copies a local .jar straight into the plugins folder - for a plugin
    the user already has on disk, same as mods.py's install_local_mod."""
    if not src_path.lower().endswith(".jar"):
        raise ValueError("That's not a .jar file.")
    if not os.path.isfile(src_path):
        raise FileNotFoundError(src_path)
    plugins_dir = get_plugins_dir(version_id)
    filename = os.path.basename(src_path)
    dest = os.path.join(plugins_dir, filename)
    shutil.copyfile(src_path, dest)
    return filename


def get_recommended_plugins() -> list[dict]:
    cache_key = {"slugs": RECOMMENDED_PLUGIN_SLUGS}

    def _fetch() -> list[dict]:
        projects = net.get_json(
            f"{MODRINTH_API}/projects", params={"ids": json.dumps(RECOMMENDED_PLUGIN_SLUGS)},
            headers=MODRINTH_HEADERS, timeout=15,
        )
        by_slug = {p.get("slug"): p for p in projects}
        results = []
        for slug in RECOMMENDED_PLUGIN_SLUGS:
            p = by_slug.get(slug)
            if not p:
                continue
            results.append({
                "project_id": p.get("id"), "slug": p.get("slug"), "title": p.get("title"),
                "description": p.get("description"), "icon_url": p.get("icon_url"),
                "downloads": p.get("downloads", 0),
            })
        return results

    return local_cache.cached_call("recommended_plugins", cache_key, _fetch, max_age=86400)


def get_low_ping_plugins() -> list[dict]:
    """Curated low-ping optimization picks for Paper servers - same shape as
    get_recommended_plugins() so the UI can render them with the same row
    builder. Missing/renamed slugs are skipped rather than erroring."""
    cache_key = {"slugs": LOW_PING_PLUGIN_SLUGS}

    def _fetch() -> list[dict]:
        by_slug = {p.get("slug"): p for p in net.get_json(
            f"{MODRINTH_API}/projects", params={"ids": json.dumps(LOW_PING_PLUGIN_SLUGS)},
            headers=MODRINTH_HEADERS, timeout=15,
        )}
        results = []
        for slug in LOW_PING_PLUGIN_SLUGS:
            p = by_slug.get(slug)
            if not p:
                continue
            results.append({
                "project_id": p.get("id"), "slug": p.get("slug"), "title": p.get("title"),
                "description": p.get("description"), "icon_url": p.get("icon_url"),
                "downloads": p.get("downloads", 0),
            })
        return results

    return local_cache.cached_call("low_ping_plugins", cache_key, _fetch, max_age=86400)


def ensure_smooth_mode_plugins(version_id: str, progress_cb=None) -> dict:
    """Cubeon's OWN low-ping stack, not just recommendations: when Smooth
    mode is switched on this installs every curated performance plugin the
    server doesn't already have (Paper only - vanilla has no plugin system,
    where we apply the properties + JVM tuning and say so).

    progress_cb(dict) is called with:
      {"stage": "start",    "slug": s, "title": t}
      {"stage": "progress", "slug": s, "title": t, "done": b, "total": b}
      {"stage": "done",     "slug": s, "title": t, "ok": bool, "detail": str}
      {"stage": "summary",  ...final result dict...}

    Returns {"installed": [titles], "present": [titles],
             "failed": [(title, reason)], "skipped_reason": str|None}.
    Never raises for an individual plugin failure - a dead mirror must not
    stop the other two from installing; network-level errors surface in
    "failed" entries too.
    """
    result = {"installed": [], "present": [], "failed": [], "skipped_reason": None}

    def _report(ev):
        if progress_cb:
            try:
                progress_cb(ev)
            except Exception:
                pass

    if get_server_type(version_id) != SERVER_TYPE_PAPER:
        result["skipped_reason"] = (
            "plugins need a Paper server. Smooth mode applied its "
            "properties + JVM tuning; switch the server type to Paper to "
            "also get the auto-installed performance plugins")
        return result

    # What's already there? Match by recorded slug OR by jar name, so a
    # plugin installed manually before Cubeon tracked slugs still counts.
    have = set()
    for p in list_plugins(version_id):
        if p.get("slug"):
            have.add(p["slug"].lower())
        base = p["filename"].replace(".jar.disabled", "").replace(".jar", "").lower()
        have.add(base)
        for slug in LOW_PING_PLUGIN_SLUGS:
            if slug in base:
                have.add(slug)

    titles = {s: s.capitalize() for s in LOW_PING_PLUGIN_SLUGS}
    try:
        for hit in get_low_ping_plugins():
            titles[hit["slug"]] = hit.get("title") or hit["slug"].capitalize()
    except Exception:
        pass  # metadata fetch is best-effort; downloads below still work

    todo = []
    for slug in LOW_PING_PLUGIN_SLUGS:
        if slug in have:
            result["present"].append(titles[slug])
        else:
            todo.append(slug)

    for slug in todo:
        title = titles[slug]
        _report({"stage": "start", "slug": slug, "title": title})
        try:
            info = get_plugin_download(slug, mc_version=version_id)
            if not info:
                # No build tagged with this exact MC version. Paper plugins
                # are broadly version-tolerant (they compile against the
                # stable API), so fall back to the latest published build -
                # a wrong-version plugin fails LOUDLY at server boot, which
                # the user can see, rather than silently never arriving.
                info = get_plugin_download(slug)
            if not info:
                result["failed"].append((title, f"no build found for {version_id}"))
                _report({"stage": "done", "slug": slug, "title": title,
                         "ok": False, "detail": "no build available"})
                continue
            last = {"done": 0, "total": 0}

            def _dl_progress(done, total, _slug=slug):
                last["done"], last["total"] = done, total
                _report({"stage": "progress", "slug": _slug, "title": title,
                         "done": done, "total": total})

            download_plugin(version_id, info["url"], info["filename"],
                            slug=slug, progress_cb=_dl_progress)
            size_mb = info.get("size_kb", 0) / 1024
            result["installed"].append(
                f"{title} ({size_mb:.1f} MB)" if size_mb else title)
            _report({"stage": "done", "slug": slug, "title": title, "ok": True})
        except Exception as ex:
            result["failed"].append((title, f"{type(ex).__name__}: {ex}"))
            _report({"stage": "done", "slug": slug, "title": title,
                     "ok": False, "detail": str(ex)})
    _report({"stage": "summary"})
    return result


def search_plugins(query: str, mc_version: str | None = None, limit: int = 100) -> list[dict]:
    """Searches Modrinth for Paper plugins, optionally scoped to an MC
    version. Bukkit/Spigot-loader plugins are Paper-compatible too, so
    both loader facets are OR'd together to catch everything installable."""
    facets = [["project_type:plugin"], ["categories:paper", "categories:bukkit", "categories:spigot"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    cache_key = {"query": query, "mc_version": mc_version, "limit": limit}

    def _fetch() -> list[dict]:
        params = {"query": query, "limit": str(limit), "facets": json.dumps(facets),
                  "index": modrinth_search_index(query)}
        data = net.get_json(f"{MODRINTH_API}/search", params=params,
                            headers=MODRINTH_HEADERS, timeout=15)
        results = []
        for hit in data.get("hits", []):
            results.append({
                "project_id": hit.get("project_id"), "slug": hit.get("slug"), "title": hit.get("title"),
                "description": hit.get("description"), "icon_url": hit.get("icon_url"),
                "downloads": hit.get("downloads", 0), "author": hit.get("author"),
            })
        return rank_search_hits(results, query)

    return local_cache.cached_call("search_plugins", cache_key, _fetch, max_age=6 * 3600)


def get_plugin_download(project_id_or_slug: str, mc_version: str | None = None) -> dict | None:
    cache_key = {"project": project_id_or_slug, "mc_version": mc_version}

    def _fetch():
        params = {"loaders": json.dumps(["paper", "spigot", "bukkit"])}
        if mc_version:
            params["game_versions"] = json.dumps([mc_version])
        versions = net.get_json(
            f"{MODRINTH_API}/project/{project_id_or_slug}/version",
            params=params, headers=MODRINTH_HEADERS, timeout=15,
        )
        if not versions:
            return None
        latest = versions[0]
        files = latest.get("files", [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not primary:
            return None
        return {
            "filename": primary.get("filename"), "url": primary.get("url"),
            "size_kb": round(primary.get("size", 0) / 1024, 1),
            "version_number": latest.get("version_number"),
        }

    return local_cache.cached_call("plugin_download", cache_key, _fetch, max_age=86400)


def download_plugin(version_id: str, download_url: str, filename: str,
                     slug: str | None = None, progress_cb=None) -> str:
    """Fetch a plugin jar with the same retry/resume/atomic-replace guarantees
    as every other download in the launcher (see cubeon/net.py)."""
    from . import net
    plugins_dir = get_plugins_dir(version_id)
    dest = os.path.join(plugins_dir, filename)
    net.download_to(dest, download_url, headers=MODRINTH_HEADERS, timeout=60,
                    progress_cb=progress_cb)
    _write_plugin_meta(plugins_dir, filename, slug)
    return dest


def get_local_lan_address() -> str:
    """Best-effort local network IP so the user can tell friends what to
    connect to. Doesn't actually send any traffic."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Whitelist - the real, working gate for who can join the server.
#
# server.properties' white-list=true is only half of it: the server also
# reads whitelist.json, and THAT file is the actual list of allowed names.
# Without managing it, the Settings switch did nothing but lock everyone
# out. Two write paths, chosen by whether the server is up:
#
#   running  -> console command (`whitelist add/remove Name`). The server
#               computes the correct UUID itself, updates whitelist.json,
#               and applies it to live connections - no reload needed.
#   stopped  -> whitelist.json written directly. The UUID must be ours;
#               Cubeon servers are offline-mode (online-mode=false), where
#               the vanilla offline UUID is md5("OfflinePlayer:<name>") -
#               exactly what config.offline_uuid() computes, and exactly
#               what the server will recompute for that name at boot. An
#               online-mode server would need Mojang's real UUIDs, so in
#               that case we still write the entry but the name is what
#               matters on next `whitelist reload`... which needs the
#               server up anyway; the console path covers that case.
# ---------------------------------------------------------------------------

def _whitelist_path(version_id: str) -> str:
    return os.path.join(get_server_dir(version_id), "whitelist.json")


def _read_whitelist(version_id: str) -> list[dict]:
    try:
        with open(_whitelist_path(version_id), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_whitelist(version_id: str, entries: list[dict]) -> None:
    server_dir = get_server_dir(version_id)
    os.makedirs(server_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=server_dir, prefix=".whitelist-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, _whitelist_path(version_id))
    except OSError as ex:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise ValueError(f"Couldn't save the whitelist: {ex}") from ex


def get_whitelist(version_id: str) -> list[str]:
    """The whitelisted player names, file order."""
    return [str(e.get("name") or "") for e in _read_whitelist(version_id)
            if e.get("name")]


def is_whitelisted(version_id: str, name: str) -> bool:
    want = (name or "").strip().lower()
    return any(str(e.get("name") or "").lower() == want
               for e in _read_whitelist(version_id))


def add_to_whitelist(version_id: str, name: str) -> None:
    """Whitelists a player. Live console command when the server is up
    (applies instantly, server owns the file); direct file write when it's
    stopped, using the offline UUID the server will recompute anyway."""
    from .config import offline_uuid, validate_username
    clean = (name or "").strip()
    ok, why = validate_username(clean)
    if not ok:
        raise ValueError(f"That isn't a valid Minecraft name: {why}")
    if is_whitelisted(version_id, clean):
        return
    if is_server_running(version_id):
        try:
            send_server_command(version_id, f"whitelist add {clean}")
            return
        except RuntimeError:
            pass  # raced a shutdown - fall through to the file write
    entries = _read_whitelist(version_id)
    entries.append({"uuid": offline_uuid(clean), "name": clean})
    _write_whitelist(version_id, entries)


def remove_from_whitelist(version_id: str, name: str) -> None:
    clean = (name or "").strip()
    if is_server_running(version_id):
        try:
            send_server_command(version_id, f"whitelist remove {clean}")
        except RuntimeError:
            pass
    entries = [e for e in _read_whitelist(version_id)
               if str(e.get("name") or "").lower() != clean.lower()]
    _write_whitelist(version_id, entries)
