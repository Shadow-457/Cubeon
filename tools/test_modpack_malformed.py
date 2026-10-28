"""A malformed pack manifest raises a readable error, not AttributeError (8.10).

`_read_index` returned whatever JSON it parsed and callers immediately used
`.get`, so a manifest that is a JSON list crashed with
`AttributeError: 'list' object has no attribute 'get'`. `files` entries were
assumed to be objects and `env` to be a dict, so one bad element (or
`"env": [...]`) broke the whole install/summary with a raw exception.

Locked-in behaviour:
  * a non-object index is a `ModpackError`;
  * non-object `files` entries are ignored (the rest still installs);
  * a non-object `env` is treated as `{}` (client-required);
  * a non-object `dependencies` becomes `{}` so the readable "doesn't say
    which Minecraft version" error is shown instead of AttributeError.

Run: python tools/test_modpack_malformed.py
"""
import json
import os
import sys
import tempfile
import zipfile

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import modpacks  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def error_of(fn):
    try:
        fn()
    except Exception as ex:
        return ex
    return None


def manifest_zip(path, body):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("modrinth.index.json", body)
    return path


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-malformed-")

    # --- 1. the index itself ------------------------------------------------
    for label, body in (("a JSON list", "[1, 2, 3]"),
                        ("a JSON string", '"just text"')):
        path = manifest_zip(os.path.join(scratch, "bad.mrpack"), body)
        with zipfile.ZipFile(path) as zf:
            ex = error_of(lambda: modpacks._read_index(zf))
        check(f"{label} index raises ModpackError",
              isinstance(ex, modpacks.ModpackError), repr(ex))

    # --- 2. files entries and env ------------------------------------------
    index = {
        "formatVersion": 1, "game": "minecraft", "versionId": "1.0.0",
        "name": "Bad Entries",
        "dependencies": {"minecraft": "1.20.1"},
        "files": ["not-a-file", None, 42, {"path": "mods/good.jar"}],
    }
    ex = error_of(lambda: modpacks.summarize(index))
    check("a non-object file entry does not raise", ex is None, repr(ex))
    info = None
    try:
        info = modpacks.summarize(index)
    except Exception:
        info = None
    check("only the object entry is counted as a mod",
          isinstance(info, dict) and info.get("mod_count") == 1, str(info))

    def wanted(entry):
        try:
            return modpacks._wanted_on_client(entry)
        except Exception:
            return None

    check("a non-dict env does not raise",
          wanted({"path": "mods/x.jar",
                  "env": ["client", "unsupported"]}) is True)
    check("a non-dict env is treated as client-required",
          wanted({"path": "mods/x.jar", "env": "x"}) is True)
    check("a real env still excludes server-only files",
          wanted({"path": "mods/x.jar",
                  "env": {"client": "unsupported"}}) is False)

    # --- 3. dependencies as a non-object -----------------------------------
    ex = error_of(lambda: modpacks.summarize(
        {"files": [], "dependencies": ["minecraft", "1.20.1"]}))
    check("a non-object dependencies block gives a readable error",
          isinstance(ex, modpacks.ModpackError)
          and "Minecraft version" in str(ex), repr(ex))

    # --- 4. a real install ignores the bad entry --------------------------
    game_dir = os.path.join(scratch, "minecraft")
    profiles_dir = os.path.join(scratch, "profiles")
    modpacks.MINECRAFT_DIR = game_dir
    modpacks.PROFILES_DIR = profiles_dir
    from cubeon import content, mods
    mods.MINECRAFT_DIR = game_dir
    mods.PROFILES_DIR = profiles_dir
    content.MINECRAFT_DIR = game_dir
    content.PROFILES_DIR = profiles_dir
    os.makedirs(os.path.join(game_dir, "versions"), exist_ok=True)
    os.makedirs(profiles_dir, exist_ok=True)

    def fake_install_version(version_id, *a, **k):
        folder = os.path.join(game_dir, "versions", version_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, version_id + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"id": version_id}, fh)

    def fake_install_loader(loader_id, mc_version, *a, **k):
        launch_id = f"{loader_id}-loader-0.15.7-{mc_version}"
        folder = os.path.join(game_dir, "versions", launch_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, launch_id + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"id": launch_id, "inheritsFrom": mc_version}, fh)
        return launch_id

    def fake_download_to(dest, urls, hashes=None, **kwargs):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("fabric.mod.json", "{}")

    modpacks.install_version = fake_install_version
    modpacks.install_mod_loader = fake_install_loader
    modpacks._download_to = fake_download_to

    import cubeon.csl as csl
    import cubeon.cubeonfriends as friends
    csl.ensure_ready = lambda *a, **k: None
    friends.ensure_installed = lambda *a, **k: True

    good_index = {
        "formatVersion": 1, "game": "minecraft", "versionId": "1.0.0",
        "name": "Bad Entries",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.7"},
        "files": ["junk", None,
                  {"path": "mods/good.jar", "hashes": {},
                   "downloads": ["https://cdn.modrinth.com/data/x/good.jar"]}],
    }
    archive = manifest_zip(os.path.join(scratch, "badentries.mrpack"),
                           json.dumps(good_index))
    ex = error_of(lambda: modpacks._install_from_zip(archive))
    check("the pack still installs despite the junk entries", ex is None,
          repr(ex))
    if ex is None:
        profile = os.path.join(profiles_dir, "1.20.1-fabric")
        check("the valid mod was downloaded",
              os.path.isfile(os.path.join(profile, "good.jar")),
              str(os.listdir(profile)) if os.path.isdir(profile) else "?")

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
