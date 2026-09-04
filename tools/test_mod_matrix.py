"""
Guards the Cubeon Friends mod's Minecraft version matrix.

The mod ships as one jar per Minecraft bracket, and two things have to agree
about that matrix: mod/build.gradle (which builds the jars) and
cubeon/cubeonfriends.py (which installs them). They agree by both reading
mod/brackets.json - these tests are what makes sure the table itself is sane and
that the installer actually picks the jar the table promises.

The failure this is really guarding against is silent: a launcher that installs a
1.20-era jar into a 1.16 profile doesn't misbehave, it crashes the game before
the main menu, and the player has no way to tell it was the launcher's doing.
"""
import fnmatch
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import cubeonfriends  # noqa: E402

MOD = os.path.join(ROOT, "mod")

passed = 0
failed = 0


def section(title):
    print()
    print(title)


def ok(condition, label):
    global passed, failed
    if condition:
        passed += 1
        print("  ok  " + label)
    else:
        failed += 1
        print("FAIL  " + label)


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_table():
    section("brackets.json: the table itself")
    matrix = load(os.path.join(MOD, "brackets.json"))
    brackets = matrix["brackets"]
    ok(bool(brackets), "at least one bracket")
    ok(all(k in matrix for k in ("mod_version", "loader_version", "loader_min", "jar_name")),
       "build-wide fields present")

    fields = ("key", "compile_against", "jdk", "mappings", "min", "below", "depends")
    ok(all(all(f in b for f in fields) for b in brackets),
       "every bracket declares " + ", ".join(fields))

    keys = [b["key"] for b in brackets]
    ok(len(keys) == len(set(keys)), "bracket keys are unique")
    ok(all(b["mappings"] in ("official", "none") for b in brackets),
       "mappings is either official or none")

    parse = cubeonfriends.parse_mc_version
    for b in brackets:
        below = parse(b["below"]) if b["below"] is not None else None
        ok(below is None or parse(b["min"]) < below,
           f"{b['key']}: min < below")
        # compile_against must be inside its own bracket, or the jar is built
        # against an API the versions it declares support may not have.
        ok(parse(b["min"]) <= parse(b["compile_against"])
           and (below is None or parse(b["compile_against"]) < below),
           f"{b['key']}: compiles against a version inside its own range")
        expected = f">={b['min']}" if b["below"] is None \
            else f">={b['min']} <{b['below']}"
        ok(b["depends"] == expected,
           f"{b['key']}: fabric.mod.json range matches min/below")

    # Overlapping ranges would make jar selection depend on table order, which
    # is exactly the kind of bug that only shows up on one player's machine.
    spans = sorted((parse(b["min"]),
                    parse(b["below"]) if b["below"] is not None else (10 ** 6, 0, 0),
                    b["key"]) for b in brackets)
    overlaps = [(a[2], c[2]) for a, c in zip(spans, spans[1:]) if c[0] < a[1]]
    ok(not overlaps, f"no two brackets overlap ({overlaps})")

    # Gaps are worse than they look: a version that falls between two brackets
    # gets no jar at all, which is how 1.21.11 ended up with no Friends button
    # while both a 1.20-era and a 26-era jar existed.
    gaps = [(a[2], c[2]) for a, c in zip(spans, spans[1:]) if c[0] > a[1]]
    ok(not gaps, f"the brackets are contiguous, no version falls between ({gaps})")

    # One open-ended bracket at the top, so a Minecraft released after this
    # launcher still gets the newest jar instead of nothing.
    ok(sum(1 for b in brackets if b["below"] is None) == 1,
       "exactly one bracket is open-ended")
    ok(brackets[-1]["below"] is None, "and it is the last one in the table")

    ok(all(int(b["jdk"]) >= 17 for b in brackets),
       "every bracket builds on JDK 17 or newer")
    return matrix


def test_version_parsing():
    section("parse_mc_version")
    parse = cubeonfriends.parse_mc_version
    ok(parse("1.20.1") == (1, 20, 1), "plain version")
    ok(parse("1.21") == (1, 21, 0), "two components pad to three")
    ok(parse("26.1.2") == (26, 1, 2), "the year-style versions parse too")
    # Callers hand us profile ids as often as versions; the loader's own version
    # comes first in those, and picking it would select the wrong bracket.
    ok(parse("fabric-loader-0.16.9-1.21.4") == (1, 21, 4),
       "a fabric profile id yields the Minecraft version, not the loader's")
    ok(parse("27") == (27, 0, 0), "a bare major is a version")
    ok(parse("25w06a") is None, "a snapshot has no bracket")
    ok(parse("1.21.5-pre1") is None or parse("1.21.5-pre1") == (1, 21, 5),
       "(documented: pre-releases are best-effort)")
    ok(parse("") is None and parse(None) is None, "empty input")


