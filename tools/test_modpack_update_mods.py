"""A pack update must replace its mod set without a data-loss window (8.1).

Reading the installer surfaced two order bugs behind "updating a pack leaves old
mods behind / duplicate-mod crashes":

  1. the previous install's pack-owned jars were deleted BEFORE the new ones
     were downloaded. A failed/cancelled update therefore destroyed the mods of
     a pack that was working a second earlier;
  2. the prune was "all old jars", not "old jars the new pack no longer ships".

This test drives the real ``_install_from_zip_body`` with a fake network and a
scratch game dir:

  * install v1 (keep-a + drop-b + bundled override), then start v2
    (keep-a + new-c) with new-c's download failing -> v1's profile must still be
    intact (nothing pruned before the new set is safely on disk);
  * install v2 successfully -> drop-b is gone, keep-a and new-c are in,
    the bundled override jar stays, and ``jars`` records exactly that set;
  * a jar the user added by hand is never touched.

Run: python tools/test_modpack_update_mods.py
"""
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home

_sandbox_home.isolate()

from cubeon import modpacks, mods  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


_BLOBS = {}


def build_pack(path, mods_spec, *, version="1.0.0"):
    files = []
    for index, (filename, payload) in enumerate(mods_spec):
        url = f"https://cdn.modrinth.com/data/P{index:04d}/versions/v/{filename}"
        _BLOBS[url] = payload
        files.append({
            "path": f"mods/{filename}",
            "downloads": [url],
            "fileSize": len(payload),
            "env": {"client": "required", "server": "required"},
        })
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": version,
        "name": "Update Pack",
        "summary": "reinstall prune fixture",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.7"},
        "files": files,
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))
        zf.writestr("overrides/mods/bundled.jar", b"BUNDLED V1")
        zf.writestr("overrides/config/pack.json", b"{}")


def profile_jars(profile_dir):
    try:
        return sorted(name for name in os.listdir(profile_dir)
                      if name.endswith((".jar", ".jar.disabled")))
    except OSError:
        return []


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-packupdate-")
    game_dir = os.path.join(scratch, "minecraft")
    profiles_dir = os.path.join(scratch, "profiles")
    versions_dir = os.path.join(game_dir, "versions")
    os.makedirs(versions_dir)
    os.makedirs(profiles_dir)

    modpacks.MINECRAFT_DIR = game_dir
    modpacks.PROFILES_DIR = profiles_dir
    mods.MINECRAFT_DIR = game_dir
    mods.PROFILES_DIR = profiles_dir

    def fake_install_version(version_id, *a, **k):
        folder = os.path.join(versions_dir, version_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, version_id + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"id": version_id, "type": "release"}, fh)

    def fake_install_loader(loader_id, mc_version, *a, **k):
        launch_id = f"{loader_id}-loader-0.15.7-{mc_version}"
        folder = os.path.join(versions_dir, launch_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, launch_id + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"id": launch_id, "inheritsFrom": mc_version}, fh)
        with open(os.path.join(folder, "client.jar"), "wb") as fh:
            fh.write(b"FAKE CLIENT JAR")
        return launch_id

    def fake_download(dest_path, urls, hashes=None, progress_cb=None,
                      use_global_cache=False):
        payload = _BLOBS.get(urls[0] if urls else "")
        if payload is None:
            raise RuntimeError("simulated download failure")
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(payload)

    modpacks.install_version = fake_install_version
    modpacks.install_mod_loader = fake_install_loader
    modpacks._download_to = fake_download

    import cubeon.csl as csl
    import cubeon.cubeonfriends as friends
    csl.ensure_ready = lambda *a, **k: None
    friends.ensure_installed = lambda *a, **k: None

    pack_path = os.path.join(scratch, "pack.mrpack")

    # --- v1 -----------------------------------------------------------------
    build_pack(pack_path, [("keep-a.jar", b"A1"), ("drop-b.jar", b"B1")])
    meta = modpacks.install_modpack_from_file(pack_path)
    profile_dir = os.path.join(profiles_dir, meta["profile"])
    v1_expected = ["bundled.jar", "drop-b.jar", "keep-a.jar"]
    check("v1 install: profile holds the pack's jars",
          profile_jars(profile_dir) == v1_expected, str(profile_jars(profile_dir)))
    check("v1 install: the owned jar list is recorded",
          sorted(meta.get("jars") or []) == v1_expected, str(meta.get("jars")))

    user_jar = os.path.join(profile_dir, "my-own-mod.jar")
    with open(user_jar, "wb") as fh:
        fh.write(b"USER MOD")

    # --- v2 successfully ----------------------------------------------------
    build_pack(pack_path, [("keep-a.jar", b"A2"), ("new-c.jar", b"C2")],
               version="2.0.0")
    meta2 = modpacks.install_modpack_from_file(pack_path)
    v2_expected = sorted(["bundled.jar", "keep-a.jar", "new-c.jar",
                          "my-own-mod.jar"])
    check("v2 install: same instance/profile",
          meta2["version_id"] == meta["version_id"]
          and meta2["profile"] == meta["profile"],
          f"{meta2.get('version_id')} / {meta2.get('profile')}")
    check("v2 install: dropped jar removed, new set present, user jar kept",
          profile_jars(profile_dir) == v2_expected,
          str(profile_jars(profile_dir)))
    check("v2 install: the recorded set excludes the dropped and user jars",
          sorted(meta2.get("jars") or [])
          == ["bundled.jar", "keep-a.jar", "new-c.jar"],
          str(meta2.get("jars")))
    check("v2 install: mod_count is the real profile count",
          meta2.get("mod_count") == len(v2_expected),
          str(meta2.get("mod_count")))

    # --- v3 with a failing download ----------------------------------------
    build_pack(pack_path, [("keep-a.jar", b"A3"), ("fail-d.jar", b"D3")],
               version="3.0.0")
    _BLOBS.pop([url for url in _BLOBS
                if url.endswith("/fail-d.jar")][0], None)
    raised = None
    try:
        modpacks.install_modpack_from_file(pack_path)
    except Exception as ex:
        raised = ex
    check("failed update: the download error is reported", raised is not None,
          repr(raised))
    check("failed update: the working pack's mods are still on disk",
          profile_jars(profile_dir) == v2_expected,
          str(profile_jars(profile_dir)))
    check("failed update: the user's jar is untouched", os.path.isfile(user_jar))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
