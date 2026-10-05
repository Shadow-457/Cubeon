"""
Building the launch command and starting the Minecraft process.

launch_game() is the fix point for the other half of the "mods don't load"
bug: it now REQUIRES mc_version/loader (no silent None defaults) and always
threads them into sync_mods_to_game() before the process starts, so the
active profile's enabled mods are guaranteed to be the ones sitting in
MINECRAFT_DIR/mods at launch time - see mods.py's module docstring for the
full story of what was going wrong before.

It's also where the skin/cape setup runs, for the same ordering reason:
CustomSkinLoader has to be in the profile *before* the mods sync, or a jar
downloaded on this launch would only reach the game on the next one. See
cubeon/csl.py.
"""
import logging

import collections
import copy
import inspect
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from functools import wraps

from .atomicio import write_json

# minecraft_launcher_lib costs ~116ms to import (it pulls in requests);
# nothing here needs it until the user actually installs/launches, so it
# is imported on first use. `mll.<anything>` is unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
mll = LazyModule("minecraft_launcher_lib")

from .paths import MINECRAFT_DIR, APP_NAME, CUBEON_HOME
from .config import stable_uuid, save_config, get_system_ram_mb
from .mods import sync_mods_to_game
from . import csl
from .skins import sync_local_skin_to_csl

# How many of the game's last output lines to keep for crash reporting. Enough
# to contain a Java stack trace or a mod-loading error without holding the whole
# log (Minecraft writes megabytes) in memory.
GAME_LOG_TAIL = 200
_spawn_lock = threading.Lock()
_client_json_lock = threading.RLock()
_active_logs = set()
GAME_LOG_LIMIT = 8


def _client_json_transaction(fn):
    @wraps(fn)
    def locked(*args, **kwargs):
        with _client_json_lock:
            return fn(*args, **kwargs)
    return locked


def _prune_game_logs():
    try:
        paths = [os.path.join(CUBEON_HOME, name) for name in os.listdir(CUBEON_HOME)
                 if re.fullmatch(r"game-[0-9a-f]{32}\.log", name)]
        paths.sort(key=os.path.getmtime, reverse=True)
        for path in paths[GAME_LOG_LIMIT:]:
            if path not in _active_logs:
                os.unlink(path)
    except OSError:
        logging.getLogger(__name__).debug("game log pruning failed", exc_info=True)


def _normalize_java_path(path: str) -> str:
    """Accept a JAVA_HOME-style directory anywhere a java executable is expected.

    A user who just installed a JDK very reasonably pastes the JDK folder -
    `C:\\Program Files\\Java\\jdk-21` - into Settings -> java_path (or sets
    JAVA_HOME and expects the same shape to work). Pointing a subprocess at that
    directory fails with a bare WinError 2 / "is a directory", and the
    os.path.isfile() guard then reports "Java N+ wasn't found" on a machine that
    plainly has Java - the same false banner as the JAVA_HOME gap. If it is a
    directory with a java inside bin/, use that; otherwise hand it back
    unchanged so the existing "not found" path still reports it honestly.
    """
    if not path or not os.path.isdir(path):
        return path
    names = ("java.exe", "java") if os.name == "nt" else ("java",)
    for name in names:
        candidate = os.path.join(path, "bin", name)
        if os.path.isfile(candidate):
            return candidate
    return path


def _java_home_binaries() -> list[str]:
    """Candidate `java` executables under JAVA_HOME, if it is set to a real dir.

    JAVA_HOME is the standard way a user points at a JDK, and the launcher
    never read it: resolution was Settings `java_path` -> PATH -> mll's scan.
    So a user who installed Temurin/Adoptium and exported JAVA_HOME (or set
    it in the OS environment after the launcher was already running) was told
    "Java N+ wasn't found" despite visibly having a JDK - the exact report
    behind the two error banners. Kept as a separate helper because both the
    bare `find_java()` fallback and `find_java_for_version()` need it.
    """
    home = (os.environ.get("JAVA_HOME") or "").strip().strip('"').strip("'")
    if not home or not os.path.isdir(home):
        return []
    # On Windows the file is java.exe; probing "bin/java" still works for
    # subprocess (CreateProcess appends .exe) but not for os.path.isfile, so
    # both spellings are offered.
    names = ("java.exe", "java") if os.name == "nt" else ("java",)
    return [os.path.join(home, "bin", name) for name in names]


def find_java() -> str | None:
    for candidate in ("java", "javaw"):
        path = shutil.which(candidate)
        if path:
            return path
    # Nothing on PATH - JAVA_HOME is still a legitimate "the user has Java"
    # signal, and returning None here is what pushes the caller onto the bare
    # "java" fallback (and, for an install, the error banner).
    for path in _java_home_binaries():
        if os.path.isfile(path):
            return path
    return None


