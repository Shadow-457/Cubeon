"""
Runs the Cubeon Client mod's Java self-test (mod/tools/SelfTest.java).

The mod's UI classes need a real Minecraft jar on the classpath to compile, so
they can't be tested here. Everything that has historically actually been broken
in the mod, though, lives in classes that import no Minecraft at all - Json and
Bridge - specifically so they can be compiled and run against a bare JDK. This
wrapper finds a JDK, compiles those two plus the test, and runs it.

Skips cleanly (exit 0) when no JDK with javac is installed, so it can sit in the
suite on machines that only run the Python side.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCES = [
    "mod/src/main/java/com/cubeon/client/Json.java",
    "mod/src/main/java/com/cubeon/client/Bridge.java",
    "mod/src/main/java/com/cubeon/client/BadgeNames.java",
    "mod/src/main/java/com/cubeon/client/modules/ModuleCategory.java",
    "mod/src/main/java/com/cubeon/client/modules/Module.java",
    "mod/src/main/java/com/cubeon/client/modules/ModuleConfig.java",
    "mod/src/main/java/com/cubeon/client/modules/HudText.java",
    "mod/tools/SelfTest.java",
]

MAIN_CLASS = "com.cubeon.client.SelfTest"

# Records and pattern-matching switches need 17+; the sources target the same
# language level the mod's Gradle build uses, which is never below this.
MIN_MAJOR = 17


def _java_version(javac):
    """Feature version of a javac binary, or None if it can't run at all."""
    try:
        out = subprocess.run([javac, "-version"], capture_output=True, text=True,
                             timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout + out.stderr).strip()
    if out.returncode != 0 or "javac " not in text:
        # A truncated JDK unpack shows up exactly here: the binary exists and is
        # executable but dies on a missing libjli.so. Treat it as absent.
        return None
    try:
        return int(text.split("javac ", 1)[1].split(".", 1)[0].split()[0])
    except (IndexError, ValueError):
        return None


def find_jdk():
    """(javac, java) for the newest usable JDK, or (None, None)."""
    candidates = []
    on_path = shutil.which("javac")
    if on_path:
        candidates.append(on_path)
    home = os.environ.get("JAVA_HOME")
    if home:
        candidates.append(os.path.join(home, "bin", "javac"))
    for pattern in ("/usr/lib/jvm/*/bin/javac",
                    "/usr/java/*/bin/javac",
                    "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/javac",
                    os.path.expanduser("~/jdks/*/bin/javac")):
        candidates.extend(sorted(glob.glob(pattern)))

    best = (None, None, -1)
    seen = set()
    for javac in candidates:
        real = os.path.realpath(javac)
        if real in seen or not os.access(javac, os.X_OK):
            continue
        seen.add(real)
        major = _java_version(javac)
        if major is None or major < MIN_MAJOR or major <= best[2]:
            continue
        java = os.path.join(os.path.dirname(javac), "java")
        if os.access(java, os.X_OK):
            best = (javac, java, major)
    return best[0], best[1]


def main():
    javac, java = find_jdk()
    if not javac:
        print(f"SKIP  no working JDK {MIN_MAJOR}+ found; the mod's Java tests "
              f"did not run (the Python suite is unaffected)")
        return 0

    missing = [s for s in SOURCES if not os.path.isfile(os.path.join(ROOT, s))]
    if missing:
        print("FAIL  missing mod sources: " + ", ".join(missing))
        return 1

    print(f"using {javac} (javac {_java_version(javac)})")
    out = tempfile.mkdtemp(prefix="cubeon-mod-")
    try:
        # -Werror: the mod ships to players' game clients, where a warning is
        # the only notice we get before an exception in the middle of a screen.
        build = subprocess.run(
            [javac, "-Xlint:all", "-Werror", "-d", out]
            + [os.path.join(ROOT, s) for s in SOURCES],
            capture_output=True, text=True, cwd=ROOT, timeout=180)
        if build.returncode != 0:
            print("FAIL  the mod's Minecraft-free classes do not compile:\n")
            print((build.stdout + build.stderr).strip())
            return 1

        run = subprocess.run([java, "-cp", out, MAIN_CLASS],
                             capture_output=True, text=True, cwd=ROOT, timeout=180)
        sys.stdout.write(run.stdout)
        if run.stderr.strip():
            sys.stderr.write(run.stderr)
        return 1 if run.returncode else 0
    except subprocess.TimeoutExpired:
        print("FAIL  the mod's Java test timed out")
        return 1
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
