"""
Builds one Cubeon Friends jar per Minecraft bracket and puts them where the
launcher looks for them.

    python3 tools/build_mod_jars.py                 # every bracket
    python3 tools/build_mod_jars.py 26              # just this one
    python3 tools/build_mod_jars.py --list          # show the matrix
    python3 tools/build_mod_jars.py --gradle        # never use the javac path

There are two ways to build, and which one applies is decided by the bracket, not
by preference:

* Brackets with mappings "official" (Minecraft up to 1.21.x) MUST go through
  Gradle. Those versions ship obfuscated, so the jar's references have to be
  remapped from Mojang names into Fabric's intermediary namespace, and
  fabric-loom is the only thing here that can do that. It needs a network the
  first time each bracket runs, to fetch the Minecraft jar and its mappings.

* Brackets with mappings "none" (26.x and later) ship unobfuscated, so there is
  nothing to remap and Gradle earns nothing. Those are built straight from the
  copy of Minecraft the launcher has already downloaded, with whatever javac is
  on PATH - no Gradle, no network, no mappings. This also sidesteps the JDK
  problem: those versions ship class files only a very new JDK can read, so the
  game jar's class-file version is stepped down in a scratch copy first (the
  bytecode is untouched; javac only ever reads signatures out of it).

Jars land in ~/.cubeon_launcher/cache/, which is the first place
cubeon/cubeonfriends.py looks, so a freshly built jar is live on the next launch
without reinstalling the launcher. Every jar is verified before being copied:
a jar missing fabric.mod.json is one Fabric silently ignores, and the symptom of
that is a Friends button that just isn't there.
"""
import argparse
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_DIR = os.path.join(ROOT, "mod")
SRC_DIR = os.path.join(MOD_DIR, "src", "main", "java")
RES_DIR = os.path.join(MOD_DIR, "src", "main", "resources")
LIBS_DIR = os.path.join(MOD_DIR, "build", "libs")
BRACKETS = os.path.join(MOD_DIR, "brackets.json")
HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".cubeon_launcher", "cache")
# The distributable copy: every verified build also lands here, so the repo's
# assets folder is a self-contained shippable (a packaged launcher reads ONLY
# this location - see cubeonfriends.find_jar).
ASSETS_JARS = os.path.join(ROOT, "assets", "jars")
MC_DIR = os.path.join(HOME, ".cubeon_minecraft")

# The libraries the mod's own code needs on the compile classpath. Minecraft's
# Component chain reaches into brigadier, its GUI classes into datafixerupper and
# guava, and the mixin annotations live in sponge-mixin. Everything else in
# ~/.cubeon_minecraft/libraries is left out deliberately: a smaller classpath means a
# missing library is a clear error instead of a mysterious one.
LIB_PREFIXES = ("sponge-mixin", "fabric-loader", "brigadier", "slf4j-api",
                "guava", "datafixerupper", "authlib", "annotations")

# What a healthy jar must contain. The two resources are the whole reason the mod
# loads at all, and the screen class is the one most likely to be missing if a
# compile half-failed.
REQUIRED_ENTRIES = ("fabric.mod.json",
                    "cubeon-friends.mixins.json",
                    "com/cubeon/friends/CubeonFriendsScreen.class",
                    "com/cubeon/friends/CornerIcon.class",
                    "com/cubeon/friends/mixin/PauseScreenMixin.class")


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


# ---------------------------------------------------------------------------
# The javac path, for brackets that need no remapping.
# ---------------------------------------------------------------------------

def javac_feature(javac):
    """The Java feature release of a javac binary, e.g. 21, or 0 if it is broken.

    Insisting on the "javac <n>" banner AND a clean exit is not belt-and-braces:
    a JDK unpacked without its shared libraries fails with a message that quotes
    its own path, and a path like ~/jdks/jdk-25.0.4.1+1/bin/javac will happily
    hand a looser check the number 25 for a compiler that cannot run at all.
    """
    try:
        run = subprocess.run([javac, "-version"], capture_output=True, text=True)
    except OSError:
        return 0
    if run.returncode != 0:
        return 0
    match = re.search(r"javac\s+(\d+)", (run.stdout or "") + (run.stderr or ""))
    return int(match.group(1)) if match else 0


