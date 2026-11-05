"""A failed skins/Friends injection is reported, not swallowed (8.11).

`_install_from_zip_body` wrapped `csl.ensure_ready()` and
`cubeonfriends.ensure_installed()` in `except Exception: pass`. When skins or
the Friends button vanished there was no log and no status line, so it looked
like the feature had simply never existed. The install must still succeed.

Locked-in behaviour:
  * a raising skin setup logs a warning and emits "Skin support could not be
    set up";
  * a raising Friends install logs a warning and emits "Friends button could
    not be set up";
  * neither failure fails the pack install.

Run: python tools/test_modpack_client_mods_errors.py
"""
import json
import logging
import os
import sys
import tempfile
from unittest.mock import patch
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


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-clientmods-")
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
    import cubeon.config as config
    real_skin_setup = csl.ensure_ready

    def boom(*a, **k):
        raise RuntimeError("injection backend exploded")

    csl.ensure_ready = boom
    friends.ensure_installed = boom

    archive = os.path.join(scratch, "pack.mrpack")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps({
            "formatVersion": 1, "game": "minecraft", "versionId": "1.0.0",
            "name": "Client Mods",
            "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.7"},
            "files": [{"path": "mods/a.jar", "hashes": {},
                       "downloads": ["https://cdn.modrinth.com/data/x/a.jar"]}],
        }))

    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = Capture()
    logger = modpacks.log
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    statuses = []
    meta = None
    exc = None
    try:
        try:
            meta = modpacks._install_from_zip(archive, status_cb=statuses.append)
        except Exception as ex:
            exc = ex
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    check("the install still succeeds", exc is None and meta is not None,
          repr(exc))
    check("a skins failure is reported to the user",
          any("Skin support could not be set up" in s for s in statuses),
          str(statuses))
    check("a Friends failure is reported to the user",
          any("Friends button could not be set up" in s for s in statuses),
          str(statuses))
    messages = [r.getMessage() for r in records]
    check("the skins failure is logged with a traceback",
          any("skin support" in m.lower() for m in messages)
          and any(r.exc_info for r in records if "skin support" in r.getMessage().lower()),
          str(messages))
    check("the Friends failure is logged with a traceback",
          any("friends mod" in m.lower() for m in messages)
          and any(r.exc_info for r in records if "friends mod" in r.getMessage().lower()),
          str(messages))
    check("the pack was still recorded as installed",
          meta is not None and meta.get("name") == "Client Mods", str(meta))

    def download_packed_csl(dest, urls, hashes=None, **kwargs):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zipfile.ZipFile(dest, "w") as zf:
            # CSL in a pack can have an opaque name. Its descriptor must
            # still identify it when Settings disables skins.
            zf.writestr("fabric.mod.json", json.dumps({"id": "customskinloader", "version": "1.0"}))

    for client_on, skin_on in ((False, False), (True, False), (False, True), (True, True)):
        choice = {"client_mod_enabled": client_on, "csl_enabled": skin_on}
        with patch.object(config, "load_config", return_value=choice), \
                patch.object(modpacks, "_download_to", side_effect=download_packed_csl), \
                patch.object(csl, "ensure_ready", wraps=real_skin_setup) as skin_setup, \
                patch.object(csl, "install", side_effect=AssertionError("Unexpected skin download")) as skin_download, \
                patch.object(friends, "ensure_installed", return_value=True) as client_setup:
            installed = modpacks._install_from_zip(archive)
            active = [m for m in mods.list_mods("1.20.1", "fabric", installed["version_id"])
                      if m["enabled"] and m["filename"] == "a.jar"]
            check(f"pack client={client_on}, CSL={skin_on} honors independent choices",
                  bool(active) == skin_on and bool(client_setup.call_count) == client_on
                  and skin_setup.call_args.kwargs["manage"] == skin_on
                  and skin_download.call_count == 0)

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