def _parse_version(v: str) -> tuple:
    """Turns a Minecraft version string into a sortable int tuple. Handles
    both '1.21.11' and the newer '26.1' style, ignoring non-numeric tails."""
    parts = []
    for piece in str(v).split("."):
        m = re.match(r"(\d+)", piece)
        parts.append(int(m.group(1)) if m else 0)
    return tuple((parts + [0, 0, 0])[:3])


def required_java_major(version_id: str) -> int:
    """Minimum Java major version needed to run a given Minecraft version.

    New Minecraft releases bump the required Java: 1.18 -> 17, 1.20.5 -> 21,
    and 26.1+ -> 25. We key off the version number rather than probing the
    server jar, because the launcher needs to pick the right Java *before*
    it ever tries to start (and a too-old Java just prints the error the user
    pasted)."""
    ver = _parse_version(version_id)
    if ver >= (26, 1):
        return 25
    if ver >= (1, 20, 5):
        return 21
    if ver >= (1, 18, 0):
        return 17
    if ver >= (1, 17, 0):
        return 16
    if ver >= (1, 12, 0):
        return 8
    return 8


def java_major_version(java_path: str) -> int | None:
    """Major version of a Java executable, or None if it can't be probed."""
    try:
        out = subprocess.run(
            [java_path, "-version"], capture_output=True, text=True,
            timeout=8, startupinfo=None,
        ).stderr
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'version "([^"]+)"', out)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith("1."):
        # Old style: "1.8.0_..." -> 8
        tail = raw.split(".")[1] if len(raw.split(".")) > 1 else ""
        return int(tail) if tail.isdigit() else None
    head = raw.split(".")[0]
    return int(head) if head.isdigit() else None


def find_java_for_version(version_id: str, java_path: str | None = None) -> str:
    """Picks the best Java for a server version.

    Prefers the user-supplied path, then the system `java`, then every JVM
    found on the machine (via minecraft_launcher_lib), choosing the highest
    version that meets the minimum for this Minecraft release. Falls back to
    plain `find_java()` so a too-old Java still surfaces Minecraft's own
    (clearer) error rather than silently failing to launch."""
    required = required_java_major(version_id)
    candidates: list[str] = []
    if java_path:
        candidates.append(_normalize_java_path(java_path))
    sys_java = find_java()
    if sys_java:
        candidates.append(sys_java)
    # JAVA_HOME is consulted after PATH, not before: an explicit PATH entry
    # (including the one the OS set for the user's JDK) stays the stronger
    # signal. Order only breaks exact-major ties anyway, since the lowest
    # sufficient major wins below.
    candidates.extend(_java_home_binaries())
    try:
        for d in mll.java_utils.find_system_java_versions():
            candidates.append(os.path.join(d, "bin", "java"))
    except Exception:
        logging.getLogger(__name__).warning("background worker error", exc_info=True)

    # Runtimes Cubeon downloaded itself, LAST. Every real source has been
    # tried by now, so a managed JRE can only ever be reached on a machine
    # that has no usable system Java at all - which is exactly the case the
    # user was prompted about before the install. Ordering it after the rest
    # is what guarantees installing one never changes what a user who already
    # has Java is running.
    try:
        from .jre import installed_runtimes
        managed = installed_runtimes()
        for major in sorted(managed):
            candidates.append(managed[major])
    except Exception:
        logging.getLogger(__name__).debug("managed runtimes unavailable",
                                          exc_info=True)

    best, best_major = None, 10_000
    for c in candidates:
        maj = java_major_version(c)
        if maj is None:
            continue
        # Pick the *lowest* Java that still satisfies the requirement, not the
        # highest: a too-new Java can itself break old Minecraft (removed
        # modules, Nashorn, etc.), so "just enough" is the safe choice.
        if maj >= required and maj < best_major:
            best, best_major = c, maj
    if best:
        return best
    fallback = (_normalize_java_path(java_path) if java_path else None) or sys_java or "java"
    # Honest breadcrumb: we're handing back a Java that may be too old, so
    # Minecraft's own (cryptic) class-version error has a paper trail in the
    # launcher log explaining exactly what was required vs. what was found.
    try:
        logging.getLogger(__name__).warning(
            "no Java >= %s found for %s - falling back to %s (major=%s)",
            required, version_id, fallback, java_major_version(fallback))
    except Exception:
        pass
    return fallback


