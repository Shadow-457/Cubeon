"""The Minecraft version comes from the install, not the first number in its name (11.6).

`extract_mc_version()` returns the first `N.N(.N)` it finds, so an
imported/renamed instance such as `Survival 2.0` resolved to `2.0`. Play's
Java check, loader-support check, pack lock and mod profile then all used a
Minecraft version that does not exist.

`resolve_mc_version()` prefers, in order: the instance sidecar's `mc_version`,
the version JSON's `inheritsFrom`/`id` when it is plainly a Minecraft version,
and only then `extract_mc_version` (so every id it already understood keeps
resolving exactly as before).

Run: python tools/test_resolve_mc_version.py
"""
import json
import os
import sys
import tempfile

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import versions  # noqa: E402
import launcher_core as core  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-resolve-mc-")
    game_dir = os.path.join(scratch, "minecraft")
    versions.MINECRAFT_DIR = game_dir
    vdir = os.path.join(game_dir, "versions")

    def version_json(vid, data):
        write(os.path.join(vdir, vid, vid + ".json"), json.dumps(data))

    def sidecar(vid, data):
        write(os.path.join(vdir, vid, "_cubeon_instance.json"), json.dumps(data))

    # --- 1. the instance sidecar wins --------------------------------------
    version_json("Survival 2.0", {"id": "Survival 2.0"})
    sidecar("Survival 2.0", {"mc_version": "1.20.1", "profile": "survival"})
    check("extract_mc_version still reads the name (the old bug)",
          versions.extract_mc_version("Survival 2.0") == "2.0",
          versions.extract_mc_version("Survival 2.0"))
    check("the sidecar's mc_version is used for a renamed instance",
          versions.resolve_mc_version("Survival 2.0") == "1.20.1",
          versions.resolve_mc_version("Survival 2.0"))

    # The sidecar outranks the version json even when both exist.
    version_json("Survival 2.0", {"id": "Survival 2.0",
                                  "inheritsFrom": "1.19.4"})
    check("the sidecar outranks inheritsFrom",
          versions.resolve_mc_version("Survival 2.0") == "1.20.1",
          versions.resolve_mc_version("Survival 2.0"))

    # --- 2. inheritsFrom from the version json ----------------------------
    version_json("My Loader Pack 3.0", {"id": "My Loader Pack 3.0",
                                        "inheritsFrom": "1.21.1"})
    check("inheritsFrom resolves a renamed loader instance",
          versions.resolve_mc_version("My Loader Pack 3.0") == "1.21.1",
          versions.resolve_mc_version("My Loader Pack 3.0"))

    version_json("neoforge-21.1.99",
                 {"id": "neoforge-21.1.99", "inheritsFrom": "1.21.1"})
    check("a NeoForge id resolves through inheritsFrom",
          versions.resolve_mc_version("neoforge-21.1.99") == "1.21.1",
          versions.resolve_mc_version("neoforge-21.1.99"))

    # --- 3. the version json's plain id ----------------------------------
    version_json("renamed-folder", {"id": "1.20.4"})
    check("a plainly-versioned json id is used",
          versions.resolve_mc_version("renamed-folder") == "1.20.4",
          versions.resolve_mc_version("renamed-folder"))

    # --- 4. everything extract_mc_version already handled ----------------
    check("a plain Minecraft id is preserved",
          versions.resolve_mc_version("1.20.1") == "1.20.1",
          versions.resolve_mc_version("1.20.1"))
    check("a fabric-loader id still resolves to the trailing version",
          versions.resolve_mc_version("fabric-loader-0.15.7-1.20.1") == "1.20.1",
          versions.resolve_mc_version("fabric-loader-0.15.7-1.20.1"))
    check("a loader-tagged id that starts with the game version is unchanged",
          versions.resolve_mc_version("1.20.1-forge-47.2.0") == "1.20.1",
          versions.resolve_mc_version("1.20.1-forge-47.2.0"))
    check("no id at all yields an empty string",
          versions.resolve_mc_version(None) == "",
          repr(versions.resolve_mc_version(None)))

    # --- 5. bad/unusable records fall through instead of raising ----------
    sidecar("blank-sidecar", {"profile": "p"})
    version_json("blank-sidecar", {"id": "blank-sidecar",
                                   "inheritsFrom": "not-a-version"})
    check("a sidecar without mc_version falls through to extract",
          versions.resolve_mc_version("blank-sidecar") == "blank-sidecar",
          versions.resolve_mc_version("blank-sidecar"))

    write(os.path.join(vdir, "corrupt", "corrupt.json"), "{not json")
    write(os.path.join(vdir, "corrupt", "_cubeon_instance.json"), "{not json")
    check("corrupt json does not raise",
          versions.resolve_mc_version("corrupt") == "corrupt",
          repr(versions.resolve_mc_version("corrupt")))
    check("a path-like id is not read from disk",
          versions.resolve_mc_version("../escape") == "../escape",
          repr(versions.resolve_mc_version("../escape")))

    # --- 6. the launcher exports it for the Play path --------------------
    check("launcher_core exports resolve_mc_version",
          core.resolve_mc_version is versions.resolve_mc_version)

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
