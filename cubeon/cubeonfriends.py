"""
Ships the "Cubeon Client" Fabric mod (see mod/ in the repo) into the active
Fabric profile before launch, so the Cubeon button shows up in Minecraft's
menus without the player ever installing anything. (Shipped as "Cubeon Friends"
until the rename; see LEGACY_JAR_GLOBS.)

The mod is built once per Minecraft bracket at dev time (see mod/brackets.json
and tools/build_mod_jars.py) and shipped with the launcher. At launch we put
the jar matching the version being launched into the global mods store (one
physical copy, shared by every profile that wants it) and link it into the
per-(mc_version, loader) mod profile - the same folder sync_mods_to_game()
copies from - so it lands in the game's mods directory like any other mod,
but is always up to date and doesn't need a Modrinth download.

Why brackets instead of one jar: not an API difference but a namespace one.
Minecraft up to 1.21.x ships obfuscated, so a Fabric mod's compiled references
live in the intermediary namespace; 26.x ships unobfuscated and its references
are plain names. Fabric remaps nothing at runtime, so one jar cannot hold both.
There are exactly two brackets for that reason, each covering its whole era, and
the newer one has no upper bound so a version released after this launcher still
gets the button. mod/brackets.json is the table, shared with the Gradle build so
the two can't disagree.

Fail-safe throughout: no jar, an unsupported version, or a copy error just means
the in-game button is absent - it never blocks a launch. The one thing this
module is *not* lax about is leaving a stale jar behind: two copies of the mod in
one mods folder is a duplicate-mod-id crash, and a 1.20-era jar in a 1.16 profile
is a crash on class load. Both are cleaned up even when nothing gets installed.
"""

import glob
import hashlib
import json
import os
import re
import zipfile