def find_javac():
    """Any javac that can emit Java 17 bytecode, newest of the obvious ones."""
    candidates = []
    found = shutil.which("javac")
    if found:
        candidates.append(found)
    for pattern in (os.path.join(HOME, "jdks", "*", "bin", "javac"),
                    "/usr/lib/jvm/*/bin/javac"):
        candidates.extend(glob.glob(pattern))
    working = []
    for path in candidates:
        feature = javac_feature(path)
        if feature >= 17:
            working.append((feature, path))
    working.sort(reverse=True)
    return working[0] if working else (0, None)


def game_jar(version):
    path = os.path.join(MC_DIR, "versions", version, version + ".jar")
    return path if os.path.isfile(path) else None


def class_major(jar):
    """The class-file version of the first class in a jar."""
    with zipfile.ZipFile(jar) as zf:
        for name in zf.namelist():
            if name.endswith(".class"):
                with zf.open(name) as handle:
                    return struct.unpack(">H", handle.read(8)[6:8])[0]
    return 0


def downgraded_copy(jar, major, into):
    """A copy of `jar` with every class file's version stepped down to `major`.

    javac refuses to read a class file newer than itself, which would otherwise
    make a 26.x jar unbuildable without the very newest JDK. Only the two-byte
    version field is rewritten - nothing reads the bytecode here, javac just
    needs the signatures - so a jar that came out of this is fit for a compile
    classpath and nothing else, which is why it goes in a scratch directory.
    """
    out = os.path.join(into, "compile-classpath.jar")
    with zipfile.ZipFile(jar) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.endswith(".class") and len(data) > 8:
                data = data[:6] + struct.pack(">H", major) + data[8:]
            dst.writestr(item, data)
    return out


def classpath_libs():
    found = []
    for path in glob.glob(os.path.join(MC_DIR, "libraries", "**", "*.jar"),
                          recursive=True):
        name = os.path.basename(path)
        if name.startswith(LIB_PREFIXES) and "sources" not in name:
            found.append(path)
    return found


def sources(bracket_key):
    out = []
    for base, _dirs, files in os.walk(SRC_DIR):
        out.extend(os.path.join(base, f) for f in files if f.endswith(".java"))
    overlay = os.path.join(MOD_DIR, "src", "main", f"java-overlay-{bracket_key}")
    if os.path.isdir(overlay):
        for base, _dirs, files in os.walk(overlay):
            out.extend(os.path.join(base, f) for f in files if f.endswith(".java"))
    return sorted(out)


def stage_resources(out_dir, replacements):
    """Copies the mod's resources next to the classes, expanding placeholders.

    Getting this wrong is the single most expensive mistake in this build: a jar
    built from the class tree alone has no fabric.mod.json, and Fabric then skips
    the mod without a word - no crash, no log line, just no Friends button. An
    unexpanded ${minecraft_range} is nearly as bad; Fabric rejects it as a
    version range and refuses to launch.
    """
    for base, _dirs, files in os.walk(RES_DIR):
        rel = os.path.relpath(base, RES_DIR)
        target = out_dir if rel == "." else os.path.join(out_dir, rel)
        os.makedirs(target, exist_ok=True)
        for name in files:
            source = os.path.join(base, name)
            if name == "fabric.mod.json":
                with open(source, encoding="utf-8") as handle:
                    text = handle.read()
                for key, value in replacements.items():
                    text = text.replace("${%s}" % key, str(value))
                with open(os.path.join(target, name), "w", encoding="utf-8") as handle:
                    handle.write(text)
            else:
                shutil.copyfile(source, os.path.join(target, name))


def pack(out_dir, jar_path, javac_feature_used):
    """Zips a staged directory into a jar.

    Fabric finds a mod by reading fabric.mod.json out of the jar root and needs
    no manifest, but the hand-built jar that was verified working in game has
    one, and matching a known-good artifact costs three lines.
    """
    os.makedirs(os.path.dirname(jar_path), exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/MANIFEST.MF",
                    "Manifest-Version: 1.0\r\n"
                    f"Created-By: {javac_feature_used} (Cubeon build_mod_jars.py)\r\n"
                    "\r\n")
        for base, _dirs, files in os.walk(out_dir):
            for name in sorted(files):
                full = os.path.join(base, name)
                zf.write(full, os.path.relpath(full, out_dir).replace(os.sep, "/"))
    return jar_path


