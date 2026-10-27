"""A failed or cancelled UPDATE must not make a working pack disappear (8.2).

`_install_from_zip_body` used to DELETE the target profile's `_modpack.json`
the moment a rebuild started ("so a half-finished pack never shows as ready").
On a first install that is right; on an update of a working pack a failed
download (or Cancel) then left the pack unlisted - "nothing was marked as
installed" - with its mods half-replaced.

Locked-in behaviour, driven through the real installer with a fake network:
  * while the rebuild runs the marker is hidden as `_modpack.json.bak`
    (so the pack does not show as ready mid-update);
  * a failed update puts it back: the pack is listed again, the previous
    build's mods are intact, no `.bak` is left behind;
  * a successful update replaces the marker and removes the `.bak`;
  * a failed FIRST install leaves no marker at all.

Run: python tools/test_modpack_update_failure_keep.py
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


def build_pack(path, mods_spec, *, name="Keep Pack", version="1.0.0", fail=None):
    files = []
    for index, (filename, payload) in enumerate(mods_spec):
        url = f"https://cdn.modrinth.com/data/P{index:04d}/versions/v/{filename}"
        if filename == fail:
            _BLOBS.pop(url, None)  # simulated download failure
        else:
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
        "name": name,
        "summary": "failed update keeps the pack",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.7"},
        "files": files,
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))


def marker_state(profile_dir):
    names = set()
    try:
        names = set(os.listdir(profile_dir))
    except OSError:
        return ("", "")
    return ("_modpack.json" in names, "_modpack.json.bak" in names)


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-packkeep-")
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

    # --- v1 installs normally ----------------------------------------------
    build_pack(pack_path, [("keep-a.jar", b"A1")])
    meta1 = modpacks.install_modpack_from_file(pack_path)
    profile_dir = os.path.join(profiles_dir, meta1["profile"])
    check("v1 install: the pack is listed",
          any(p.get("name") == "Keep Pack"
              for p in modpacks.list_installed_modpacks()),
          str(modpacks.list_installed_modpacks()))
    check("v1 install: the marker is on disk", marker_state(profile_dir)[0])

    # --- v2 fails halfway ---------------------------------------------------
    seen_mid_update = []

    def status_cb(text):
        if text.startswith("Installing Minecraft") or text.startswith("Downloading mods"):
            # The old marker must already be hidden (not listed as ready),
            # but still on disk as a restorable backup.
            seen_mid_update.append(marker_state(profile_dir))

    build_pack(pack_path, [("keep-a.jar", b"A2"), ("new-c.jar", b"C2")],
               version="2.0.0", fail="new-c.jar")
    raised = None
    try:
        modpacks.install_modpack_from_file(pack_path, status_cb=status_cb)
    except Exception as ex:
        raised = ex
    check("failed update: the error is reported", raised is not None,
          repr(raised))
    check("failed update: the marker was hidden while it ran",
          bool(seen_mid_update) and all(state == (False, True)
                                        for state in seen_mid_update),
          str(seen_mid_update[:3]))
    listed = modpacks.list_installed_modpacks()
    check("failed update: the pack is still listed",
          [p.get("name") for p in listed] == ["Keep Pack"],
          str(listed))
    check("failed update: its marker is restored",
          marker_state(profile_dir) == (True, False),
          str(marker_state(profile_dir)))
    check("failed update: v1's mod is still there",
          os.path.isfile(os.path.join(profile_dir, "keep-a.jar")))

    # --- v2 succeeds --------------------------------------------------------
    build_pack(pack_path, [("keep-a.jar", b"A2"), ("new-c.jar", b"C2")],
               version="2.0.0")
    meta2 = modpacks.install_modpack_from_file(pack_path)
    check("v2 install: same instance", meta2["version_id"] == meta1["version_id"],
          f"{meta2.get('version_id')} / {meta1.get('version_id')}")
    check("v2 install: only the new marker is left",
          marker_state(profile_dir) == (True, False),
          str(marker_state(profile_dir)))
    with open(os.path.join(profile_dir, "_modpack.json"), encoding="utf-8") as fh:
        saved = json.load(fh)
    check("v2 install: the marker holds the new pack version",
          saved.get("pack_version") == "2.0.0", str(saved.get("pack_version")))
    check("v2 install: no .bak survived",
          not os.path.exists(os.path.join(profile_dir, "_modpack.json.bak")))

    # --- a failed FIRST install leaves nothing behind -----------------------
    build_pack(pack_path, [("first-fail.jar", b"X")], name="Fresh Pack",
               fail="first-fail.jar")
    raised = None
    try:
        modpacks.install_modpack_from_file(pack_path)
    except Exception as ex:
        raised = ex
    check("failed first install: the error is reported", raised is not None,
          repr(raised))
    fresh = [p for p in modpacks.list_installed_modpacks()
             if p.get("name") == "Fresh Pack"]
    check("failed first install: nothing is listed as installed", not fresh,
          str(fresh))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