def test_selection(matrix):
    section("pick_bracket")
    pick = cubeonfriends.pick_bracket
    for version, expected in (("1.20.1", "1.20-1.21"),
                              ("1.20.2", "1.20-1.21"),
                              ("1.20.6", "1.20-1.21"),
                              ("1.21", "1.20-1.21"),
                              ("1.21.5", "1.20-1.21"),
                              # The version that started this: obfuscated era, so
                              # it needs the intermediary-namespace jar, and used
                              # to get nothing at all.
                              ("1.21.11", "1.20-1.21"),
                              ("26.1", "26"),
                              ("26.1.2", "26"),
                              # Unobfuscated era, released after this launcher.
                              ("26.4", "26"),
                              ("27.0.1", "26")):
        got = pick(version)
        ok(got is not None and got["key"] == expected,
           f"{version} -> {expected} (got {got and got['key']})")

    # No jar rather than a crashing one: the widgets this screen is built from
    # arrived in 1.20, so nothing older can load this mod at all.
    for version in ("1.19.4", "1.16.5", "1.12.2", "1.7.10"):
        ok(pick(version) is None, f"{version} has no bracket (pre-StringWidget)")
    ok(pick("25w06a") is None, "snapshots have no bracket")

    # The eras must not be confused for one another. A jar whose references are
    # in the wrong namespace resolves to nothing at runtime.
    ok(pick("1.21.11")["mappings"] == "official",
       "the obfuscated era is built with mappings, so its jar is intermediary")
    ok(pick("26.1.2")["mappings"] == "none",
       "the unobfuscated era is built without")

    keys = {b["key"] for b in matrix["brackets"]}
    names = {cubeonfriends.jar_name(b) for b in matrix["brackets"]}
    ok(len(names) == len(keys), "each bracket maps to a distinct jar name")
    ok(all("+mc" in n and n.endswith(".jar") for n in names),
       "jar names carry their bracket, so a profile's jar is self-identifying")
    # Fabric parses the mod version as semver and "+" opens build metadata, so a
    # second one in the key would make the whole mod version invalid.
    ok(all(n.count("+") == 1 for n in names),
       "and stay valid semver (one + in the version)")


def test_no_cross_era_fallback():
    section("find_jar never guesses across eras")
    # find_jar used to fall back to an unbracketed jar when the right one was
    # missing. With two namespaces in play that fallback is a crash rather than a
    # degraded button: the 26.x jar in a 1.21 profile resolves none of its
    # references, because 1.21 expects intermediary names and it has real ones.
    work = tempfile.mkdtemp(prefix="cubeon-mod-find-")
    real_home, real_repo = cubeonfriends.CUBEON_HOME, cubeonfriends._REPO
    try:
        cache = os.path.join(work, "home", "cache")
        os.makedirs(cache)
        os.makedirs(os.path.join(work, "repo", "mod", "build", "libs"))
        cubeonfriends.CUBEON_HOME = os.path.join(work, "home")
        cubeonfriends._REPO = os.path.join(work, "repo")

        modern = cubeonfriends.jar_name(cubeonfriends.pick_bracket("26.1.2"))
        for name in ("cubeon-friends-1.0.0.jar", modern):
            with open(os.path.join(cache, name), "wb") as handle:
                handle.write(b"PK\x03\x04 not really a jar")

        ok(cubeonfriends.find_jar("1.21.11") is None,
           "an obfuscated-era launch takes no jar rather than the wrong-era one")
        ok(cubeonfriends.find_jar("1.20.1") is None,
           "and none rather than a pre-bracket jar of unknown provenance")
        found = cubeonfriends.find_jar("26.1.2")
        ok(found is not None and os.path.basename(found) == modern,
           f"the era that does have a jar still gets it ({found and os.path.basename(found)})")
    finally:
        cubeonfriends.CUBEON_HOME, cubeonfriends._REPO = real_home, real_repo
        shutil.rmtree(work, ignore_errors=True)

    for bracket in load(os.path.join(MOD, "brackets.json"))["brackets"]:
        name = cubeonfriends.jar_name(bracket)
        # The cleanup glob is what removes the other era's jar when a profile
        # changes version. A jar it doesn't match would live in the profile
        # forever, and two mods with one id is a hard Fabric failure.
        ok(fnmatch.fnmatch(name, cubeonfriends.JAR_GLOB),
           f"{name} is matched by the cleanup glob {cubeonfriends.JAR_GLOB}")