# Minimal argument set that any modern (1.13+) client needs to start. Used only
# to rebuild a version whose arguments block was emptied by the old sanitizer
# bug - see _restore_emptied_arguments(). Deliberately conservative: it's the
# vanilla template plus the Fabric emulation flag when the profile needs it, and
# nothing pack-specific, because pack-specific flags cannot be recovered.
_VANILLA_GAME_ARGS = [
    "--username", "${auth_player_name}",
    "--version", "${version_name}",
    "--gameDir", "${game_directory}",
    "--assetsDir", "${assets_root}",
    "--assetIndex", "${assets_index_name}",
    "--uuid", "${auth_uuid}",
    "--accessToken", "${auth_access_token}",
    "--versionType", "${version_type}",
    {
        "rules": [{"action": "allow", "features": {"has_custom_resolution": True}}],
        "value": ["--width", "${resolution_width}", "--height", "${resolution_height}"],
    },
]

_VANILLA_JVM_ARGS = [
    {"rules": [{"action": "allow", "os": {"name": "osx"}}], "value": ["-XstartOnFirstThread"]},
    {"rules": [{"action": "allow", "os": {"name": "windows"}}],
     "value": "-XX:HeapDumpPath=MojangTricksIntelDriversForPerformance_javaw.exe_minecraft.exe.heapdump"},
    {"rules": [{"action": "allow", "os": {"arch": "x86"}}], "value": "-Xss1M"},
    "-Djava.library.path=${natives_directory}",
    "-Djna.tmpdir=${natives_directory}",
    "-Dorg.lwjgl.system.SharedLibraryExtractPath=${natives_directory}",
    "-Dio.netty.native.workdir=${natives_directory}",
    "-Dminecraft.launcher.brand=${launcher_name}",
    "-Dminecraft.launcher.version=${launcher_version}",
    "-cp", "${classpath}",
]

# Fabric's KnotClient needs this to report the "real" main class to mods.
_FABRIC_JVM_ARG = "-DFabricMcEmu= net.minecraft.client.main.Main "

# Client-side JVM tuning, appended to every launch. Aimed squarely at the
# thing players read as "low FPS": frame-time spikes. G1GC keeps garbage
# collection off the render frames, and matching -Xms to -Xmx (done in
# build_launch_command) removes the mid-game heap-growth hitches where a long
# session suddenly stutters as the heap resizes.
#
# This is Aikar's well-known client set (github.com/Aikar/timings), trimmed of
# everything that could HURT an ordinary player's machine, per the repo rule
# that performance must never cost stability:
#   - AlwaysPreTouch is OFF by default (below), because committing and
#     faulting the whole heap at startup punishes low-RAM machines and doubles
#     launch time. It is switched ON only for a roomy box (see
#     `_pretouch_flag`): there it is a win, because it moves the page faults
#     out of the first world load - where the heap grows by hundreds of MB in a
#     second - and into startup where nothing is waiting on a frame.
#   - nothing huge for G1HeapRegionSize: a client heap is small;
#   - nothing newer than Java 8 supports, since Cubeon launches versions
#     across Java 8 through 25.
# UnlockExperimentalVMOptions comes FIRST because every G1 tuning flag below
# it is experimental-gated. PerfDisableSharedMem stops the JVM writing perf
# statistics to a mmap'd file, a known source of periodic micro-stutter.
#
# Two flags are deliberately NOT the aggressive server values, because a
# client's render thread shares the CPU with GC and a weak 4-6 core chip is
# exactly where over-eager GC shows up as lost FPS:
#   - G1HeapRegionSize=8M, not 16M. Aikar uses 8M for the client-sized heaps
#     this launcher hands out (half of system RAM, usually 4-8G); 16M makes
#     the young gen coarser and lengthens each young-collection pause.
#   - G1HeapWastePercent=5 is Aikar's value; without it G1 can leave more
#     reclaimable old-gen garbage for longer, triggering more mixed cycles.
# -Dorg.lwjgl.util.NoChecks disables LWJGL's per-call pointer validation,
# which is a small but free CPU saving on the render thread.
#
# Young-gen sizing is CPU-aware (2026-10-05). Aikar's 30-40% young gen assumes
# a server's many GC threads; on a 2-4 thread client one young collection then
# copies hundreds of MB on the same cores the game renders on, and the frame
# time spike is visible. A low core count gets a smaller young gen (20-30%) and
# a shorter pause goal, trading a few more collections for smoother frames.
# `_available_cpus()` honours CPU affinity, so a player who pins the game to
# fewer cores (e.g. `taskset -c 0,1`) gets the low-core tuning automatically.
def _available_cpus() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def client_jvm_flags(cores: int | None = None) -> list:
    """The client GC tuning for a machine with `cores` usable CPUs."""
    cores = cores or _available_cpus()
    if cores <= 4:
        new_pct, max_new_pct, pause_ms = 20, 30, 100
    else:
        new_pct, max_new_pct, pause_ms = 30, 40, 200
    return [
        "-XX:+UseG1GC",
        "-XX:+ParallelRefProcEnabled",
        f"-XX:MaxGCPauseMillis={pause_ms}",
        "-XX:+UnlockExperimentalVMOptions",
        "-XX:+DisableExplicitGC",
        f"-XX:G1NewSizePercent={new_pct}",
        f"-XX:G1MaxNewSizePercent={max_new_pct}",
        "-XX:G1HeapRegionSize=8M",
        "-XX:G1ReservePercent=20",
        "-XX:G1HeapWastePercent=5",
        "-XX:G1MixedGCCountTarget=4",
        "-XX:InitiatingHeapOccupancyPercent=15",
        "-XX:G1MixedGCLiveThresholdPercent=90",
        "-XX:G1RSetUpdatingPauseTimePercent=5",
        "-XX:SurvivorRatio=32",
        "-XX:MaxTenuringThreshold=1",
        "-XX:+PerfDisableSharedMem",
        "-Dorg.lwjgl.util.NoChecks=true",
    ]


