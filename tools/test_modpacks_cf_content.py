"""Keyless CurseForge entries are checked and bad ones are reported (8.7).

Two problems in `_cf_files_keyless` / the mod download step:

1. A malformed manifest entry raised a raw `KeyError` (`e["projectID"]`), and a
   file whose URL failed the host allowlist was silently skipped - the pack
   installed with mods missing and said nothing.
2. Every entry becomes `mods/<fileID>.jar`, including the pack's resource
   packs/shaders (the real filename is behind a redirect), so a content zip
   landed in the loader's mods folder. Forge/Fabric then error on launch.

Locked-in behaviour:
  * malformed entries and disallowed hosts are counted and reported, never a
    raw exception;
  * a downloaded jar with no mod metadata but with `pack.mcmeta` is moved to the
    instance's resourcepacks folder; a real mod (or an unknown/unreadable jar)
    stays in mods/.

Run: python tools/test_modpacks_cf_content.py
"""
import json
import os
import sys
import tempfile
import zipfile
from unittest.mock import patch

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


def zip_with(path, names):
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, "{}")


def install_pack(scratch, archive, payloads):
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
            json.dump({"id": version_id, "type": "release"}, fh)

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
        zip_with(dest, payloads.get(os.path.basename(dest), ["fabric.mod.json"]))

    modpacks.install_version = fake_install_version
    modpacks.install_mod_loader = fake_install_loader
    modpacks._download_to = fake_download_to

    import cubeon.csl as csl
    import cubeon.cubeonfriends as friends
    csl.ensure_ready = lambda *a, **k: None
    friends.ensure_installed = lambda *a, **k: True

    return modpacks.install_modpack_from_file(archive)


def main():
    # --- 1. malformed / disallowed entries are counted ----------------------
    statuses = []
    entries = [
        {"projectID": 111, "fileID": 222},
        {"projectID": None, "fileID": 333},
        {"fileID": 444},
        "not a dict",
    ]
    files = modpacks._cf_files_keyless(entries, statuses.append)
    check("a malformed entry does not raise", len(files) == 1, str(files))
    check("only the well-formed entry becomes a file",
          [f["path"] for f in files] == ["mods/222.jar"], str(files))
    check("the skipped count is reported to the user",
          any("Skipped 3" in s for s in statuses), str(statuses))

    # A host the installer will not fetch from is counted too, not silent.
    statuses.clear()
    with patch.object(modpacks, "_host_allowed", return_value=False):
        files = modpacks._cf_files_keyless(entries[:1], statuses.append)
    check("a disallowed host is skipped and reported",
          files == [] and any("Skipped 1" in s for s in statuses),
          f"{files} {statuses}")

    # --- 2. a resource pack listed as a mod is relocated --------------------
    scratch = tempfile.mkdtemp(prefix="cubeon-cf-content-")
    archive = os.path.join(scratch, "pack.mrpack")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps({
            "formatVersion": 1, "game": "minecraft", "versionId": "1.0.0",
            "name": "Content Pack", "dependencies": {
                "minecraft": "1.20.1", "fabric-loader": "0.15.7"},
            "files": [
                {"path": "mods/111.jar", "hashes": {},
                 "downloads": ["https://cdn.modrinth.com/data/x/111.jar"]},
                {"path": "mods/222.jar", "hashes": {},
                 "downloads": ["https://cdn.modrinth.com/data/x/222.jar"]},
                {"path": "mods/333.jar", "hashes": {},
                 "downloads": ["https://cdn.modrinth.com/data/x/333.jar"]},
            ],
        }))

    payloads = {
        "111.jar": ["fabric.mod.json"],          # a real mod
        "222.jar": ["pack.mcmeta", "assets/x"],  # really a resource pack
        "333.jar": ["some/unknown/file.txt"],    # unknown: leave it alone
    }
    meta = install_pack(scratch, archive, payloads)
    profile = os.path.join(modpacks.PROFILES_DIR, meta["profile"])
    check("the resource pack moved out of mods/",
          os.path.isfile(os.path.join(profile, "resourcepacks", "222.jar"))
          and not os.path.exists(os.path.join(profile, "222.jar")),
          str(sorted(os.listdir(profile))))
    check("the real mod stayed in the profile",
          os.path.isfile(os.path.join(profile, "111.jar")))
    check("an unidentified jar is not moved",
          os.path.isfile(os.path.join(profile, "333.jar")))
    check("the pack is listed normally",
          meta.get("name") == "Content Pack", str(meta))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