def test_install():
    section("ensure_installed")
    work = tempfile.mkdtemp(prefix="cubeon-mod-install-")
    try:
        profile = os.path.join(work, "profile")
        os.makedirs(profile)
        bracket = cubeonfriends.pick_bracket("1.20.1")
        name = cubeonfriends.jar_name(bracket)

        # Stand in for a built jar without needing Gradle or a network.
        fake_cache = os.path.join(work, "cache")
        os.makedirs(fake_cache)
        with open(os.path.join(fake_cache, name), "wb") as handle:
            handle.write(b"PK\x03\x04 not really a jar")

        real_find = cubeonfriends.find_jar
        cubeonfriends.find_jar = lambda mc: (
            os.path.join(fake_cache, cubeonfriends.jar_name(cubeonfriends.pick_bracket(mc)))
            if cubeonfriends.pick_bracket(mc)
            and os.path.isfile(os.path.join(
                fake_cache, cubeonfriends.jar_name(cubeonfriends.pick_bracket(mc))))
            else None)
        try:
            ok(cubeonfriends.ensure_installed("1.20.1", "fabric", profile),
               "installs the jar for a supported version")
            ok(os.path.isfile(os.path.join(profile, name)), "jar is in the profile")

            ok(cubeonfriends.ensure_installed("1.20.1", "fabric", profile),
               "installing twice is fine")
            ok(len([f for f in os.listdir(profile) if f.endswith(".jar")]) == 1,
               "and does not leave a second copy")

            # The upgrade case: an older launcher shipped an unbracketed jar.
            # Leaving it behind means two mods with the same id, which Fabric
            # refuses to load at all - a crash on an otherwise fine profile.
            legacy = os.path.join(profile, "cubeon-friends-1.0.0.jar")
            with open(legacy, "wb") as handle:
                handle.write(b"old")
            cubeonfriends.ensure_installed("1.20.1", "fabric", profile)
            ok(not os.path.exists(legacy),
               "a pre-bracket jar is removed instead of duplicating the mod id")

            ok(cubeonfriends.ensure_installed("1.20.1", "quilt", profile),
               "quilt gets the fabric jar (it loads them natively)")

            # Unsupported version, and the jar from a previous launch is still
            # sitting there: it must go, or the game crashes on class load.
            ok(not cubeonfriends.ensure_installed("1.16.5", "fabric", profile),
               "no install for a pre-1.20 version")
            ok(not [f for f in os.listdir(profile) if f.endswith(".jar")],
               "and the stale jar is cleaned out")

            cubeonfriends.ensure_installed("1.20.1", "fabric", profile)
            ok(not cubeonfriends.ensure_installed("1.20.1", "forge", profile),
               "forge is a no-op")
            ok(not [f for f in os.listdir(profile) if f.endswith(".jar")],
               "switching a profile to forge removes the fabric jar")

            ok(not cubeonfriends.ensure_installed("1.20.1", "fabric", None),
               "no profile dir is a no-op, not a crash")
            ok(not cubeonfriends.ensure_installed(None, "fabric", profile),
               "no version is a no-op")
        finally:
            cubeonfriends.find_jar = real_find
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_resources(matrix):
    section("mod resources agree with the build")
    gradle = open(os.path.join(MOD, "build.gradle"), encoding="utf-8").read()
    fabric_json = open(os.path.join(MOD, "src", "main", "resources", "fabric.mod.json"),
                       encoding="utf-8").read()
    mixins = load(os.path.join(MOD, "src", "main", "resources", "cubeon-friends.mixins.json"))

    # A placeholder the build doesn't supply ships to players verbatim, and
    # Fabric then rejects "${minecraft_range}" as a version range.
    placeholders = set(re.findall(r"\$\{(\w+)\}", fabric_json))
    supplied = set(re.findall(r"^\s+(\w+)\s*:", gradle, re.M))
    ok(placeholders <= supplied,
       f"every fabric.mod.json placeholder is filled in by the build "
       f"(missing: {sorted(placeholders - supplied)})")
    ok("filesMatching('fabric.mod.json')" in gradle,
       "the build actually expands fabric.mod.json")

    # Mixin refuses to apply a mixin whose class file is newer than the declared
    # compatibility level, so these two numbers have to be the same number.
    release = re.search(r"options\.release\s*=\s*(\d+)", gradle)
    ok(release is not None, "the build pins a bytecode release")
    ok(release and mixins["compatibilityLevel"] == f"JAVA_{release.group(1)}",
       f"mixin compatibilityLevel matches options.release "
       f"({mixins.get('compatibilityLevel')} vs {release and release.group(1)})")

    # Fail-soft: on a version whose PauseScreen doesn't match, the player should
    # lose the Friends button, not the game.
    ok(mixins.get("required") is False,
       "mixins are not required, so a mismatch is skipped rather than fatal")
    ok(mixins.get("injectors", {}).get("defaultRequire") == 0,
       "a missing injection point is not fatal either")

    ok(matrix["loader_min"] in fabric_json or "${loader_range}" in fabric_json,
       "the loader minimum reaches fabric.mod.json")


def main():
    matrix = test_table()
    test_version_parsing()
    test_selection(matrix)
    test_no_cross_era_fallback()
    test_install()
    test_resources(matrix)
    print()
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