# The default (many-core) set, kept as a module constant for callers/tests.
CLIENT_JVM_FLAGS = client_jvm_flags(8)


def _pretouch_flag(ram_mb: int, system_ram_mb: int) -> str | None:
    """`-XX:+AlwaysPreTouch` only when it is safe, else None.

    Pre-touching faults the whole heap in at startup instead of on the render
    thread during the first world load, which is exactly where a 2-core client
    stalls. It costs commit-all-of-Xmx up front and roughly doubles launch
    time, so it is gated to a machine that can afford it: at least 8 GB of
    system RAM AND a heap no larger than half of it. A low-RAM box keeps the
    flag off, which is the original reason the client set omitted it.
    """
    if system_ram_mb >= 8192 and 0 < ram_mb <= system_ram_mb // 2:
        return "-XX:+AlwaysPreTouch"
    return None


@_client_json_transaction
def _restore_emptied_arguments(version_id: str) -> bool:
    """Rebuilds an arguments block that an older Cubeon emptied. Returns True if repaired.

    Cubeon shipped a sanitizer that deleted every argument entry it couldn't
    parse and saved the result. On TLauncher-derived profiles that meant *all*
    of them, so the file on disk now has `{"game": [], "jvm": []}` and the game
    can't start - the classpath argument is gone. The file is already saved, so
    fixing the sanitizer alone doesn't bring these installs back.

    Prefers the backup if one exists. Otherwise reconstructs from the vanilla
    template, which is enough to launch: the pack's own JVM tuning flags
    (GC settings and such) are unrecoverable, but those are performance
    preferences, not launch requirements.
    """
    json_path = os.path.join(MINECRAFT_DIR, "versions", version_id, version_id + ".json")
    if not os.path.isfile(json_path):
        return False

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    arguments = data.get("arguments")
    if not isinstance(arguments, dict):
        return False
    # Only act on the exact damage signature: present but entirely empty.
    if any(v for v in arguments.values() if isinstance(v, list)):
        return False
    if data.get("inheritsFrom"):
        return False  # inherits real arguments from its parent; nothing to rebuild

    backup = json_path + ".cubeon-backup"
    if os.path.isfile(backup):
        try:
            with open(backup, "r", encoding="utf-8") as f:
                original = json.load(f)
            restored = original.get("arguments")
            if isinstance(restored, dict) and any(
                v for v in restored.values() if isinstance(v, list)
            ):
                # Run it back through the (now correct) repair so it's usable.
                data["arguments"] = restored
                _write_client_json(json_path, data)
                _sanitize_client_json(version_id)
                return True
        except (json.JSONDecodeError, OSError):
            pass  # fall through to reconstruction

    jvm = list(_VANILLA_JVM_ARGS)
    main_class = data.get("mainClass") or ""
    if "fabricmc" in main_class or "knot" in main_class.lower():
        jvm.append(_FABRIC_JVM_ARG)

    data["arguments"] = {"game": list(_VANILLA_GAME_ARGS), "jvm": jvm}
    return _write_client_json(json_path, data)


def _write_client_json(json_path: str, data: dict) -> bool:
    """Atomically replaces a client.json. Never leaves a half-written file."""
    try:
        write_json(json_path, data)
        return True
    except OSError:
        return False


def _repair_argument_entry(entry: dict) -> dict | None:
    """Normalizes one argument entry to the shape mll expects, or None to drop it.

    mll reads `entry["value"]` unconditionally and raises a bare
    KeyError('value') on anything else. TLauncher (and packs exported from it)
    write the key as **"values"** instead - same meaning, different name, and
    it's every single entry in the file, `-cp`/`${classpath}` included.

    So the fix is to RENAME, not to delete. An entry with no usable value at
    all is still dropped, since there's nothing to recover from it.
    """
    if "value" in entry:
        return entry

    # TLauncher's spelling. Rename it and keep everything else (rules,
    # compatibilityRules) exactly as it was.
    if "values" in entry:
        fixed = dict(entry)
        fixed["value"] = fixed.pop("values")
        return fixed

    return None  # genuinely nothing to launch with


