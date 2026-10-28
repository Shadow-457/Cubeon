"""Dependencies come from the build being installed, not the newest one (9.5).

`required_dependencies()` always read `versions[0]` - the newest build for the
version+loader filter - even when the user installed an older build (a pinned
pack file, or an older release picked on the mod page). A newer build can
require different dependencies, so the wrong mods were pulled in (or a needed
one was missed).

Locked-in behaviour:
  * with a `filename` that matches one of the version's files, that version's
    `dependencies` are used;
  * without one (the doctor cache, old callers) the newest version is used;
  * an unknown filename falls back to the newest version rather than failing;
  * `install_mod_with_dependencies` passes the jar it is installing.

Run: python tools/test_mod_required_deps_version.py
"""
import os
import sys
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import mods  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


VERSIONS = [
    {   # newest: what versions[0] used to pick
        "version_number": "2.0.0",
        "files": [{"filename": "sodium-2.0.0.jar"}],
        "dependencies": [{"project_id": "new-dep", "dependency_type": "required"},
                         {"project_id": "opt-dep", "dependency_type": "optional"}],
    },
    {   # the build the user actually installed
        "version_number": "1.5.0",
        "files": [{"filename": "sodium-1.5.0.jar"},
                  {"filename": "sodium-1.5.0-sources.jar"}],
        "dependencies": [{"project_id": "old-dep", "dependency_type": "required"}],
    },
]


def fake_get_json(url, params=None, headers=None, timeout=None):
    assert "/version" in url, url
    return [dict(v) for v in VERSIONS]


def fake_download(project_id, mc_version=None, loader=None):
    return {"project_id": project_id, "filename": project_id + ".jar",
            "url": "https://cdn/" + project_id, "size_kb": 1, "hashes": {}}


def deps_for(filename):
    with patch.object(mods.net, "get_json", fake_get_json), \
            patch.object(mods, "get_mod_download", fake_download):
        return [d["project_id"] for d in mods.required_dependencies(
            "sodium", "1.20.1", "fabric", filename=filename)]


def main():
    # --- the installed build wins over the newest one ---------------------
    check("the chosen build's dependencies are used",
          deps_for("sodium-1.5.0.jar") == ["old-dep"],
          str(deps_for("sodium-1.5.0.jar")))
    check("the newest build is no longer consulted for an older jar",
          "new-dep" not in deps_for("sodium-1.5.0.jar"))

    # --- backwards compatibility ------------------------------------------
    check("no filename still uses the newest version",
          deps_for(None) == ["new-dep"], str(deps_for(None)))
    check("an unknown filename falls back to the newest version",
          deps_for("some-other.jar") == ["new-dep"],
          str(deps_for("some-other.jar")))
    check("a disabled jar name still matches its build",
          deps_for("sodium-1.5.0.jar.disabled") == ["old-dep"],
          str(deps_for("sodium-1.5.0.jar.disabled")))

    # --- the install path forwards the jar it is installing ---------------
    seen = {}

    def spy(project, mc_version, loader="fabric", filename=None):
        seen.update(project=project, mc=mc_version, loader=loader,
                    filename=filename)
        return []

    mods.require_mod_loader = lambda *a, **k: None
    mods.installed_project_ids = lambda *a, **k: set()
    mods.download_mod = lambda *a, **k: "fake/sodium-1.5.0.jar"
    with patch.object(mods, "required_dependencies", spy):
        mods.install_mod_with_dependencies(
            "https://cdn/sodium-1.5.0.jar", "sodium-1.5.0.jar",
            "1.20.1", "fabric", project_id="sodium-id")
    check("install_mod_with_dependencies passes the installed filename",
          seen.get("filename") == "sodium-1.5.0.jar", str(seen))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
