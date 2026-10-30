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
import shlex
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

from .paths import (MINECRAFT_DIR, APP_NAME, CUBEON_HOME, game_dir_for,
                    set_active_game_dir)
from .config import stable_uuid, save_config, get_system_ram_mb
from .mods import sync_mods_to_game
from .mod_loaders import MOD_CAPABLE_LOADERS
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
    # Loader and isolated instance ids are not release numbers. Resolve their
    # own base before choosing a JVM (fabric-loader-... previously chose Java 8).
    from .versions import extract_mc_version
    ver = _parse_version(extract_mc_version(version_id))
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
        from .winproc import hidden
        out = subprocess.run(
            [java_path, "-version"], capture_output=True, text=True,
            timeout=8, **hidden(),
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
# collection off the render frames, and a deliberately small -Xms (see
# `_initial_heap_mb`) lets the heap grow into -Xmx instead of committing and
# faulting all of it up front.
#
# This started as Aikar's well-known set (github.com/Aikar/timings) and has
# been pulled back to a CLIENT tuning, per the repo rule that performance must
# never cost stability. Aikar's numbers are a *server* profile: a server
# optimises throughput and its GC threads have nothing else to do, whereas on a
# client GC competes with the render thread for the same cores. The values
# below that differ from Aikar's are called out where they are set, and the
# remaining trim is:
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
# YOUNG-GEN SIZING IS THE CLIENT FIX (2026-10-14). This is a CLIENT set, not
# Aikar's server set. Aikar sizes the young generation at 30-40% of the heap
# because a server optimises throughput and its GC threads are otherwise idle.
# On a client the GC shares cores with the render thread, so a big young gen
# makes G1 wait until eden is ~30% of the heap before collecting: heap climbs to
# ~50% before it "cleans" (exactly the "why does Cubeon clean at 50%+" report)
# and every collection copies hundreds of MB on the frames' cores. At 10% young
# GCs run earlier and are small. `_available_cpus()` honours CPU affinity, so a
# player who pins the game to fewer cores (e.g. `taskset -c 0,1`) gets the
# shorter pause goal automatically.
def _available_cpus() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


# Young generation's floor, as a percentage of the heap. The JVM's own default
# is 5; 10 keeps collections early without making them constant.
G1_NEW_SIZE_PERCENT = 10


def client_jvm_flags(cores: int | None = None) -> list:
    """The client GC tuning for a machine with `cores` usable CPUs."""
    cores = cores or _available_cpus()
    max_new_pct, pause_ms = (30, 100) if cores <= 4 else (40, 200)
    return [
        "-XX:+UseG1GC",
        "-XX:+ParallelRefProcEnabled",
        f"-XX:MaxGCPauseMillis={pause_ms}",
        "-XX:+UnlockExperimentalVMOptions",
        "-XX:+DisableExplicitGC",
        f"-XX:G1NewSizePercent={G1_NEW_SIZE_PERCENT}",
        f"-XX:G1MaxNewSizePercent={max_new_pct}",
        "-XX:G1HeapRegionSize=8M",
        # Reserve / concurrent-marking threshold / tenuring moved off Aikar's
        # server values onto the JVM's own client-sane defaults: a 20% reserve
        # and concurrent marking starting at 15% heap both put GC work on the
        # cores the render thread wants, and SurvivorRatio=32 with
        # MaxTenuringThreshold=1 promotes almost everything straight to the old
        # generation - buying more (and costlier) mixed collections than it
        # saves.
        "-XX:G1ReservePercent=10",
        "-XX:G1HeapWastePercent=5",
        "-XX:G1MixedGCCountTarget=4",
        "-XX:InitiatingHeapOccupancyPercent=45",
        "-XX:G1MixedGCLiveThresholdPercent=90",
        "-XX:G1RSetUpdatingPauseTimePercent=5",
        "-XX:SurvivorRatio=8",
        "-XX:MaxTenuringThreshold=15",
        "-XX:+PerfDisableSharedMem",
        "-Dorg.lwjgl.util.NoChecks=true",
    ]


# The default (many-core) set, kept as a module constant for callers/tests.
CLIENT_JVM_FLAGS = client_jvm_flags(8)


# Initial heap. Deliberately NOT equal to -Xmx (2026-10-14): -Xms==-Xmx commits
# the whole heap up front - F3 shows "Allocated: 100%" - and pins RSS for the
# whole session, which is what makes Cubeon look like it hoards memory next to a
# client that starts small and grows. A modest -Xms lets the JVM grow into -Xmx
# as the player actually needs it; growing is free (no pause).
INITIAL_HEAP_MB = 512


def _initial_heap_mb(ram_mb: int) -> int:
    """Starting heap for a given -Xmx: the fixed start, but never more than half
    the ceiling, so a tiny -Xmx is not given a bigger -Xms."""
    return max(256, min(INITIAL_HEAP_MB, max(1, ram_mb // 2)))


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


# Why each default exists, for Settings > Java > "Cubeon's defaults". Keyed by
# the flag itself so the report is built FROM `client_jvm_flags()` and cannot
# drift: an unknown flag is still listed, just without a sentence.
_JVM_FLAG_NOTES = {
    "-Xmx":
        "The memory ceiling, taken from your Allocated RAM slider.",
    "-Xms":
        "Starting heap. Deliberately smaller than -Xmx, so the JVM grows into "
        "the ceiling as you need it instead of committing all of it up front.",
    "-XX:+UseG1GC":
        "Selects G1, which combines concurrent work with collection pauses.",
    "-XX:+ParallelRefProcEnabled":
        "Processes soft/weak references on several threads at once, shortening "
        "each pause.",
    "-XX:MaxGCPauseMillis=":
        "The pause goal G1 aims for. 100 ms on a 4-core-or-less machine, "
        "200 ms on a bigger one.",
    "-XX:+UnlockExperimentalVMOptions":
        "Required before any of the G1 tuning below can be set at all.",
    "-XX:+DisableExplicitGC":
        "Ignores System.gc() calls, which cause a full stop-the-world pause.",
    "-XX:G1NewSizePercent=":
        "Young-generation floor as a share of the heap. Small on purpose: a "
        "big young gen makes G1 wait, then copy hundreds of MB at once.",
    "-XX:G1MaxNewSizePercent=":
        "Young-generation ceiling. 30% on 4 cores or fewer, 40% above that.",
    "-XX:G1HeapRegionSize=8M":
        "Region size for a client-sized heap. 16M would make young collections "
        "coarser and longer.",
    "-XX:G1ReservePercent=10":
        "How much heap G1 holds back for promotion. Left at a client-sane "
        "value rather than a server's.",
    "-XX:G1HeapWastePercent=5":
        "How much reclaimable garbage G1 tolerates before a mixed cycle.",
    "-XX:G1MixedGCCountTarget=4":
        "Spreads old-generation collection over several smaller cycles instead "
        "of one long one.",
    "-XX:InitiatingHeapOccupancyPercent=45":
        "Heap fullness at which concurrent marking starts.",
    "-XX:G1MixedGCLiveThresholdPercent=90":
        "Skips regions that are nearly all live, since collecting them saves "
        "almost nothing.",
    "-XX:G1RSetUpdatingPauseTimePercent=5":
        "Caps how much of a pause may go to remembered-set updates.",
    "-XX:SurvivorRatio=8":
        "Eden-to-survivor split. Deliberately not Aikar's 32, which promotes "
        "almost everything straight to the old generation.",
    "-XX:MaxTenuringThreshold=15":
        "How long an object may age in survivor space before promotion.",
    "-XX:+PerfDisableSharedMem":
        "Disables the shared-memory JVM performance statistics file.",
    "-Dorg.lwjgl.util.NoChecks=true":
        "Disables LWJGL runtime checks.",
    "-XX:+AlwaysPreTouch":
        "Pre-touches committed heap pages at startup. Added with at least "
        "8 GB system RAM when the selected heap is no more than half of it.",
}


def _jvm_flag_note(flag: str) -> str:
    """The one-line reason for a default flag, or '' if we have none.

    Prefix-matched so the flags that carry a value (`-XX:MaxGCPauseMillis=200`)
    still find their sentence.
    """
    if flag in _JVM_FLAG_NOTES:
        return _JVM_FLAG_NOTES[flag]
    # Flags that carry a value ("-Xmx4096M", "-XX:MaxGCPauseMillis=200") are
    # keyed by their prefix. An exact match above always wins first, so a
    # prefix can never shadow a fuller flag.
    for prefix, note in _JVM_FLAG_NOTES.items():
        if flag.startswith(prefix):
            return note
    return ""


def default_jvm_flags_report(ram_mb: int | None = None, *,
                             system_ram_mb: int | None = None,
                             cores: int | None = None,
                             custom_jvm_flags: str | None = None,
                             default_jvm_flags_enabled: bool = True) -> list[dict]:
    """The default JVM flags Cubeon adds to a launch, with why each is there.

    Built from the SAME functions `build_launch_command` uses
    (`_initial_heap_mb`, `client_jvm_flags`, `_pretouch_flag`), so the Settings
    panel cannot drift from what actually launches. That is the whole point of
    routing it through here instead of restating a list in the UI.

    Each entry is ``{"flag", "note", "source"}`` where `source` is:
      - ``"always"``      added on every launch;
      - ``"conditional"`` added only on a machine that can afford it;
      - ``"dropped"``     a default Cubeon would add but is NOT adding here.

    ``ram_mb`` is the player's maximum RAM; omitted, only the flags that do
    not depend on it are reported. Never raises: this is a readout, and a
    machine that cannot report its own RAM must still get the rest of the list.
    """
    out: list[dict] = []

    def add(flag: str, source: str) -> None:
        out.append({"flag": flag, "note": _jvm_flag_note(flag), "source": source})

    # A collector the player typed in Settings wins, and Cubeon drops its own
    # G1 choice AND its G1-only tuning with it (they are not valid for another
    # collector). Mirrors build_launch_command's own rule.
    collector = re.compile(
        r"-XX:[+-]Use(?:G1|Parallel|ParallelOld|Serial|ConcMarkSweep|ParNew"
        r"|Z|Shenandoah|Epsilon)GC$")
    user_collector = None
    try:
        user_collector = next(
            (f for f in _parse_custom_jvm_flags(custom_jvm_flags)
             if collector.fullmatch(f)), None)
    except Exception:
        user_collector = None
    own_collector = bool(user_collector and user_collector != "-XX:+UseG1GC")

    if ram_mb:
        try:
            ram = max(1, int(ram_mb))
            custom_heap = _custom_heap_flags(_parse_custom_jvm_flags(custom_jvm_flags))
            defaults = _launcher_heap_flags(ram, custom_heap)
            for kind, flag in defaults.items():
                if kind in custom_heap:
                    out.append({"flag": flag, "source": "dropped",
                                "note": _jvm_flag_note(flag) +
                                f" Replaced by your custom flag {custom_heap[kind]}."})
                else:
                    add(flag, "always")
        except (TypeError, ValueError):
            pass

    for flag in client_jvm_flags(cores):
        if own_collector and (collector.fullmatch(flag)
                              or flag.startswith("-XX:G1")):
            # Reported as dropped rather than hidden: a player who chose ZGC
            # should be able to see that Cubeon stepped aside, not wonder
            # where the tuning went.
            out.append({"flag": flag, "note": _jvm_flag_note(flag),
                        "source": "dropped"})
            continue
        add(flag, "always")

    if ram_mb:
        try:
            sys_ram = (get_system_ram_mb() if system_ram_mb is None
                       else int(system_ram_mb))
            pretouch = _pretouch_flag(max(1, int(ram_mb)), sys_ram)
            if pretouch:
                add(pretouch, "conditional")
            else:
                out.append({"flag": "-XX:+AlwaysPreTouch",
                            "note": _jvm_flag_note("-XX:+AlwaysPreTouch")
                            + " Skipped here: it needs at least 8 GB of system "
                              "RAM and a heap no larger than half of it.",
                            "source": "dropped"})
        except Exception:
            logging.getLogger(__name__).debug(
                "could not resolve the AlwaysPreTouch default", exc_info=True)
    if not default_jvm_flags_enabled:
        for entry in out:
            entry["source"] = "dropped"
            entry["note"] += " Not added: Cubeon's default flags are switched off."
    return out


def _default_client_jvm_arguments(ram_mb: int, user_flags: list[str], *,
                                  enabled: bool = True) -> list[str]:
    """Launch and Settings share the same default flag assembly."""
    return [entry["flag"] for entry in default_jvm_flags_report(
        ram_mb, custom_jvm_flags=shlex.join(user_flags),
        default_jvm_flags_enabled=enabled)
        if entry["source"] != "dropped"]


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


# JVM options that take their VALUE as the next argv token. Without this list
# a legitimate `--add-opens java.base/java.lang=ALL-UNNAMED` would lose its
# value when non-flag tokens are stripped (see _parse_custom_jvm_flags).
_JVM_VALUE_OPTIONS = frozenset({
    "-cp", "-classpath", "--class-path",
    "-p", "--module-path", "--upgrade-module-path",
    "--add-opens", "--add-exports", "--add-reads", "--patch-module",
    "--limit-modules", "--enable-native-access",
    "-javaagent", "-agentlib", "-agentpath",
})


def _split_custom_jvm_flags(raw: str | None) -> list[str]:
    """Quote-aware split; an unbalanced quote falls back to whitespace."""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


def _filter_jvm_tokens(tokens) -> tuple[list[str], list[str]]:
    """(usable flags, rejected tokens).

    A custom-flags string is spliced into the JVM argv before the main class.
    Any bare token that is not the value of a preceding option is therefore
    read by Java as the MAIN CLASS - which is exactly how a config holding
    ``custom_jvm_flags: "他他他"`` crashed Minecraft 26.3 with
    ``ClassNotFoundException: 他他他`` (2026-10-25). Reject those tokens
    instead of handing them to Popen.
    """
    kept: list[str] = []
    dropped: list[str] = []
    expect_value = False
    for token in tokens:
        if expect_value:
            kept.append(token)
            expect_value = False
            continue
        if token.startswith("-"):
            kept.append(token)
            expect_value = token in _JVM_VALUE_OPTIONS
        else:
            dropped.append(token)
    return kept, dropped


def invalid_custom_jvm_flags(raw: str | None) -> list[str]:
    """Tokens in `raw` that would be mistaken for the main class.

    Exposed for the doctor, which reports/fixes a config that would crash the
    next launch.
    """
    return _filter_jvm_tokens(_split_custom_jvm_flags(raw))[1]


def _parse_custom_jvm_flags(raw: str | None) -> list[str]:
    """Split a user-supplied JVM-flag string into safe argv pieces.

    Quotes are respected (`-Dfoo="a b"` stays one arg); an unbalanced quote
    falls back to a naive whitespace split so a typo can never abort a launch.
    Non-option tokens are dropped - see _filter_jvm_tokens for why.
    """
    kept, dropped = _filter_jvm_tokens(_split_custom_jvm_flags(raw))
    if dropped:
        logging.getLogger(__name__).warning(
            "Ignoring invalid custom JVM flag token(s) %r - they would "
            "be read as the main class", dropped)
    return kept


def _jvm_option_positions(tokens: list[str], start: int = 0):
    """Visit options before the main class, skipping separate option values."""
    index = start
    while index < len(tokens):
        token = tokens[index]
        if (not token.startswith("-") or token in ("-jar", "-m", "--module")
                or token.startswith("--module=")):
            break
        yield index
        index += 2 if token in _JVM_VALUE_OPTIONS else 1


def _heap_kind(flag: str) -> str | None:
    if flag.startswith(("-Xmx", "-XX:MaxHeapSize=")):
        return "maximum"
    if flag.startswith(("-Xms", "-XX:InitialHeapSize=")):
        return "initial"
    return None


def _heap_size_mb(flag: str) -> float | None:
    """Read Java heap sizes, including byte values and K/M/G/T suffixes."""
    value = flag.split("=", 1)[1] if "=" in flag else flag[4:]
    match = re.fullmatch(r"(\d+)([kKmMgGtT]?)", value)
    if not match:
        return None
    return int(match[1]) * {"": 1 / 1048576, "k": 1 / 1024,
                           "m": 1, "g": 1024, "t": 1048576}[match[2].lower()]


def _custom_heap_flags(user_flags: list[str]) -> dict[str, str]:
    chosen = {}
    for index in _jvm_option_positions(user_flags):
        flag = user_flags[index]
        kind = _heap_kind(flag)
        if kind:
            chosen[kind] = flag  # Java's last explicit setting wins.
    return chosen


def _launcher_heap_flags(ram_mb: int, custom_heap: dict[str, str]) -> dict[str, str]:
    ram = max(1, int(ram_mb))
    initial = _initial_heap_mb(ram)
    if "maximum" in custom_heap:
        maximum = _heap_size_mb(custom_heap["maximum"])
        if maximum is not None and maximum > 0:
            initial = max(1, min(initial, int(maximum)))
    return {"maximum": f"-Xmx{ram}M", "initial": f"-Xms{initial}M"}


def memory_limit_report(ram_mb: int, *, custom_jvm_flags: str | None = None,
                        default_jvm_flags_enabled: bool = True) -> dict:
    """Settings' heap ceiling, using the same precedence as command assembly."""
    custom = _custom_heap_flags(_parse_custom_jvm_flags(custom_jvm_flags))
    if "maximum" in custom:
        flag = custom["maximum"]
        return {"source": "custom", "flag": flag, "ram_mb": _heap_size_mb(flag)}
    if default_jvm_flags_enabled:
        flag = _launcher_heap_flags(ram_mb, custom)["maximum"]
        return {"source": "slider", "flag": flag, "ram_mb": _heap_size_mb(flag)}
    return {"source": "profile", "flag": None, "ram_mb": None}


def _normalize_heap_arguments(command: list[str], ram_mb: int,
                              user_flags: list[str], enabled: bool) -> list[str]:
    """Profile/inherited JVM defaults must not override launcher heap choices.

    mll appends the profile's arguments after our jvmArguments. Normalize only
    JVM options, leaving classpath/module values and all game arguments intact.
    With defaults disabled, only explicitly customized heap sizes are owned.
    """
    chosen = _custom_heap_flags(user_flags)
    if enabled:
        chosen = {**_launcher_heap_flags(ram_mb, chosen), **chosen}
    if not chosen:
        return command
    remove = {index for index in _jvm_option_positions(command, 1)
              if _heap_kind(command[index]) in chosen}
    return [command[0], *chosen.values(),
            *(token for index, token in enumerate(command[1:], 1) if index not in remove)]


def build_launch_command(version_id: str, username: str, ram_mb: int,
                          width: int, height: int, java_path: str | None = None,
                          custom_jvm_flags: str | None = None,
                          game_dir: str | None = None,
                          default_jvm_flags_enabled: bool = True) -> list[str]:
    """The full java command. `game_dir` is the instance's own folder (see
    paths.game_dir_for); omitted -> the shared root, which is what every
    non-launch caller and the tests still want."""
    _sanitize_client_json(version_id)
    # Undo the damage done by the sanitizer Cubeon used to ship, for anyone
    # whose install it already emptied. No-op on healthy versions.
    _restore_emptied_arguments(version_id)

    # User flags ride along AFTER the tuned defaults so they can override them
    # (the JVM honors the last of a repeated flag). mll places everything in
    # jvmArguments before the main class, so they land in the right spot.
    user_flags = _parse_custom_jvm_flags(custom_jvm_flags)
    jvm_args = [*_default_client_jvm_arguments(ram_mb, user_flags,
                                             enabled=default_jvm_flags_enabled), *user_flags]

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
        # -Xms is deliberately SMALLER than -Xmx so the JVM grows into the
        # ceiling on demand, then the shared client GC tuning rides along.
        # AlwaysPreTouch is added only on a machine that can afford it (see
        # _pretouch_flag) so the first world load does not pay page faults.
        "jvmArguments": jvm_args,
        "customResolution": True,
        "resolutionWidth": str(width),
        "resolutionHeight": str(height),
        # mll substitutes this into the profile's --gameDir. Without it every
        # instance shared one saves/ and config/ (see paths.INSTANCES_GAME_DIR).
        "gameDirectory": game_dir or MINECRAFT_DIR,
    }
    # Only hand mll a Java that actually exists. A typo'd / cleared Settings
    # path used to go straight into executablePath, and Popen then died with
    # FileNotFoundError on the garbage string (2026-10-25: java_path was
    # "他他他"). A missing configured path now falls back to the same
    # resolution the Java check uses, so the game still starts on a machine
    # that plainly has Java.
    java = None
    if java_path:
        candidate = _normalize_java_path(java_path)
        if os.path.isfile(candidate) or shutil.which(candidate):
            major = java_major_version(candidate)
            if major is None or major >= required_java_major(version_id):
                java = candidate
    if java is None:
        try:
            java = find_java_for_version(version_id, None)
        except Exception:
            java = find_java()
    if java:
        options["executablePath"] = java

    try:
        command = mll.command.get_minecraft_command(version_id, MINECRAFT_DIR, options)
    except KeyError as e:
        raise RuntimeError(
            f"This version's client.json has a malformed or non-standard entry "
            f"(missing {e}). It may be a broken or custom launcher install, "
            f"try reinstalling this version, or downloading the vanilla version instead."
        ) from e

    command = _normalize_heap_arguments(command, ram_mb, user_flags,
                                        default_jvm_flags_enabled)

    collector = re.compile(r"-XX:[+-]Use(?:G1|Parallel|ParallelOld|Serial|ConcMarkSweep|ParNew|Z|Shenandoah|Epsilon)GC$")
    # A collector the player typed in Settings is a deliberate choice, not a
    # stale default: forcing G1 over it made ZGC/Shenandoah/Parallel silently
    # do nothing. Keep theirs, and drop Cubeon's G1 choice AND its G1-only
    # tuning flags (they are not valid for another collector). With no user
    # collector the old behaviour stands: strip whatever the profile carried
    # and put exactly one G1 in.
    user_collector = next((flag for flag in user_flags if collector.fullmatch(flag)),
                          None)
    if user_collector and user_collector != "-XX:+UseG1GC":
        command = [arg for arg in command
                   if not (collector.fullmatch(arg) and arg != user_collector)
                   and not arg.startswith("-XX:G1")]
    elif default_jvm_flags_enabled:
        command = [arg for arg in command if not collector.fullmatch(arg)]
        command.insert(1, "-XX:+UseG1GC")
    elif user_collector:
        command = [arg for arg in command
                   if not collector.fullmatch(arg) or arg == user_collector]

    # minecraft_launcher_lib 8.0's replace_arguments() does NOT know
    # ${clientid} / ${auth_xuid} (vanilla placeholders tied to Microsoft
    # account plumbing). Cubeon is offline-only, so those tokens are never
    # substituted and ship through as the LITERAL strings "${clientid}" /
    # "${auth_xuid}". They are not what causes "Invalid session" (that is
    # the offline accessToken "0" being rejected by an online-mode server's
    # session check, which no launcher can fix) - but leaving them means the
    # game is handed garbage where a real clientId/xuid would go. Drop the
    # flag+placeholder pairs so the game never sees them.
    scrub = re.compile(r"^\$\{.+\}$")
    cleaned: list[str] = []
    i = 0
    while i < len(command):
        arg = command[i]
        # Flag immediately followed by an unresolved ${...} placeholder: drop both.
        if arg.startswith("--") and i + 1 < len(command) and scrub.fullmatch(command[i + 1]):
            i += 2
            continue
        # A bare unresolved placeholder with no flag before it: drop just it.
        if scrub.fullmatch(arg):
            i += 1
            continue
        cleaned.append(arg)
        i += 1
    command = cleaned

    return command


def launch_game(version_id: str, username: str, ram_mb: int, width: int, height: int,
                 java_path: str | None, on_exit=None,
                 *, mc_version: str, loader: str,
                 cfg: dict | None = None, status_cb=None, log_cb=None,
                 server_address: str | None = None, server_port: int | None = None,
                 approve_mod_changes=None) -> subprocess.Popen:
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
        # Each install plays in its OWN game folder (worlds, configs,
        # options.txt), with the shared staging folders linked into it - see
        # paths.INSTANCES_GAME_DIR. Falls back to the shared folder when the
        # filesystem refuses a link, so this is never a new failure mode.
        # Resolved FIRST because the per-game-dir writes below (cosmetics)
        # must land in the folder this launch will actually read.
        game_dir = game_dir_for(version_id)

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

        # Shoulder/back cosmetics: the client mod reads this file, so a
        # selection made in the Cosmetics tab is live on the next join. Written
        # into THIS launch's game folder - the mod's config dir is the
        # instance's config/, not the shared root.
        try:
            from . import cosmetics as _cosmetics
            _cosmetics.sync_to_game(cfg, game_dir)
        except Exception:
            logging.getLogger(__name__).debug(
                "cosmetics sync failed", exc_info=True)

        # Best-effort: never let a skin-mod problem stop the game launching.
        try:
            skin_setup = csl.ensure_ready(
                mc_version, loader,
                manage=bool(cfg.get("manage_skin_mod", True)),
                status_cb=status_cb,
                version_id=version_id,
            ) or {}
            if (cfg.get("manage_skin_mod", True) and loader in MOD_CAPABLE_LOADERS
                    and not skin_setup.get("installed")):
                logging.getLogger(__name__).warning("skin loader setup: %s",
                                                     skin_setup.get("detail") or "not installed")
        except Exception as error:
            logging.getLogger(__name__).warning("skin loader setup failed: %s",
                                                 type(error).__name__)

    # Ship the in-game Cubeon Client mod into the Fabric profile so the
    # Friends button exists in Minecraft's game menu. Best-effort, always
    # before the mods sync so a fresh drop is live this launch.
    try:
        from .features import friends_enabled
        from .mods import get_profile_dir
        from . import cubeonfriends
        _profile_dir = get_profile_dir(mc_version, loader, version_id)
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
            if friends_ok:
                # The HUD half of the client mod is built on Fabric API, which
                # is a mod rather than part of the loader. Install it too, so
                # "the overlays work" is not something the player has to arrange
                # - but only alongside a jar we actually shipped, and only
                # best-effort: a profile without it still gets the button.
                try:
                    _api_detail = cubeonfriends.ensure_fabric_api(
                        mc_version, loader, status_cb=status_cb,
                        version_id=version_id)
                    if _api_detail.startswith(("couldn't", "no ", "download")):
                        logging.getLogger(__name__).info(
                            "Fabric API not installed: %s", _api_detail)
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Fabric API setup failed", exc_info=True)
    except Exception:
        logging.getLogger(__name__).warning("friends mod setup failed", exc_info=True)

    # Each install plays in its OWN game folder (worlds, configs, options.txt),
    # with the shared staging folders linked into it - see
    # paths.INSTANCES_GAME_DIR. Falls back to the shared folder when the
    # filesystem refuses a link, so this is never a new failure mode.
    # Already resolved at the top of the cfg block; this covers the callers
    # that launch without a config dict (a bare command build).
    if cfg is None:
        game_dir = MINECRAFT_DIR

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
                                                status_cb=status_cb,
                                                version_id=version_id)
            if report["installed"] and status_cb:
                status_cb("FPS boost installed")
            # The suite was narrowed to Sodium only; remove the retired mods so
            # an existing profile stops loading the pile instead of leaving the
            # user to delete eight jars by hand.
            pruned = perf_mods.prune_retired_perf_mods(mc_version, loader,
                                                       version_id=version_id)
            if pruned and status_cb:
                status_cb("Removed extra perf mods")
            # The game is not running yet (the JVM starts further down), so
            # options.txt can be edited safely. Deliberately NO Vsync/maxFps
            # rewrite here (2026-10-24): forcing `enableVsync:false` +
            # `maxFps:260` on every launch meant a player could never keep
            # Vsync on, and on a fast machine that pegged six cores in a
            # singleplayer world (582% CPU, 83 C package). A fresh install now
            # keeps Minecraft's own defaults (Vsync ON, maxFps 120), and an
            # existing options.txt is left exactly as the player set it.
            from . import game_options
            # Max FPS mode: the game's own speed-only graphics options.
            # Same launch-path spot as the frame unlock - options.txt is not
            # owned by a running JVM yet. Gated on the Play-menu FPS boost
            # toggle; when the boost is OFF the SAME keys are written back to
            # Minecraft's defaults instead, so an install that ran boosted
            # actually looks vanilla again (a plain "do nothing" left the
            # fast values baked in, which is what made the old Settings
            # toggle feel useless on an installed instance).
            if cfg.get("fps_boost_enabled", True):
                maxed = game_options.apply_max_fps(
                    game_options.options_path(game_dir))
                if maxed["changed"] and status_cb:
                    status_cb("FPS boost applied")
            else:
                restored = game_options.restore_vanilla_look(
                    game_options.options_path(game_dir))
                if restored["changed"] and status_cb:
                    status_cb("Vanilla graphics restored")
            # Sodium's own renderer options are the half of its settings that
            # options.txt has no key for - they live in
            # config/sodium-options.json, and unlike options.txt there is no
            # "vanilla look" to restore (Sodium's compiled defaults ARE the fast
            # values), so this only ever runs with the boost ON. Rewritten every
            # boosted launch, so a config left by an older Sodium/Cubeon, or by
            # an FPS guide that turned fog occlusion off, cannot keep the
            # renderer doing work it does not have to.
            if cfg.get("fps_boost_enabled", True):
                tuned = perf_mods.apply_max_fps_sodium(
                    perf_mods.sodium_config_path(game_dir))
                if tuned["changed"]:
                    logging.getLogger(__name__).info(
                        "sodium options tuned: %s", tuned["detail"])
    except Exception:
        pass

    # EntityCulling ships with a whitelist that can hold a null/empty entry in
    # a legacy config, which crashes the game on its first tick (see
    # perf_mods.sanitize_entityculling_config). Repair it whenever the mod is
    # present - even if the perf suite is switched off - because a stale broken
    # config would otherwise keep crashing an install the user already has.
    try:
        from . import perf_mods
        repaired = perf_mods.sanitize_entityculling_config(
            perf_mods.entityculling_config_path(game_dir))
        if repaired["removed"]:
            logging.getLogger(__name__).warning(
                "repaired EntityCulling config: %s", repaired["detail"])
    except Exception:
        pass

    command = build_launch_command(version_id, username, ram_mb, width, height,
                                   java_path, game_dir=game_dir,
                                   default_jvm_flags_enabled=(cfg or {}).get("default_jvm_flags_enabled", True),
                                   custom_jvm_flags=(cfg or {}).get("custom_jvm_flags"))

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
    set_active_game_dir(game_dir)

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
    # Launch-time checks are deliberately NON-INTERACTIVE and tiny.
    #
    # This used to run the full doctor (first launch online, every launch
    # offline) with the interactive approver attached. Each proposed mod
    # change opened a modal that waited up to two minutes, so "ignore the
    # doctor and just play" actually meant "wait for every dialog to time
    # out" - the launch was blocked by the very thing the user dismissed.
    #
    # A launch must never wait on a question. All this pass does now is
    # repair launcher-owned settings that make Java die before Minecraft
    # starts (a bare token in custom JVM flags, a deleted Java path). It
    # never touches installed content and never prompts. Mod dependency /
    # conflict repair belongs to an explicit install or "Fix crash" action,
    # not to the Play button.
    try:
        from .doctor import run_doctor
        report = run_doctor(mc_version, loader, auto_fix=True,
                            check_online=False, version_id=version_id,
                            include=("launch",))
        fixed = len(report.get("fixed") or [])
        if fixed and status_cb:
            status_cb("Fixed the launch settings")
    except Exception:
        logging.getLogger(__name__).warning(
            "launch config check failed", exc_info=True)
    try:
        with _spawn_lock:
            try:
                from .content import sync_content_to_game
                sync_content_to_game(mc_version, loader, version_id)
            except Exception:
                logging.getLogger(__name__).warning("content staging failed", exc_info=True)
            sync_mods_to_game(mc_version, loader, version_id)
            process = subprocess.Popen(
                command,
                cwd=game_dir,
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
        # Read in chunks and only emit COMPLETE lines. `readline()` on a log
        # the game is still writing returns a half-written line at EOF and the
        # rest as a second "line" once more arrives, which breaks crash
        # detection that matches whole lines. The remainder is flushed only
        # when the process has ended.
        buffer = ""

        def emit(text):
            text = text.rstrip()
            if text:
                recent.append(text)
                if log_cb:
                    log_cb(text)

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                while True:
                    chunk = fh.read(8192)
                    if chunk:
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            emit(line)
                        continue
                    if process.poll() is not None:
                        # Dead: flush the final (possibly newline-less) line so
                        # a crash report isn't cut off mid-write.
                        if buffer:
                            emit(buffer)
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
        except Exception:
            logging.getLogger(__name__).debug("game exit reconciliation failed", exc_info=True)
        # Let the reader finish flushing what the game wrote on its way out,
        # so a crash report isn't truncated. Bounded so a stuck pipe can't
        # keep this thread alive forever.
        drain.join(timeout=5.0)
        try:
            milestones.end_play_session(session_id=session_id)
        except Exception:
            logging.getLogger(__name__).warning("game playtime cleanup failed", exc_info=True)
        try:
            with _spawn_lock:
                _active_logs.discard(log_path)
                _prune_game_logs()
        except Exception:
            logging.getLogger(__name__).warning("game log cleanup failed", exc_info=True)
        if on_exit:
            # A UI callback that raises must not kill this daemon thread before
            # it finishes; there is no other place that would report it.
            try:
                _call_on_exit(on_exit, process.returncode, list(recent), session_id)
            except Exception:
                logging.getLogger(__name__).warning(
                    "game-exit callback failed", exc_info=True)
        try:
            from .friends_service import FriendsService
            FriendsService.reconcile_username_active()
        except Exception:
            logging.getLogger(__name__).debug("game username reconciliation failed", exc_info=True)
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
