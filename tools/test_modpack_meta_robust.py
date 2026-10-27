"""Corrupt pack markers must not break the list, and the marker write is atomic (8.5, 8.6).

8.5: `list_installed_modpacks()` / `forget_modpack_for_version()` only caught
`json.JSONDecodeError`, so a marker with invalid UTF-8 (a `ValueError`) broke
the whole "Installed packs" list; `forget_modpack_for_version()` also called
`.get()` on whatever JSON it got (a list has no `.get`).
8.6: `_modpack.json` was written with a plain `open("w") + json.dump` whose
failure was swallowed - the install reported success for a pack that would
never be listed or played.

Run: python tools/test_modpack_meta_robust.py
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

from cubeon import atomicio, modpacks, mods  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-meta-")
    game_dir = os.path.join(scratch, "minecraft")
    profiles_dir = os.path.join(scratch, "profiles")
    os.makedirs(os.path.join(game_dir, "versions"))
    os.makedirs(profiles_dir)
    modpacks.MINECRAFT_DIR = game_dir
    modpacks.PROFILES_DIR = profiles_dir
    mods.MINECRAFT_DIR = game_dir
    mods.PROFILES_DIR = profiles_dir

    def marker(folder, payload):
        path = os.path.join(profiles_dir, folder)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "_modpack.json"), "wb") as fh:
            fh.write(payload)

    marker("good", json.dumps({"name": "Good Pack", "mc_version": "1.20.1",
                               "loader": "fabric", "version_id": "good-1"}).encode())
    # Invalid UTF-8: json.load raises UnicodeDecodeError, a ValueError.
    marker("bad-utf8", b'{"name": "\xff\xfe broken"}')
    # Valid JSON, wrong shape: a list has no .get().
    marker("bad-shape", b'["not", "a", "dict"]')

    listed = modpacks.list_installed_modpacks()
    check("a corrupt UTF-8 marker does not break the list",
          [p.get("name") for p in listed] == ["Good Pack"], str(listed))
    try:
        forgot = modpacks.forget_modpack_for_version("whatever")
        raised = None
    except Exception as ex:
        forgot, raised = False, ex
    check("forget_modpack_for_version survives a non-dict marker",
          raised is None and forgot is False, repr(raised))
    check("the good marker was left alone", len(listed) == 1)

    # --- 8.6: a failing marker write is an error, not a silent success ------
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

    modpacks.install_version = fake_install_version
    modpacks.install_mod_loader = fake_install_loader
    modpacks._download_to = lambda *a, **k: None

    import cubeon.csl as csl
    import cubeon.cubeonfriends as friends
    csl.ensure_ready = lambda *a, **k: None
    friends.ensure_installed = lambda *a, **k: None

    archive = os.path.join(scratch, "empty.mrpack")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps({
            "formatVersion": 1, "game": "minecraft", "versionId": "1.0.0",
            "name": "Marker Pack", "dependencies": {
                "minecraft": "1.20.1", "fabric-loader": "0.15.7"},
            "files": [],
        }))

    real_write = atomicio.write_json

    def flaky_write(path, data, indent=2):
        if str(path).endswith("_modpack.json"):
            raise OSError("disk full")
        return real_write(path, data, indent)

    raised = None
    with patch.object(atomicio, "write_json", flaky_write):
        try:
            modpacks.install_modpack_from_file(archive)
        except Exception as ex:
            raised = ex
    check("a failed marker write raises ModpackError",
          isinstance(raised, modpacks.ModpackError)
          and "Couldn't save the modpack record" in str(raised), repr(raised))
    check("the pack is not reported as installed",
          "Marker Pack" not in [p.get("name")
                                for p in modpacks.list_installed_modpacks()])

    # And with the real writer it installs and lists normally.
    meta = modpacks.install_modpack_from_file(archive)
    check("with a working write the pack is listed",
          "Marker Pack" in [p.get("name")
                            for p in modpacks.list_installed_modpacks()],
          str(meta))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