from .paths import CUBEON_HOME
from . import global_mod_cache

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_path(*parts: str) -> str:
    """Find a bundled resource in source, PyInstaller onedir, or AppImage."""
    import sys
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, *parts))
    if getattr(sys, "frozen", False):
        exe = os.path.dirname(os.path.abspath(sys.executable))
        candidates.extend((os.path.join(exe, *parts), os.path.join(exe, "_internal", *parts)))
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.extend((os.path.join(appdir, "usr", "bin", *parts),
                           os.path.join(appdir, "usr", "bin", "_internal", *parts)))
    candidates.extend((os.path.join(_REPO, *parts),
                       os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


JAR_GLOB = "cubeon-client-*.jar"
# The mod shipped as "Cubeon Friends" (cubeon-friends-*.jar) before it grew into
# the Cubeon Client. A profile set up by one of those launchers still has that
# jar, and the rename changed the mod id, so Fabric would happily load BOTH -
# two Cubeon buttons, two bridges, two pollers. Every cleanup pass therefore
# sweeps the old name as well as the current one; nothing installs it.
LEGACY_JAR_GLOBS = ("cubeon-friends-*.jar",)
_MC_VERSION_RE = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)*(?![A-Za-z0-9]*[A-Za-z])")
_matrix_cache: dict | None = None
BRACKETS_FILE = _resource_path("mod", "brackets.json")


def _matrix() -> dict:
    """The parsed bracket table, or an empty one if it can't be read."""
    global _matrix_cache
    if _matrix_cache is None:
        try:
            with open(BRACKETS_FILE, encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict) or not isinstance(data.get("brackets"), list):
                data = {}
        except (OSError, ValueError):
            data = {}
        _matrix_cache = data
    return _matrix_cache




def parse_mc_version(text: str | None) -> tuple[int, int, int] | None:
    """A comparable (major, minor, patch) from a version string, or None.

    Takes the *last* version-looking number in the string on purpose: callers
    sometimes hand us a profile id like "fabric-loader-0.16.9-1.21.4", where the
    first number is the loader's. Snapshots ("25w06a") contain no version number
    at all and correctly yield None - there is no bracket for them.
    """
    if not text:
        return None
    text = re.split(r"-(?:forge|fabric|quilt|neoforge)(?:-|$)", str(text), maxsplit=1, flags=re.I)[0]
    text = re.sub(r"-(?:pre|rc)-?\d+$", "", text, flags=re.I)
    matches = _MC_VERSION_RE.findall(text)
    if not matches:
        return None
    parts = [int(p) for p in matches[-1].split(".")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def pick_bracket(mc_version: str | None) -> dict | None:
    """The bracket whose range contains mc_version, or None if unsupported.

    A bracket with no "below" is open-ended, which the newest one always is: a
    Minecraft released after this launcher should still get the newest jar rather
    than silently losing the Friends button. Being wrong about that costs the
    button (the mixin is declared non-required); refusing to install costs it for
    certain.
    """
    version = parse_mc_version(mc_version)
    if version is None:
        return None
    for bracket in _matrix().get("brackets", []):
        low = parse_mc_version(bracket.get("min"))
        high = parse_mc_version(bracket.get("below"))
        if low is None or version < low:
            continue
        if high is None or version < high:
            return bracket
    return None


def jar_name(bracket: dict) -> str:
    pattern = _matrix().get("jar_name", "cubeon-client-{version}+mc{key}.jar")
    return (pattern
            .replace("{version}", str(_matrix().get("mod_version", "1.0.0")))
            .replace("{key}", str(bracket.get("key", ""))))


def mod_stamp(mc_version: str | None) -> str:
    """Short sha256 of the jar find_jar() would install - the freshness
    fingerprint served on GET /friends.

    The running mod fingerprints its own jar the same way and compares: a
    mismatch means the launcher on disk is newer than the mod in the game,
    i.e. the player forgot to restart Minecraft after updating Cubeon. Cached
    per (path, mtime) so the once-a-second poll doesn't re-hash the file.
    """
    path = find_jar(mc_version)
    if not path:
        return ""
    try:
        stamp_key = (path, os.path.getmtime(path))
    except OSError:
        return ""
    cached = _mod_stamp_cache.get(stamp_key)
    if cached is not None:
        return cached
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    stamp = h.hexdigest()[:8]
    _mod_stamp_cache.clear()   # keep at most one - the current jar
    _mod_stamp_cache[stamp_key] = stamp
    return stamp


_mod_stamp_cache: dict = {}


def _jar_info(path):
    try:
        stat = os.stat(path)
        key = (path, stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
        if key in _jar_info_cache:
            return _jar_info_cache[key]
        with open(path, "rb") as fh:
            if fh.read(4) != b"PK\x03\x04":
                return None
            fh.seek(0)
            digest = hashlib.sha256(fh.read()).digest()
        with zipfile.ZipFile(path) as jar:
            metadata = jar.getinfo("fabric.mod.json")
            json.loads(jar.read(metadata))
            stamp = max(item.date_time for item in jar.infolist())
        result = (digest, stamp)
        _jar_info_cache.clear()
        _jar_info_cache[key] = result
        return result
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return None


_jar_info_cache = {}


def find_jar(mc_version: str | None) -> str | None:
    """The built jar for mc_version, looked up in the shipped layouts.

    Order: the launcher's runtime cache (what a previous run installed), then
    the repo's assets/jars (the distributable copy - build_mod_jars.py puts
    every fresh build there too, and a packaged launcher has ONLY this), then
    the gradle output. Deliberately no fallback to some other jar: the jars
    differ by namespace, not by features, and installing the 26.x one into a
    1.21 profile is a crash on class load rather than a missing button.
    """
    bracket = pick_bracket(mc_version)
    if bracket is None:
        return None
    name = jar_name(bracket)
    candidates = [os.path.join(CUBEON_HOME, "cache", name),
                  _resource_path("assets", "jars", name),
                  os.path.join(_REPO, "assets", "jars", name),
                  os.path.join(_REPO, "mod", "build", "libs", name)]
    valid = [(path, info) for path in dict.fromkeys(candidates)
             if (info := _jar_info(path)) is not None]
    if not valid:
        return None
    path, info = valid[0]
    if path == candidates[0]:
        bundled = next(((p, i) for p, i in valid if p in candidates[1:3]), None)
        if bundled and info[0] != bundled[1][0] and info[1] <= bundled[1][1]:
            return bundled[0]
    return path


def _remove_other_jars(profile_dir: str, keep: str | None) -> None:
    """Deletes every Cubeon Client jar in the profile except `keep`."""
    for pattern in (JAR_GLOB, *LEGACY_JAR_GLOBS):
        for path in glob.glob(os.path.join(profile_dir, pattern)):
            if keep and os.path.basename(path) == keep:
                continue
            try:
                os.remove(path)
            except OSError:
                pass


def remove_installed(profile_dir: str | None) -> None:
    """Remove Cubeon Client jars from a profile for a no-Friends build."""
    if not profile_dir:
        return
    _remove_other_jars(profile_dir, None)

def ensure_installed(mc_version: str | None, loader: str | None,
                     profile_dir: str | None = None) -> bool:


    """Drops the right mod jar into the active (mc_version, loader) profile.

    Only mod loaders that can run the Fabric-format jar get it: Fabric itself,
    and Quilt, which loads Fabric mods natively. Vanilla has no mod loader and
    Forge/NeoForge need a differently-built jar, so those are a no-op rather
    than a broken install. Returns True when the jar is in place.
    """
    if not profile_dir:
        return False

    if not mc_version or loader not in ("fabric", "quilt"):
        # A profile that switched away from Fabric must not keep the jar: the
        # game would either ignore it or, on Forge, fail to read it.
        if os.path.isdir(profile_dir):
            _remove_other_jars(profile_dir, None)
        return False

    src = find_jar(mc_version)
    name = os.path.basename(src) if src else None
    try:
        os.makedirs(profile_dir, exist_ok=True)
        _remove_other_jars(profile_dir, name)
        if not src:
            return False
        dst = os.path.join(profile_dir, name)
        # Stored once in the global mods store, linked into the profile: a
        # second profile on the same bracket reuses the same physical jar
        # instead of holding its own copy. (Both the shipped jar and any
        # already-stored copy are the same bytes, so put_file dedupes.)
        global_mod_cache.put_file(src, dst)
        return True
    except OSError:
        return False