@_client_json_transaction
def _sanitize_client_json(version_id: str) -> None:
    """Rewrites a version's client.json so mll's command builder can read it.

    Third-party installs (TLauncher, modpacks exported from it, hand-edited
    profiles) ship argument entries keyed "values" where Mojang's schema says
    "value". mll indexes ["value"] directly and dies with KeyError('value').

    HISTORY - this function used to *delete* every entry it couldn't read, and
    then write the file back. Since TLauncher spells EVERY entry "values", that
    deleted the entire arguments block, `-cp` and `${classpath}` with it. The
    game then started with no classpath and died with

        ClassNotFoundException: net.fabricmc.loader.impl.launch.knot.KnotClient

    and because the damage was saved to disk it was permanent - reinstalling
    didn't help, and the file no longer contained what was needed to rebuild it.
    Two of the test machine's modpacks were destroyed this way. Hence:
      * repair (rename) instead of drop, so nothing is lost;
      * never write a file that ends up with fewer arguments than it started
        with - a sanitizer that empties a launch config is broken by
        definition, and refusing to save is always recoverable;
      * back the original up before the first rewrite, so there is a way back
        even if a future bug gets past the check above.
    """
    json_path = os.path.join(MINECRAFT_DIR, "versions", version_id, version_id + ".json")
    if not os.path.isfile(json_path):
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    arguments = data.get("arguments")
    if not isinstance(arguments, dict):
        return

    repaired = copy.deepcopy(arguments)
    changed = False
    dropped = 0

    for key, entries in arguments.items():
        if not isinstance(entries, list):
            continue
        cleaned = []
        for entry in entries:
            if not isinstance(entry, dict):
                cleaned.append(entry)  # plain string argument, already fine
                continue
            fixed = _repair_argument_entry(entry)
            if fixed is None:
                dropped += 1
                changed = True
                continue
            if fixed is not entry:
                changed = True
            cleaned.append(fixed)
        repaired[key] = cleaned

    if not changed:
        return

    # Guard: never save a version whose arguments got emptier. This is the
    # check whose absence destroyed two installs.
    before = sum(len(v) for v in arguments.values() if isinstance(v, list))
    after = sum(len(v) for v in repaired.values() if isinstance(v, list))
    if after < before and dropped:
        # Something in here is unreadable AND unrepairable. Launching may still
        # fail, but a broken file is strictly better than a destroyed one.
        return

    backup = json_path + ".cubeon-backup"
    if not os.path.exists(backup):
        try:
            shutil.copy2(json_path, backup)
        except OSError:
            return  # can't secure a way back, so don't touch the original

    data["arguments"] = repaired
    _write_client_json(json_path, data)


def build_launch_command(version_id: str, username: str, ram_mb: int,
                          width: int, height: int, java_path: str | None = None) -> list[str]:
    _sanitize_client_json(version_id)
    # Undo the damage done by the sanitizer Cubeon used to ship, for anyone
    # whose install it already emptied. No-op on healthy versions.
    _restore_emptied_arguments(version_id)

    jvm_args = [f"-Xmx{ram_mb}M", f"-Xms{ram_mb}M", *client_jvm_flags()]
    try:
        pretouch = _pretouch_flag(ram_mb, get_system_ram_mb())
    except Exception:
        pretouch = None
    if pretouch:
        jvm_args.append(pretouch)

    options = {
        "username": username,
        # The player's stable identity UUID, NOT offline_uuid(username). This is
        # the whole point of auth_key.json: renaming changes the display name but
        # keeps the same UUID, so per-UUID server data (inventory, position) is
        # never orphaned by a name change. offline_uuid() is now only used as a
        # public, name-derived value for the friends registry.
        "uuid": stable_uuid(),
        "token": "0",  # offline/cracked token placeholder
        "launcherName": APP_NAME,
        "launcherVersion": "1.0",
        # -Xms matches -Xmx so the heap never resizes mid-game (the resize is a
        # visible stutter), then the shared client GC tuning rides along.
        # AlwaysPreTouch is added only on a machine that can afford it (see
        # _pretouch_flag) so the first world load does not pay page faults.
        "jvmArguments": jvm_args,
        "customResolution": True,
        "resolutionWidth": str(width),
        "resolutionHeight": str(height),
    }
    if java_path:
        options["executablePath"] = java_path

    try:
        command = mll.command.get_minecraft_command(version_id, MINECRAFT_DIR, options)
    except KeyError as e:
        raise RuntimeError(
            f"This version's client.json has a malformed or non-standard entry "
            f"(missing {e}). It may be a broken or custom launcher install, "
            f"try reinstalling this version, or downloading the vanilla version instead."
        ) from e

    collector = re.compile(r"-XX:[+-]Use(?:G1|Parallel|ParallelOld|Serial|ConcMarkSweep|ParNew|Z|Shenandoah|Epsilon)GC$")
    command = [arg for arg in command if not collector.fullmatch(arg)]
    command.insert(1, "-XX:+UseG1GC")
    return command


