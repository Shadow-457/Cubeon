"""
Ships the "Cubeon Friends" Fabric mod (see mod/ in the repo) into the active
Fabric profile before launch, so the Friends button shows up in Minecraft's
game menu without the player ever installing anything.

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

from .paths import CUBEON_HOME
from . import global_mod_cache

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRACKETS_FILE = os.path.join(_REPO, "mod", "brackets.json")

# Every jar this module manages, so an obsolete one can be recognised and
# removed. Covers the pre-bracket name (cubeon-friends-1.0.0.jar) too, which
# would otherwise sit in the profile forever alongside its replacement.
JAR_GLOB = "cubeon-friends-*.jar"

# A Minecraft version number, and nothing that merely contains digits. The
# lookarounds are what keep snapshots out: "25w06a" has no version in it, and
# reading "25" or "06" out of it would silently pick a bracket at random.
_MC_VERSION_RE = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)*(?![A-Za-z0-9]*[A-Za-z])")

_matrix_cache: dict | None = None


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
    matches = _MC_VERSION_RE.findall(str(text))
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
    pattern = _matrix().get("jar_name", "cubeon-friends-{version}+mc{key}.jar")
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
    repo_libs = os.path.join(_REPO, "mod", "build", "libs")
    asset_jars = os.path.join(_REPO, "assets", "jars")
    for path in (os.path.join(CUBEON_HOME, "cache", name),
                 os.path.join(asset_jars, name),
                 os.path.join(repo_libs, name)):
        if os.path.isfile(path):
            return path
    return None


def _remove_other_jars(profile_dir: str, keep: str | None) -> None:
    """Deletes every Cubeon Friends jar in the profile except `keep`."""
    for path in glob.glob(os.path.join(profile_dir, JAR_GLOB)):
        if keep and os.path.basename(path) == keep:
            continue
        try:
            os.remove(path)
        except OSError:
            pass


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
