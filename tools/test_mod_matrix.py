"""
Guards the Cubeon Client mod's Minecraft version matrix.

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
import glob
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import cubeonfriends  # noqa: E402
from build_mod_jars import removed_feature_entries, verify, REQUIRED_ENTRIES  # noqa: E402

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
    # "yarn" means the release ships obfuscated and loom remaps Yarn names to
    # intermediary; "none" means 26.x and later, which ship unobfuscated.
    ok(all(b["mappings"] in ("yarn", "none") for b in brackets),
       "mappings is either yarn or none")
    ok(all(("yarn" in b) == (b["mappings"] == "yarn") for b in brackets),
       "every yarn bracket names the mappings version it builds against")
    ok(all("fabric_api" in b and b["overlays"] for b in brackets),
       "every bracket names its Fabric API version and its source overlays")
    ok(all(b["overlays"][0] == ("api-yarn" if b["mappings"] == "yarn" else "api-mojang")
           for b in brackets),
       "each bracket layers the api overlay for its own namespace")

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
        expected = f">={b['min']}" if b["below"] is None else f"~{b['key']}"
        ok(b["depends"] == expected,
           f"{b['key']}: fabric.mod.json range is {expected} (looser than the "
           f"bracket's own min/below on purpose - see the assertion below)")

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

    # The toolchain has to be able to READ the Minecraft jar it compiles
    # against, and Minecraft raised its own floor twice: 1.20.5 moved to Java 21
    # (its classes are major 65) and 26.x to Java 25. A bracket that reads 1.20.5
    # on a 17 toolchain fails with "class file has wrong version 65.0, should be
    # 61.0" - exactly how 1.20.5 and 1.20.6 failed the first time all 24 were
    # built, because those two were the only brackets Cubeon Client never got round to
    # building on this machine. The *bytecode* stays Java 17 either way.
    for b in brackets:
        mc = parse(b["compile_against"])
        floor = 25 if mc >= (26, 0, 0) else 21 if mc >= (1, 20, 5) else 17
        ok(int(b["jdk"]) >= floor,
           f"{b['key']}: toolchain {b['jdk']} can read that Minecraft "
           f"(needs {floor}+)")
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
    for version, expected in (("1.20", "1.20"),
                              ("1.20.1", "1.20.1"),
                              ("1.20.2", "1.20.2"),
                              ("1.20.6", "1.20.6"),
                              ("1.21", "1.21"),
                              ("1.21.5", "1.21.5"),
                              # The version that started this: obfuscated era, so
                              # it needs the intermediary-namespace jar, and used
                              # to get nothing at all.
                              ("1.21.11", "1.21.11"),
                              ("26.1", "26.1"),
                              ("26.1.2", "26.1.2"),
                              ("26.3", "26.3"),
                              # Unobfuscated era, released after this launcher.
                              ("26.4", "26.3"),
                              ("27.0.1", "26.3"),
                              # A patch that does not exist yet rides on the
                              # newest jar of its own minor rather than falling
                              # into the next era.
                              ("1.20.7", "1.20.6"),
                              ("1.21.12", "1.21.11")):
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
    ok(pick("1.21.11")["mappings"] == "yarn",
       "the obfuscated era is built from Yarn, so its jar is intermediary")
    ok(pick("26.1.2")["mappings"] == "none",
       "the unobfuscated era is built without")

    # Every Minecraft release from 1.20 up is covered, one bracket each: the
    # merge's whole point was that no version silently loses the HUD.
    listed = [b["key"] for b in matrix["brackets"]]
    for release in ("1.20", "1.20.1", "1.20.2", "1.20.3", "1.20.4", "1.20.5", "1.20.6",
                    "1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4", "1.21.5", "1.21.6",
                    "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11",
                    "26.1", "26.1.1", "26.1.2", "26.2", "26.3"):
        ok(release in listed, f"{release} has its own bracket")

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
            with zipfile.ZipFile(os.path.join(cache, name), "w") as handle:
                handle.writestr("fabric.mod.json", json.dumps({"id": "cubeon-client"}))

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
    mixins = load(os.path.join(MOD, "src", "main", "resources", "cubeon-client.mixins.json"))

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

    # The 26.x half ships a second mixin config of its own (the HUD's ping
    # probe). It has to exist, be fail-soft like the other one, and be listed
    # only for the brackets that actually carry the class it names.
    hud_cfg_path = os.path.join(MOD, "src", "main", "resources-26x",
                                   "cubeon-client-hud.mixins.json")
    ok(os.path.isfile(hud_cfg_path), "the 26.x HUD's own mixin config is shipped")
    if os.path.isfile(hud_cfg_path):
        hud_cfg = load(hud_cfg_path)
        ok(hud_cfg.get("package") == "com.cubeon.client.hud.mixin",
           "it names the HUD's mixin package")
        ok(hud_cfg.get("required") is False
           and hud_cfg.get("injectors", {}).get("defaultRequire") == 0,
           "and it is fail-soft too: a moved packet hook costs the ping, not the game")
        ok(release is not None
           and int(hud_cfg.get("compatibilityLevel", "JAVA_0").split("_")[1])
           >= int(release.group(1)),
           "its compatibilityLevel is not below the jar's own bytecode")
    ok("mixins_extra" in gradle and "cubeon-client-hud.mixins.json" in gradle,
       "the build lists that config only via the templated mixins array")
    ok("resources-26x" in gradle,
       "and ships the folder holding it only for the brackets that need it")

    # The dynamic crosshair was REMOVED on 2026-10-24 (the player asked for it
    # after it misbehaved in game). It must be gone rather than disabled: a
    # leftover config in fabric.mod.json would name a class that no longer
    # exists, which Fabric reports as a startup warning.
    ok(not os.path.isfile(os.path.join(MOD, "src", "main", "resources",
                                       "cubeon-client-crosshair.mixins.json")),
       "the removed dynamic crosshair's mixin config is gone")
    ok("cubeon-client-crosshair.mixins.json" not in fabric_json,
       "and fabric.mod.json no longer lists it")
    ok(not os.path.isfile(os.path.join(MOD, "src", "main", "java", "com", "cubeon",
                                       "client", "hud", "CrosshairScale.java")),
       "nor does the shared tree still carry CrosshairScale")

    # Source, config and resources must all drop the removed effects.
    pattern = re.compile(
        r"motion[_-]?blur|dynamic[_-]?crosshair|crosshair(?:scale|mixin)|renderTargetHighlight", re.I)
    leftovers = []
    for path in Path(MOD, "src", "main").rglob("*"):
        if path.suffix not in {".java", ".json", ".fsh"}:
            continue
        if pattern.search(path.name) or pattern.search(path.read_text(encoding="utf-8")):
            leftovers.append(str(path.relative_to(MOD)))
    ok(not leftovers, f"removed game effects are absent from all source/resources ({leftovers})")
    if os.path.isfile(hud_cfg_path):
        ok(hud_cfg.get("client") == ["ClientPacketListenerMixin"],
           "the 26.x HUD config registers only the ping hook")


def test_removed_effect_guard():
    section("jar verification rejects removed effects, including stale config fields")
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "probe.jar")

        def write(extra):
            entries = dict.fromkeys(REQUIRED_ENTRIES, b"fixture")
            entries["fabric.mod.json"] = json.dumps({"depends": {"minecraft": "*"}}).encode()
            entries.update(extra)
            with zipfile.ZipFile(path, "w") as jar:
                for name, data in entries.items():
                    jar.writestr(name, data)

        write({"com/cubeon/client/hud/CubeonHud.class": b"crosshairTarget"})
        ok(verify(path) is None, "normal vanilla crosshair references remain valid")
        cases = (
            ("com/cubeon/client/hud/MotionBlur.class", b"fixture"),
            ("assets/cubeon-client/post_effect/motion_blur_low.json", b"{}"),
            ("assets/cubeon-client/shaders/post/motion_blur.fsh", b"fixture"),
            ("com/cubeon/client/hud/CrosshairScale.class", b"fixture"),
            ("com/cubeon/client/hud/mixin/CrosshairMixin.class", b"fixture"),
            ("com/cubeon/client/hud/CubeonHudConfig.class", b"motionBlurStrength"),
            ("com/cubeon/client/hud/CubeonHudConfig.class", b"dynamicCrosshair"),
            ("com/cubeon/client/hud/CubeonHud.class", b"renderTargetHighlight"),
            ("cubeon-client-hud.mixins.json", b'{"client":["MotionBlurMixin"]}'),
            ("fabric.mod.json", b'{"depends":{"minecraft":"*"},"mixins":["cubeon-client-crosshair.mixins.json"]}'),
        )
        for name, data in cases:
            write({name: data})
            error = verify(path)
            ok(error is not None and "removed game effects" in error,
               f"verification rejects {name}: {data!r}")


def test_mouse_buttons():
    section("per-bracket mouse-button convention")
    # 26.3 moved MC's input backend from GLFW to SDL. GLFW numbers the mouse
    # buttons from 0 (left=0) but SDL from 1 (SDL_BUTTON_LEFT=1). The drag
    # editor grabs on the LEFT button, so the 26.3 copy must check 1 while the
    # GLFW copies keep 0. Getting this wrong fails SILENTLY - the click never
    # starts a drag and nothing can be moved - which is exactly the reported
    # "can't move the widgets in Cubeon Client 26.3". Vanilla's own
    # ContainerEventHandler now drags on button() == 1, corroborating SDL.
    root = os.path.join(MOD, "src", "main")

    def grab_button(overlay):
        path = os.path.join(root, overlay, "com", "cubeon", "client", "hud", "screen",
                            "MoveOverlayScreen.java")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            # old brackets name the param plainly (`button == 0`); 1.21.9+ call
            # the event's accessor (`click/event.button() == 0`).
            m = re.search(r"(?:\.button\(\)|\bbutton)\s*==\s*(\d+)", fh.read())
        return m.group(1) if m else None

    ok(grab_button("java-overlay-hud-26.3") == "1",
       "the 26.3 (SDL) drag editor grabs on mouse button 1")
    for glfw in ("java-overlay-hud-26.1", "java-overlay-hud-26.2",
                 "java-overlay-hud-1.21.9", "java-overlay-hud-1.20",
                 "java-overlay-hud-1.20.1", "java-overlay-hud-1.20.2"):
        ok(grab_button(glfw) == "0",
           f"the {glfw} (GLFW) drag editor still grabs on mouse button 0")


def test_fabric_api_install():
    section("ensure_fabric_api")
    from cubeon import mods as mods_module

    real_mods = (mods_module.get_mod_download, mods_module.download_mod)
    real_installed = cubeonfriends.fabric_api_installed
    calls = []
    try:
        # A vanilla/forge profile has no mod loader to install into at all.
        ok(cubeonfriends.ensure_fabric_api("1.20.1", "forge") == "",
           "a non-Fabric profile is a quiet no-op")
        ok(cubeonfriends.ensure_fabric_api(None, "fabric") == "",
           "and no version is too")

        ok(cubeonfriends._looks_like_fabric_api({"slug": "fabric-api"}),
           "recognises the slug the launcher records")
        ok(cubeonfriends._looks_like_fabric_api(
            {"display_name": "fabric-api-0.92.2+1.20.1"}),
           "recognises a jar the player dropped in by hand")
        ok(cubeonfriends._looks_like_fabric_api({"filename": "Fabric API 0.92.2.jar"}),
           "and the spaced spelling")
        ok(not cubeonfriends._looks_like_fabric_api(
            {"display_name": "sodium-fabric-0.9.2-alpha.4.jar"}),
           "but not another mod that merely mentions fabric")

        cubeonfriends.fabric_api_installed = lambda mc, loader, version_id=None: True
        ok("already installed" in cubeonfriends.ensure_fabric_api("1.20.1", "fabric"),
           "an existing copy is left alone, with no download at all")

        cubeonfriends.fabric_api_installed = lambda mc, loader, version_id=None: False
        mods_module.get_mod_download = lambda slug, mc_version=None, loader=None, **kwargs: {
            "url": "https://cdn.example/fabric-api.jar",
            "filename": "fabric-api-0.92.2+1.20.1.jar",
            "version_number": "0.92.2+1.20.1",
            "hashes": {"sha1": "x"}}

        def fake_download(url, filename, **kwargs):
            calls.append((url, filename, kwargs))
            return "/profile/" + filename

        mods_module.download_mod = fake_download
        said = []
        detail = cubeonfriends.ensure_fabric_api("1.20.1", "fabric",
                                                status_cb=said.append)
        ok(detail == "installed Fabric API 0.92.2+1.20.1", f"installs it ({detail})")
        ok(calls and calls[0][2].get("slug") == "fabric-api"
           and calls[0][2].get("mc_version") == "1.20.1"
           and calls[0][2].get("loader") == "fabric",
           "into this profile, under the slug/version/loader the mod store expects")
        ok(any("Fabric API" in line for line in said),
           "and says so in the launch status")

        def dead(slug, mc_version=None, loader=None, **kwargs):
            raise OSError("no network")

        mods_module.get_mod_download = dead
        detail = cubeonfriends.ensure_fabric_api("1.20.1", "fabric")
        ok("couldn't reach Modrinth" in detail,
           f"a dead network is reported, never raised ({detail})")

        mods_module.get_mod_download = lambda slug, mc_version=None, loader=None, **kwargs: None
        detail = cubeonfriends.ensure_fabric_api("1.16.5", "fabric")
        ok("no Fabric API build" in detail,
           f"a Minecraft with no Fabric API build is reported too ({detail})")

        def exploding_download(url, filename, **kwargs):
            raise RuntimeError("sha mismatch")

        mods_module.get_mod_download = lambda slug, mc_version=None, loader=None, **kwargs: {
            "url": "u", "filename": "f", "version_number": "v", "hashes": {}}
        mods_module.download_mod = exploding_download
        detail = cubeonfriends.ensure_fabric_api("1.20.1", "fabric")
        ok("download failed" in detail,
           f"a failed download does not propagate out of the launch path ({detail})")
    finally:
        mods_module.get_mod_download, mods_module.download_mod = real_mods
        cubeonfriends.fabric_api_installed = real_installed


def test_shipped_jars(matrix):
    section("shipped jars only declare classes they contain")
    # 2026-10-23 crash: the WIP emotes overlay added a literal
    # "com.emotesmod.EmotesMod" to the MAIN entrypoint of fabric.mod.json while
    # no bracket actually layered that overlay in. Every rebuilt jar therefore
    # advertised a class it did not contain, and Fabric aborted startup with
    # ClassNotFoundException before the main menu. A jar that names a missing
    # entrypoint is not a warning: it is an unlaunchable game.
    fabric_json = open(os.path.join(MOD, "src", "main", "resources", "fabric.mod.json"),
                       encoding="utf-8").read()
    ok("com.emotesmod.EmotesMod" not in fabric_json,
       "the emotes main class is templated, not literal in fabric.mod.json")
    ok("${emotes_main}" in fabric_json and "emotes_main" in
       open(os.path.join(MOD, "build.gradle"), encoding="utf-8").read(),
       "the build decides whether the emotes entrypoint exists")

    jars = sorted(glob.glob(os.path.join(ROOT, "assets", "jars",
                                         "cubeon-client-*.jar")))
    if not jars:
        ok(True, "no built jars to inspect (skip)")
        return
    for path in jars:
        name = os.path.basename(path)
        try:
            with zipfile.ZipFile(path) as jar:
                names = set(jar.namelist())
                removed = removed_feature_entries(jar)
                ok(not removed, f"{name}: no removed game effect code/assets/config ({removed})")
                meta = json.loads(jar.read("fabric.mod.json"))
                # Read the mixin configs while the archive is still open; the
                # `with` block closes it, and a closed ZipFile cannot be read.
                mixin_configs = []
                for entry in meta.get("mixins") or []:
                    cfg_name = entry.get("config") if isinstance(entry, dict) else entry
                    if not cfg_name:
                        continue
                    if cfg_name not in names:
                        mixin_configs.append((cfg_name, None))
                        continue
                    try:
                        mixin_configs.append((cfg_name, json.loads(jar.read(cfg_name))))
                    except (KeyError, ValueError) as exc:
                        mixin_configs.append((cfg_name, f"unreadable ({exc})"))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            ok(False, f"{name}: readable jar ({exc})")
            continue
        missing = []
        for stage, classes in (meta.get("entrypoints") or {}).items():
            for entry in classes:
                # A value may be "class" or "class::method"; only the class
                # matters for existence.
                cls = str(entry).split("::", 1)[0].strip()
                if not cls:
                    continue
                if cls.replace(".", "/") + ".class" not in names:
                    missing.append(f"{stage}:{cls}")
        ok(not missing, f"{name}: every declared entrypoint class is present "
                        f"(missing: {missing})")

        # The same failure mode, one layer down: fabric.mod.json lists a mixin
        # config, and the config names classes. If the config is not in the jar
        # (wrong overlay) or names a class that is not (wrong era copy), Mixin
        # skips it and the feature silently does nothing. Check the chain.
        missing_mixins = []
        for cfg_name, cfg in mixin_configs:
            if cfg is None:
                missing_mixins.append(f"config:{cfg_name}")
                continue
            if isinstance(cfg, str):
                missing_mixins.append(f"{cfg_name}: {cfg}")
                continue
            package = cfg.get("package", "")
            for side in ("mixins", "client", "server"):
                for cls in cfg.get(side) or []:
                    class_path = (package + "." + cls).replace(".", "/") + ".class"
                    if class_path not in names:
                        missing_mixins.append(f"{cfg_name}:{cls}")
        ok(not missing_mixins,
           f"{name}: every listed mixin config and class is present "
           f"(missing: {missing_mixins})")


def test_zoom():
    """Hold-to-zoom: one overlay per getFov return type, and no 26.x claim."""
    section("hold-to-zoom wiring")
    matrix = load(os.path.join(MOD, "brackets.json"))
    buckets = {b["key"]: [o for o in b["overlays"]
                          if str(o).startswith("zoom-")]
               for b in matrix["brackets"]}
    yarn = [b for b in matrix["brackets"] if b["mappings"] == "yarn"]
    mojang = [b for b in matrix["brackets"] if b["mappings"] != "yarn"]
    ok(all(len(buckets[b["key"]]) == 1 for b in yarn),
       "every Yarn bracket carries exactly one zoom overlay")
    ok(all(not buckets[b["key"]] for b in mojang),
       "26.x brackets carry none: their FOV path moved and is not ported")

    # GameRenderer.getFov returns a double up to 1.21.1 and a float from
    # 1.21.2. A jar with the wrong copy compiles (the names match) and then
    # fails to apply the mixin at startup, which is why the split is checked
    # by version here instead of trusted.
    parse = cubeonfriends.parse_mc_version
    wrong = []
    for b in yarn:
        expected = ("zoom-double"
                    if parse(b["compile_against"]) < parse("1.21.2")
                    else "zoom-float")
        if buckets[b["key"]] != [expected]:
            wrong.append((b["key"], buckets[b["key"]], expected))
    ok(not wrong, f"each zoom overlay matches getFov's return type ({wrong})")

    for overlay in ("zoom-double", "zoom-float"):
        base = os.path.join(MOD, "src", "main", f"java-overlay-{overlay}",
                            "com", "cubeon", "client", "mixin")
        ok(os.path.isfile(os.path.join(base, "ZoomMixin.java"))
           and os.path.isfile(os.path.join(base, "ZoomScrollMixin.java")),
           f"{overlay} ships both the FOV and the scroll hook")

    shared = os.path.join(MOD, "src", "main", "java", "com", "cubeon", "client",
                          "hud", "Zoom.java")
    ok(os.path.isfile(shared), "the smoothed zoom state is in the shared tree")
    shared_src = open(shared, encoding="utf-8").read()
    ok("CubeonHudConfig" in shared_src and "net.minecraft" not in shared_src,
       "and it stays Minecraft-free, so the shared tree still compiles alone")

    cfg_path = os.path.join(MOD, "src", "main", "resources",
                            "cubeon-client.zoom.mixins.json")
    ok(os.path.isfile(cfg_path), "the zoom mixin config is shipped")
    if os.path.isfile(cfg_path):
        cfg = load(cfg_path)
        ok(set(cfg.get("client", [])) == {"ZoomMixin", "ZoomScrollMixin"},
           "it registers both zoom mixins")
        ok(cfg.get("required") is False
           and cfg.get("injectors", {}).get("defaultRequire") == 0,
           "and it is fail-soft: a mismatch costs the zoom, not the game")
        ok(cfg.get("compatibilityLevel") == "JAVA_17",
           "its compatibilityLevel matches the jar's bytecode")

        gradle = open(os.path.join(MOD, "build.gradle"), encoding="utf-8").read()
        ok("zoom_mixins" in gradle and "cubeon-client.zoom.mixins.json" in gradle,
           "build.gradle lists that config only via the templated mixins array")
        fabric = open(os.path.join(MOD, "src", "main", "resources",
                                   "fabric.mod.json"), encoding="utf-8").read()
        ok("${zoom_mixins}" in fabric, "fabric.mod.json asks the build for it")

        dbl = open(os.path.join(MOD, "src", "main", "java-overlay-zoom-double",
                                "com", "cubeon", "client", "mixin", "ZoomMixin.java"),
                   encoding="utf-8").read()
        flt = open(os.path.join(MOD, "src", "main", "java-overlay-zoom-float",
                                "com", "cubeon", "client", "mixin", "ZoomMixin.java"),
                   encoding="utf-8").read()
        ok("CallbackInfoReturnable<Double>" in dbl and "getReturnValueD" in dbl,
           "the 1.20-1.21.1 copy reads and writes a double")
        ok("CallbackInfoReturnable<Float>" in flt and "getReturnValueF" in flt,
           "the 1.21.2+ copy reads and writes a float")


def main():
    matrix = test_table()
    test_version_parsing()
    test_selection(matrix)
    test_no_cross_era_fallback()
    test_install()
    test_fabric_api_install()
    test_resources(matrix)
    test_removed_effect_guard()
    test_mouse_buttons()
    test_zoom()
    test_shipped_jars(matrix)
    print()
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
