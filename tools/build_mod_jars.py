"""
Builds one Cubeon Client jar per Minecraft version and puts them where the
launcher looks for them.

    python3 tools/build_mod_jars.py                 # every bracket (all 24)
    python3 tools/build_mod_jars.py 1.20.2          # just this one
    python3 tools/build_mod_jars.py --list          # show the matrix
    python3 tools/build_mod_jars.py --no-copy       # leave jars in mod/build/libs

Every bracket goes through Gradle and fabric-loom, and there is no longer a
second path. Remapping is the obvious reason for the obfuscated ones: 1.20-1.21.11
ship obfuscated, and their sources are written in Yarn names, which only loom can
turn into the intermediary references the real game needs. The 26.x brackets need
no remapping at all, but they do need Fabric API on the compile classpath (the
HUD is built on HudRenderCallback / HudElementRegistry / KeyBindingHelper), and
the API ships as a bundle of nested module jars - which javac cannot read and
loom can. So Gradle builds all 24, and the first build of each version needs a
network to fetch that Minecraft, its Yarn mappings and Fabric API.

Jars land in ~/.cubeon_launcher/cache/, which is the first place
cubeon/cubeonfriends.py looks, so a freshly built jar is live on the next launch
without reinstalling the launcher. Every jar is verified before being copied:
a jar missing fabric.mod.json is one Fabric silently ignores, and the symptom of
that is a Friends button that just isn't there.

Gradle itself has to run on JVM 25 or newer (loom 1.18 needs it) while the mod
still emits Java 17 bytecode. This script finds a 25+ JDK and points JAVA_HOME at
it for the build, so the system gradle/wrapper can stay on whatever it likes.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_DIR = os.path.join(ROOT, "mod")
LIBS_DIR = os.path.join(MOD_DIR, "build", "libs")
BRACKETS = os.path.join(MOD_DIR, "brackets.json")
HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".cubeon_launcher", "cache")
# The distributable copy: every verified build also lands here, so the repo's
# assets folder is a self-contained shippable (a packaged launcher reads ONLY
# this location - see cubeonfriends.find_jar).
ASSETS_JARS = os.path.join(ROOT, "assets", "jars")

# What a healthy jar must contain. The two resources are the whole reason the mod
# loads at all, the mixins are the one thing most likely to be missing if a
# compile half-failed, and the Cubeon Client classes prove the HUD overlay was layered in
# (a bracket whose overlays list is wrong still builds - it just builds without
# the HUD, and a missing com/cubeon/client/hud class is the only cheap way to see that).
REQUIRED_ENTRIES = ("fabric.mod.json",
                    "cubeon-client.mixins.json",
                    "cubeon-client-crosshair.mixins.json",
                    "assets/cubeon-client/icon.png",
                    "com/cubeon/client/CubeonClient.class",
                    "com/cubeon/client/WorldPlayers.class",
                    "com/cubeon/client/TabListTag.class",
                    "com/cubeon/client/mixin/PlayerTabOverlayMixin.class",
                    "com/cubeon/client/mixin/YggdrasilSessionServiceMixin.class",
                    "com/cubeon/client/hud/CubeonHudClient.class",
                    "com/cubeon/client/hud/CubeonHudConfig.class",
                    "com/cubeon/client/hud/CubeonHud.class",
                    "com/cubeon/client/hud/mixin/CrosshairMixin.class")

# The 26.x brackets only. The HUD there measures ping through a mixin of its own,
# and a mixin that is compiled but not registered by a config silently does
# nothing - the HUD still draws, its ping is just wrong, which is exactly the
# kind of failure nobody notices. So the class and its config are required.
# The motion blur lives only here too: its post effect and shader are the effect,
# and MotionBlurMixin is what asks for it every frame.
REQUIRED_ENTRIES_26X = ("cubeon-client-hud.mixins.json",
                        "com/cubeon/client/hud/mixin/ClientPacketListenerMixin.class",
                        "com/cubeon/client/hud/mixin/MotionBlurMixin.class",
                        "assets/cubeon-client/post_effect/motion_blur_low.json",
                        "assets/cubeon-client/post_effect/motion_blur_medium.json",
                        "assets/cubeon-client/post_effect/motion_blur_high.json",
                        "assets/cubeon-client/shaders/post/motion_blur.fsh")

# Loom 1.18 (all 24 brackets) refuses to start on an older JVM, and the system
# gradle here runs on 21, so the build needs an explicit JAVA_HOME.
GRADLE_JVM_MIN = 25


def load_matrix():
    with open(BRACKETS, encoding="utf-8") as handle:
        return json.load(handle)


def gradle_command():
    """The wrapper if the repo has one, otherwise a system gradle."""
    for candidate in ("gradlew.bat" if os.name == "nt" else "gradlew",):
        path = os.path.join(MOD_DIR, candidate)
        if os.path.isfile(path):
            return [path]
    found = shutil.which("gradle")
    return [found] if found else None


def java_feature(java):
    """The Java feature release of a java binary, e.g. 26, or 0 if it is broken."""
    try:
        run = subprocess.run([java, "-version"], capture_output=True, text=True)
    except OSError:
        return 0
    text = (run.stdout or "") + (run.stderr or "")
    match = re.search(r'version "(\d+)', text)
    if run.returncode != 0 or not match:
        return 0
    feature = int(match.group(1))
    # "1.8.0_392" -> 8, for the ancient installs that still say 1.x
    if feature == 1:
        minor = re.search(r'version "1\.(\d+)', text)
        feature = int(minor.group(1)) if minor else 0
    return feature


def find_gradle_jvm():
    """A 25+ JDK to run Gradle on. Returns (feature, home) or (0, None)."""
    candidates = []
    env_home = os.environ.get("JAVA_HOME")
    if env_home:
        candidates.append(env_home)
    candidates.extend(glob.glob(os.path.join(HOME, "jdks", "*")))
    candidates.extend(glob.glob(os.path.join(HOME, ".gradle", "jdks", "*")))
    candidates.extend(glob.glob("/usr/lib/jvm/*"))
    found = []
    for home in candidates:
        java = os.path.join(home, "bin", "java.exe" if os.name == "nt" else "java")
        if not os.path.isfile(java):
            continue
        feature = java_feature(java)
        if feature >= GRADLE_JVM_MIN:
            found.append((feature, home))
    found.sort(reverse=True)
    return found[0] if found else (0, None)


def build_with_gradle(bracket, jar_name, gradle, jvm_home):
    if not gradle:
        return None, ("no gradle found (install Gradle, or add a wrapper to mod/) - "
                      "loom is what remaps the obfuscated brackets and what can "
                      "read Fabric API's nested jars")
    if not jvm_home:
        return None, (f"no JDK {GRADLE_JVM_MIN}+ found to run Gradle on "
                      f"(loom 1.18 needs one). Install one in ~/jdks or set JAVA_HOME.")
    env = dict(os.environ)
    env["JAVA_HOME"] = jvm_home
    run = subprocess.run(gradle + ["build", f"-PmcVersion={bracket['key']}"],
                         cwd=MOD_DIR, env=env)
    path = os.path.join(LIBS_DIR, jar_name)
    if run.returncode != 0 or not os.path.isfile(path):
        return None, "gradle build failed"
    return path, None


def verify(jar_path, bracket=None):
    """Checks a built jar is one Fabric will actually load. Returns an error."""
    required = list(REQUIRED_ENTRIES)
    if bracket and bracket.get("mappings") == "none":
        required.extend(REQUIRED_ENTRIES_26X)
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            missing = [e for e in required if e not in names]
            if missing:
                return "jar is missing " + ", ".join(missing)
            meta = zf.read("fabric.mod.json").decode("utf-8")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        return f"jar is unreadable ({exc})"
    left = re.findall(r"\$\{(\w+)\}", meta)
    if left:
        return "fabric.mod.json still has placeholders: " + ", ".join(sorted(set(left)))
    try:
        parsed = json.loads(meta)
    except ValueError as exc:
        return f"fabric.mod.json is not valid JSON ({exc})"
    if not parsed.get("depends", {}).get("minecraft"):
        return "fabric.mod.json declares no Minecraft range"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("brackets", nargs="*", help="bracket keys to build; default all")
    parser.add_argument("--list", action="store_true", help="print the matrix and exit")
    parser.add_argument("--no-copy", action="store_true",
                        help="leave the jars in mod/build/libs instead of copying")
    args = parser.parse_args(argv)

    matrix = load_matrix()
    version = matrix.get("mod_version", "1.0.0")
    wanted = args.brackets or [b["key"] for b in matrix["brackets"]]
    known = {b["key"]: b for b in matrix["brackets"]}

    if args.list:
        for bracket in matrix["brackets"]:
            print(f"{bracket['key']:<8} minecraft={bracket['compile_against']:<8} "
                  f"jdk={bracket['jdk']:<3} mappings={bracket['mappings']:<5} "
                  f"fabric-api={bracket['fabric_api']:<18} "
                  f"overlays={'+'.join(bracket['overlays']):<22} {bracket['depends']}")
        return 0

    unknown = [key for key in wanted if key not in known]
    if unknown:
        print("unknown bracket(s): " + ", ".join(unknown))
        print("known: " + ", ".join(known))
        return 2

    gradle = gradle_command()
    jvm_feature, jvm_home = find_gradle_jvm()
    if jvm_home:
        print(f"Gradle JVM: {jvm_home} (java {jvm_feature})")
    else:
        print(f"WARNING: no JDK {GRADLE_JVM_MIN}+ found for Gradle; builds will fail. "
              f"Install one in ~/jdks or set JAVA_HOME.")

    built, failed = [], []
    for key in wanted:
        bracket = known[key]
        jar = matrix["jar_name"].replace("{version}", version).replace("{key}", key)
        print(f"\n=== {key} -> {jar} (gradle+loom, {'+'.join(bracket['overlays'])}) ===")

        path, error = build_with_gradle(bracket, jar, gradle, jvm_home)
        if error:
            print("      " + error)
            failed.append(key)
            continue

        error = verify(path, bracket)
        if error:
            print("      " + error)
            failed.append(key)
            continue
        print(f"      built and verified: {path}")

        if args.no_copy:
            built.append(path)
            continue
        try:
            os.makedirs(CACHE, exist_ok=True)
            shutil.copyfile(path, os.path.join(CACHE, jar))
            os.makedirs(ASSETS_JARS, exist_ok=True)
            shutil.copyfile(path, os.path.join(ASSETS_JARS, jar))
            built.append(os.path.join(CACHE, jar))
            built.append(os.path.join(ASSETS_JARS, jar))
        except OSError as exc:
            print(f"      built but could not copy: {exc}")
            failed.append(key)

    print()
    for path in built:
        print("ok    " + path)
    for key in failed:
        print("FAIL  " + key)
    if failed:
        print("\nA bracket with no jar means no Cubeon button and no HUD on those "
              "Minecraft versions. The launcher installs nothing rather than the "
              "wrong jar.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
