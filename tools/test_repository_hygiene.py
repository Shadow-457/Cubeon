"""Generated diagnostics stay untracked without losing bundled runtime assets."""
from pathlib import Path
import hashlib
import re
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parent.parent

# A bundled client jar must carry the generated cosmetic catalogue and art.
# assets/jars is what the launcher installs (and what a packaged build ships),
# so a stale jar there silently means "no shoulder/back items in game" even
# when mod/build/libs is fresh. tools/build_mod_jars.py copies both.
COSMETIC_CATALOG = "assets/cubeon-client/cosmetics/catalog.json"
COSMETIC_TEXTURES = "assets/cubeon-client/textures/cosmetics/"


def _jar_has_cosmetics(path):
    try:
        with zipfile.ZipFile(path) as jar:
            names = jar.namelist()
    except (OSError, zipfile.BadZipFile):
        return False
    return (COSMETIC_CATALOG in names
            and any(name.startswith(COSMETIC_TEXTURES)
                    and name.endswith(".png") for name in names))


def main():
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=REPO, text=True).split("\0")) - {""}
    generated = sorted(path for path in tracked if (
        Path(path).suffix in {".log", ".class", ".pyc"}
        or "__pycache__" in Path(path).parts
        or path.startswith(("logs/", "build/", "dist/", "archive/",
                            "agents/docs/ux_shots", ".venv/", ".venv-"))))
    samples = ["logs/build.log", "net/minecraft/Example.class",
               ".venv/lib/example.py", ".venv-build/lib/example.py",
               "ui/__pycache__/example.pyc", "agents/docs/ux_shots/preview.png"]
    ignored = set(subprocess.check_output(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"], cwd=REPO,
        input="\0".join(samples) + "\0", text=True).split("\0"))
    public_hashes = {
        hashlib.sha256((REPO / path).read_bytes()).digest()
        for path in tracked if path.startswith("docs/") and path.endswith(".md")
        and (REPO / path).is_file()
    }
    mirrors = [path for path in tracked if path.startswith("agents/")
               and path.endswith(".md") and (REPO / path).is_file()
               and hashlib.sha256((REPO / path).read_bytes()).digest() in public_hashes]
    index = (REPO / "agents/docs/module-map.md").read_text()
    readme = (REPO / "README.md").read_text()
    capture = (REPO / "tools/ux_capture.py").read_text()
    # Flet serialises an unset Scale axis as null; the Flutter client then
    # builds a NaN matrix and logs "TransformLayer is constructed with an
    # invalid matrix" on every repaint. Runtime code must always set BOTH
    # axes explicitly (tools/tests may use the positional shorthand).
    bad_scales = []
    runtime_files = [REPO / "main.py"] + sorted((REPO / "ui").glob("*.py")) \
        + sorted((REPO / "cubeon").glob("*.py"))
    for path in runtime_files:
        source = path.read_text()
        for match in re.finditer(r"ft\.Scale\(([^()]*)\)", source):
            args = match.group(1)
            if "scale_x=" not in args or "scale_y=" not in args:
                line = source[:match.start()].count("\n") + 1
                bad_scales.append(f"{path.relative_to(REPO)}:{line}")
    module_paths = re.findall(r"`([\w/.-]+\.py)`", index)
    missing = [path for path in module_paths
               if not (REPO / path).is_file()
               and not (REPO / "cubeon" / path).is_file()
               and not (REPO / "tools" / path).is_file()]
    bundled_jars = [path for path in tracked
                    if path.startswith("assets/jars/cubeon-client-")
                    and path.endswith(".jar")]
    stale_jars = [path for path in bundled_jars
                  if not _jar_has_cosmetics(REPO / path)]
    checks = {
        "generated outputs are not tracked": not generated,
        "generated outputs remain ignored": set(samples) <= ignored,
        "the server tunnel plugin remains bundled": "assets/jars/connect-spigot.jar" in tracked,
        "companion mod jars remain bundled": any(path.startswith("assets/jars/cubeon-client-") for path in tracked),
        "bundled client jars contain the cosmetic catalogue": not stale_jars,
        "the Gradle wrapper remains available": "mod/gradle/wrapper/gradle-wrapper.jar" in tracked,
        "the agent module map remains tracked": "agents/docs/module-map.md" in tracked,
        "public guides have no tracked agent mirrors": not mirrors,
        "old task diaries are not distributed": not any(
            Path(path).parent == Path("agents") and Path(path).name[:4].isdigit()
            for path in tracked),
        "the current module index stays concise": len(index.splitlines()) <= 300,
        "module index references existing Python files": not missing,
        "public guide names use the organized layout": all(
            (REPO / path).is_file() for path in (
                "docs/user-guide.md", "docs/release/windows-smoke-test.md",
                "docs/reports/2026-09-17-bug-report.md")),
        "README uses the actual website screenshot": 'src="web/assets/cubeon-play.png"' in readme,
        "README badges are flat-square with a live release version":
            "style=flat-square" in readme and "img.shields.io/github/v/release/" in readme,
        "new captures do not repopulate the agent docs":
            'REPO, "archive"' in capture and '"ui-captures"' in capture,
        "runtime Scale transforms set both axes":
            not bad_scales,
    }
    for label, result in checks.items():
        print(f"  {'ok' if result else 'FAIL'}   {label}")
    if generated:
        print("Tracked generated files:\n" + "\n".join(generated))
    if mirrors:
        print("Duplicate agent guides:\n" + "\n".join(sorted(mirrors)))
    if missing:
        print("Missing module references:\n" + "\n".join(sorted(set(missing))))
    if bad_scales:
        print("Scale transforms with an unset axis:\n" + "\n".join(bad_scales))
    if stale_jars:
        print("Bundled jars without cosmetics (rebuild them):\n"
              + "\n".join(sorted(stale_jars)))
    failed = sum(not result for result in checks.values())
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
