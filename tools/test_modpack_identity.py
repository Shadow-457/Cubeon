"""Two different packs with the same display name stay two instances (8.9).

`_find_installed_pack` matched on name + Minecraft version + loader only, so
installing a second pack called e.g. "Better Adventures" was treated as an
update of the first: it reused that pack's profile/instance and replaced its
mods and record.

Locked-in behaviour:
  * `_modpack.json` records the browse hit's project id as `source_id`;
  * `_find_installed_pack` requires source ids to be equal when BOTH sides
    have one, and still matches when only one side (an older install, an
    imported file) knows it;
  * a second install with a different source id gets its own profile and
    version folder, and does not overwrite the first pack's record.

Run: python tools/test_modpack_identity.py
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


def main():
    # --- 1. the matcher itself ---------------------------------------------
    modpacks.MINECRAFT_DIR = tempfile.mkdtemp(prefix="cubeon-pid-game-")
    stored = [{"name": "Better Adventures", "mc_version": "1.20.1",
               "loader": "fabric", "source_id": "modrinth:AAA",
               "version_id": "1.20.1-fabric-better-adventures"}]
    with patch.object(modpacks, "list_installed_modpacks", lambda: list(stored)):
        same = modpacks._find_installed_pack(
            "Better Adventures", "1.20.1", "fabric", source_id="modrinth:AAA")
        check("the same source id is the same pack", bool(same), str(same))
        other = modpacks._find_installed_pack(
            "Better Adventures", "1.20.1", "fabric", source_id="modrinth:BBB")
        check("a different source id is a different pack", other is None,
              str(other))
        unknown = modpacks._find_installed_pack(
            "Better Adventures", "1.20.1", "fabric")
        check("a caller without an id still matches (old records)",
              bool(unknown), str(unknown))

    stored_no_id = [{"name": "Better Adventures", "mc_version": "1.20.1",
                     "loader": "fabric", "version_id": "legacy"}]
    with patch.object(modpacks, "list_installed_modpacks",
                      lambda: list(stored_no_id)):
        imported = modpacks._find_installed_pack(
            "Better Adventures", "1.20.1", "fabric", source_id="modrinth:BBB")
        check("an id on only one side is not proof of a different pack",
              bool(imported), str(imported))

    # --- 2. two real installs with the same name ---------------------------
    scratch = tempfile.mkdtemp(prefix="cubeon-packid-")
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
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("fabric.mod.json", "{}")

    modpacks.install_version = fake_install_version
    modpacks.install_mod_loader = fake_install_loader
    modpacks._download_to = fake_download_to

    import cubeon.csl as csl
    import cubeon.cubeonfriends as friends
    csl.ensure_ready = lambda *a, **k: None
    friends.ensure_installed = lambda *a, **k: True

    def make_archive(mod_name):
        archive = os.path.join(scratch, mod_name + ".mrpack")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("modrinth.index.json", json.dumps({
                "formatVersion": 1, "game": "minecraft", "versionId": "1.0.0",
                "name": "Better Adventures",
                "dependencies": {"minecraft": "1.20.1",
                                 "fabric-loader": "0.15.7"},
                "files": [{"path": f"mods/{mod_name}.jar", "hashes": {},
                           "downloads": [f"https://cdn.modrinth.com/data/x/{mod_name}.jar"]}],
            }))
        return archive

    def install(archive, source_id):
        return modpacks._install_from_zip(archive, source_id=source_id)

    first = install(make_archive("aaa"), "modrinth:AAA")
    second = install(make_archive("bbb"), "modrinth:BBB")

    check("the first pack records its source id",
          first.get("source_id") == "modrinth:AAA", str(first))
    check("the second pack records its own source id",
          second.get("source_id") == "modrinth:BBB", str(second))
    check("the second pack does not reuse the first instance",
          second.get("version_id") != first.get("version_id"),
          f"{first.get('version_id')} vs {second.get('version_id')}")
    check("the second pack does not reuse the first profile",
          second.get("profile") != first.get("profile"),
          f"{first.get('profile')!r} vs {second.get('profile')!r}")

    # Both records are on disk with their own identity; the second install
    # must not have overwritten the first one.
    markers = []
    for root, _dirs, files in os.walk(profiles_dir):
        if modpacks.MODPACK_META_FILENAME in files:
            with open(os.path.join(root, modpacks.MODPACK_META_FILENAME),
                      encoding="utf-8") as fh:
                markers.append(json.load(fh))
    sources = sorted(m.get("source_id") for m in markers)
    check("both installs keep a marker with their own source id",
          sources == ["modrinth:AAA", "modrinth:BBB"], str(sources))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