def build_with_javac(bracket, matrix, jar_name):
    """Compiles and packs a no-remapping bracket. Returns (path, error)."""
    version = bracket["compile_against"]
    game = game_jar(version)
    if not game:
        return None, (f"Minecraft {version} is not downloaded "
                      f"(looked for {os.path.join(MC_DIR, 'versions', version)})")

    feature, javac = find_javac()
    if not javac:
        return None, "no working javac 17+ found on PATH or in ~/jdks"

    libs = classpath_libs()
    if not any("sponge-mixin" in os.path.basename(p) for p in libs):
        return None, ("sponge-mixin is not in ~/.cubeon_minecraft/libraries - launch this "
                      "Minecraft version once so the launcher fetches it")

    work = tempfile.mkdtemp(prefix="cubeon-mod-build-")
    try:
        major = class_major(game)
        compile_jar = game
        if major > feature + 44:
            # javac 21 reads up to class-file 65; 26.x ships 69.
            compile_jar = downgraded_copy(game, feature + 44, work)

        classes = os.path.join(work, "classes")
        os.makedirs(classes)
        argfile = os.path.join(work, "args")
        with open(argfile, "w", encoding="utf-8") as handle:
            handle.write("-proc:none\n-nowarn\n--release 17\n")
            handle.write("-cp " + os.pathsep.join([compile_jar] + libs) + "\n")
            handle.write("-d " + classes + "\n")
            handle.write("\n".join(sources(bracket["key"])) + "\n")
        run = subprocess.run([javac, "@" + argfile], capture_output=True, text=True)
        if run.returncode != 0:
            return None, "javac failed:\n" + (run.stdout + run.stderr).strip()

        stage_resources(classes, {
            "version": f"{matrix['mod_version']}+mc{bracket['key']}",
            "minecraft_range": bracket["depends"],
            "loader_range": matrix["loader_min"],
        })
        return pack(classes, os.path.join(LIBS_DIR, jar_name), feature), None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_with_gradle(bracket, jar_name, gradle):
    if not gradle:
        return None, ("no gradle found (install Gradle, or add a wrapper to mod/) - "
                      "this bracket ships obfuscated, so loom has to remap it")
    run = subprocess.run(gradle + ["build", f"-PmcVersion={bracket['key']}"],
                         cwd=MOD_DIR)
    path = os.path.join(LIBS_DIR, jar_name)
    if run.returncode != 0 or not os.path.isfile(path):
        return None, "gradle build failed"
    return path, None


def verify(jar_path):
    """Checks a built jar is one Fabric will actually load. Returns an error."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            missing = [e for e in REQUIRED_ENTRIES if e not in names]
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
    parser.add_argument("--gradle", action="store_true",
                        help="build every bracket through Gradle, even ones that "
                             "need no remapping")
    parser.add_argument("--no-copy", action="store_true",
                        help="leave the jars in mod/build/libs instead of copying")
    args = parser.parse_args(argv)

    matrix = load_matrix()
    version = matrix.get("mod_version", "1.0.0")
    wanted = args.brackets or [b["key"] for b in matrix["brackets"]]
    known = {b["key"]: b for b in matrix["brackets"]}

    if args.list:
        for bracket in matrix["brackets"]:
            how = "gradle+loom" if bracket["mappings"] == "official" else "javac"
            print(f"{bracket['key']:<12} minecraft={bracket['compile_against']:<8} "
                  f"jdk={bracket['jdk']:<3} mappings={bracket['mappings']:<9} "
                  f"build={how:<11} {bracket['depends']}")
        return 0

    unknown = [key for key in wanted if key not in known]
    if unknown:
        print("unknown bracket(s): " + ", ".join(unknown))
        print("known: " + ", ".join(known))
        return 2

    gradle = gradle_command()
    built, failed = [], []
    for key in wanted:
        bracket = known[key]
        jar = matrix["jar_name"].replace("{version}", version).replace("{key}", key)
        needs_loom = bracket["mappings"] == "official"
        how = "gradle+loom" if (needs_loom or args.gradle) else "javac"
        print(f"\n=== {key} -> {jar} ({how}) ===")

        if needs_loom or args.gradle:
            path, error = build_with_gradle(bracket, jar, gradle)
        else:
            path, error = build_with_javac(bracket, matrix, jar)
            if error and gradle:
                print(f"javac path did not work ({error}); trying gradle")
                path, error = build_with_gradle(bracket, jar, gradle)

        if error:
            print("      " + error)
            failed.append(key)
            continue

        error = verify(path)
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
        print("\nA bracket with no jar means no Friends button on those Minecraft "
              "versions. The launcher installs nothing rather than the wrong jar.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