def launch_game(version_id: str, username: str, ram_mb: int, width: int, height: int,
                 java_path: str | None, on_exit=None,
                 *, mc_version: str, loader: str,
                 cfg: dict | None = None, status_cb=None, log_cb=None,
                 server_address: str | None = None, server_port: int | None = None) -> subprocess.Popen:
    """
    mc_version and loader are keyword-only and required (no more silent
    `mc_version or version_id` / `loader=None` fallbacks). Mods live in
    per-profile folders (~/.cubeon_launcher/mod_profiles/...) so different
    version+loader combos don't stomp on each other, but the game itself
    only ever reads MINECRAFT_DIR/mods - so the active profile's enabled
    jars must be synced there before every launch, and that sync has to
    know the REAL loader, not "whatever happened to default to None".

    cfg is optional so old call sites keep working, but passing it is what
    enables the skin/cape setup: CustomSkinLoader gets downloaded into the
    profile and the active skin is re-mirrored under the current username.
    Both happen BEFORE sync_mods_to_game(), so a jar fetched right now still
    lands in MINECRAFT_DIR/mods for this same launch rather than the next one.

    log_cb, if given, receives each line the game writes. on_exit receives
    (returncode, last_lines) so a crash can be explained; a one-argument
    on_exit(returncode) is still accepted.
    """
    if cfg is not None:
        # Offline skins are keyed by username, so the file CSL looks for is
        # <USERNAME>.png. Re-syncing here covers any path that changed the
        # name or the skin without going through set_active_skin().
        before = cfg.get("csl_synced_name")
        sync_local_skin_to_csl(cfg)
        if cfg.get("csl_synced_name") != before:
            save_config(cfg)

        # Same for the active cape - LocalSkin/capes/<USERNAME>.png.
        from .capes import sync_local_cape_to_csl
        cape_before = cfg.get("csl_synced_cape_name")
        sync_local_cape_to_csl(cfg)
        if cfg.get("csl_synced_cape_name") != cape_before:
            save_config(cfg)

        # Best-effort: never let a skin-mod problem stop the game launching.
        try:
            csl.ensure_ready(
                mc_version, loader,
                manage=bool(cfg.get("manage_skin_mod", True)),
                status_cb=status_cb,
            )
        except Exception:
            pass

    # Ship the in-game Cubeon Client mod into the Fabric profile so the
    # Friends button exists in Minecraft's game menu. Best-effort, always
    # before the mods sync so a fresh drop is live this launch.
    try:
        from .features import friends_enabled
        from .mods import get_profile_dir
        from . import cubeonfriends
        _profile_dir = get_profile_dir(mc_version, loader)
        if not friends_enabled() or not (cfg or {}).get("client_mod_enabled", True):
            # Off: either a public build (no Friends backend at all) or the
            # user's Settings toggle. Both must also REMOVE any jar a
            # previous run left behind - a stale copy would still load.
            cubeonfriends.remove_installed(_profile_dir)
        else:
            friends_ok = cubeonfriends.ensure_installed(mc_version, loader,
                                           _profile_dir)
            if not friends_ok and status_cb and loader in ("fabric", "quilt"):
                status_cb("Cubeon Friends mod not built for this Minecraft "
                          "version - the in-game Friends button will be missing")
    except Exception:
        logging.getLogger(__name__).warning("friends mod setup failed", exc_info=True)

    # The Cubeon Client is a social mod and draws almost nothing; the actual
    # frame-rate win comes from the client performance mod suite (Sodium,
    # Lithium, ImmediatelyFast, EntityCulling, MoreCulling, ...) fetched here
    # for the same profile, plus unlocking Minecraft's own Vsync/FPS-cap
    # options so those mods can actually be seen. Tied to the client toggle
    # (there is no separate switch in Settings - the user asked for that gone;
    # `perf_mods_enabled` remains a config-only opt-out), and always before
    # the mods sync so a jar fetched right now is live this launch.
    try:
        if (cfg is not None and cfg.get("client_mod_enabled", True)
                and cfg.get("perf_mods_enabled", True)):
            from . import perf_mods
            report = perf_mods.ensure_installed(mc_version, loader,
                                                status_cb=status_cb)
            if report["installed"] and status_cb:
                status_cb("FPS boost installed")
            # The suite was narrowed to Sodium only; remove the retired mods so
            # an existing profile stops loading the pile instead of leaving the
            # user to delete eight jars by hand.
            pruned = perf_mods.prune_retired_perf_mods(mc_version, loader)
            if pruned and status_cb:
                status_cb("Removed extra perf mods")
            # The game is not running yet (the JVM starts further down), so
            # options.txt can be edited safely. This is what stops a machine
            # that CAN render 120 FPS from still reading 60/30 because of
            # Vsync and the frame cap.
            from . import game_options
            unlocked = game_options.unlock_frame_rate()
            if unlocked["changed"] and status_cb:
                status_cb("Frame rate unlocked")
    except Exception:
        pass

    # EntityCulling ships with a whitelist that can hold a null/empty entry in
    # a legacy config, which crashes the game on its first tick (see
    # perf_mods.sanitize_entityculling_config). Repair it whenever the mod is
    # present - even if the perf suite is switched off - because a stale broken
    # config would otherwise keep crashing an install the user already has.
    try:
        from . import perf_mods
        repaired = perf_mods.sanitize_entityculling_config()
        if repaired["removed"]:
            logging.getLogger(__name__).warning(
                "repaired EntityCulling config: %s", repaired["detail"])
    except Exception:
        pass

    command = build_launch_command(version_id, username, ram_mb, width, height, java_path)

    # Optional direct-connect arguments. Minecraft's client accepts these as
    # launch arguments, which lets features such as P2P hand the player
    # straight into a freshly-created local relay instead of requiring a
    # second manual "Direct Connect" step. Normal launches are unchanged.
    if server_address:
        command.extend(["--server", str(server_address)])
        if server_port is not None:
            command.extend(["--port", str(int(server_port))])

    # The game must SURVIVE the launcher. Two things used to tie its life to
    # ours, so closing the launcher (or the terminal it was started from)
    # took Minecraft down with it:
    #
    #   1. stdout was a PIPE owned by this process. When the launcher exits
    #      the read end dies, and the game's next log write hits a broken
    #      pipe - at best its logging breaks, at worst the JVM goes down.
    #      Fixed by giving the game a real FILE for stdout: nothing the
    #      launcher does can invalidate it, and the user gets a game log.
    #   2. the game shared our process group and terminal session, so a
    #      SIGHUP/SIGINT aimed at the launcher (terminal closed, shell job
    #      killed, desktop session tidying up) was delivered to it too.
    #      start_new_session=True puts it in its own session/group, which is
    #      exactly what a real launcher does.
    #
    # stdin is /dev/null for the same reason: an inherited terminal stdin
    # would make the game a background-job SIGTTIN casualty.
    session_id = uuid.uuid4().hex
    log_path = os.path.join(CUBEON_HOME, f"game-{session_id}.log")
    try:
        os.makedirs(CUBEON_HOME, exist_ok=True)
        log_fh = open(log_path, "wb")
    except OSError:
        log_fh = None  # unwritable HOME: fall back to discarding output

    popen_kwargs = {}
    if os.name == "nt":
        # Packaged Windows launchers are commonly started from a console or
        # from an installer-created process tree.  A normal Popen child then
        # inherits the console/job and Task Manager presents Minecraft as a
        # Cubeon child.  Start it in a detached process group with no console
        # of its own.  CREATE_BREAKAWAY_FROM_JOB is best effort: Windows
        # refuses it when the parent job does not allow breakaway, but the
        # other flags still keep the game independent of the launcher's UI.
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        popen_kwargs["creationflags"] = creationflags
        popen_kwargs["close_fds"] = True
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        popen_kwargs["startupinfo"] = startupinfo
    elif hasattr(os, "setsid"):
        # A separate session/group prevents terminal shutdown and launcher
        # signals from taking Minecraft down with them.
        popen_kwargs["start_new_session"] = True

    # The launcher may be running on SOFTWARE OpenGL (its own crash fallback:
    # if the GPU driver killed the flet client, main.py arms LIBGL_ALWAYS_
    # SOFTWARE=1 for itself and re-execs). The game must NEVER inherit that:
    # Minecraft on llvmpipe is ~4 FPS, and the game has its own GL stack that
    # doesn't share the launcher's driver bug. Strip the software-GL vars from
    # the child environment while passing everything else through.
    # CUBEON_GPU_RESTARTS is main.py's re-exec crash budget (how many times
    # the launcher UI restarted due to driver death). It exists ONLY so a
    # wedged driver can't loop re-execs forever - it must never reach the
    # game, or any game that probes its environment for namespaced
    # CUBEON_* knobs sees a stale restart count as a knob.
    _game_env = {k: v for k, v in os.environ.items()
                 if k not in ("LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER",
                              "LIBGL_DRM_DEVICE", "CUBEON_GPU_RESTARTS")}
    popen_kwargs["env"] = _game_env

    from . import watchdog
    try:
        with _spawn_lock:
            try:
                from .content import sync_content_to_game
                sync_content_to_game(mc_version, loader)
            except Exception:
                logging.getLogger(__name__).warning("content staging failed", exc_info=True)
            try:
                from .doctor import run_doctor
                report = run_doctor(mc_version, loader, auto_fix=True,
                                    check_online=False, version_id=version_id,
                                    include=("mods", "resourcepacks", "shaders"))
                fixed = len(report.get("fixed") or [])
                if fixed and status_cb:
                    status_cb(f"Fixed {fixed} content problem(s)")
            except Exception:
                logging.getLogger(__name__).warning("launch doctor failed", exc_info=True)
            sync_mods_to_game(mc_version, loader)
            process = subprocess.Popen(
                command,
                cwd=MINECRAFT_DIR,
                stdin=subprocess.DEVNULL,
                stdout=(log_fh or subprocess.DEVNULL),
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )
            process.session_id = session_id
            _active_logs.add(log_path)
            _prune_game_logs()
            try:
                watchdog.register(process.pid, version_id, username,
                                  process=process, session_id=session_id)
            except Exception:
                logging.getLogger(__name__).debug("game metadata registration failed", exc_info=True)
    except BaseException:
        if log_fh is not None:
            log_fh.close()
        try:
            os.unlink(log_path)
        except OSError:
            pass
        raise
    finally:
        if log_fh is not None:
            log_fh.close()
    try:
        from .friends_service import FriendsService
        FriendsService.reconcile_username_active()
    except Exception:
        logging.getLogger(__name__).debug("game username reconciliation failed", exc_info=True)

    # We still want the game's output live (progress + the last lines to show
    # when a launch fails), so we TAIL the log file instead of owning a pipe.
    recent = collections.deque(maxlen=GAME_LOG_TAIL)

    def _drain():
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                while True:
                    line = fh.readline()
                    if line:
                        line = line.rstrip()
                        if line:
                            recent.append(line)
                            if log_cb:
                                log_cb(line)
                        continue
                    if process.poll() is not None:
                        # Dead: one final sweep so a crash report isn't cut
                        # off mid-write, then stop tailing.
                        for last in fh.read().splitlines():
                            last = last.rstrip()
                            if last:
                                recent.append(last)
                                if log_cb:
                                    log_cb(last)
                        return
                    time.sleep(0.2)
        except OSError:
            pass  # no log file (unwritable HOME): the game still runs

    drain = threading.Thread(target=_drain, name="mc-stdout", daemon=True)
    drain.start()

    # Playtime: persist the session start next to the watchdog record. The
    # in-process on_exit watcher credits and clears it on a clean exit; if the
    # launcher is re-exec'd/crashes first, the next startup reconciles it (see
    # milestones.reconcile_play_session) so the game's time isn't lost.
    from . import milestones
    milestones.begin_play_session(process.pid, None, session_id)

    def _watch():
        process.wait()
        try:
            watchdog.clear(session_id)
            from .friends_service import FriendsService
            FriendsService.reconcile_username_active()
        except Exception:
            logging.getLogger(__name__).debug("game exit reconciliation failed", exc_info=True)
        # Let the reader finish flushing what the game wrote on its way out,
        # so a crash report isn't truncated. Bounded so a stuck pipe can't
        # keep this thread alive forever.
        drain.join(timeout=5.0)
        milestones.end_play_session(session_id=session_id)
        with _spawn_lock:
            _active_logs.discard(log_path)
            _prune_game_logs()
        if on_exit:
            _call_on_exit(on_exit, process.returncode, list(recent), session_id)
    threading.Thread(target=_watch, daemon=True).start()

    return process


def _call_on_exit(on_exit, code: int, lines: list[str], session_id=None) -> None:
    """Calls on_exit(code, lines), falling back to on_exit(code).

    The second argument was added so a failed launch can show the game's own
    error output instead of just a number. Callers written against the old
    one-argument form still work rather than dying with a TypeError inside a
    daemon thread, where nobody would ever see it.
    """
    try:
        count = len(inspect.signature(on_exit).parameters)
    except (TypeError, ValueError):
        count = 1
    if count >= 3:
        on_exit(code, lines, session_id)
    elif count >= 2:
        on_exit(code, lines)
    else:
        on_exit(code)
