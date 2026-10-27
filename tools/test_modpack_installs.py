"""
Offline checks for modpack install idempotency and instance scoping.

Report (2026-10-26): installing one pack produced TWO "installed" rows with
different mod counts (30 and 70), every reinstall only ADDED jars, and starting
a pack install for one Minecraft version disabled the Play button on an
unrelated real instance that merely shared a version prefix.

This test drives the real ``_install_from_zip_body`` bookkeeping with a fake
network and a scratch game dir. What it pins down:
  * one pack = one installed row and one isolated version folder, even after
    several reinstalls;
  * ``mod_count`` is the REAL number of jars in the profile (the same number
    ``instances.mod_count()`` reports), not the manifest's file list;
  * a reinstall REPLACES the pack's jars (old ones pruned), while a jar the
    user added by hand survives;
  * ``list_installed_modpacks()`` de-duplicates a legacy marker and its clone;
  * the in-flight claim is scoped to the pack's OWN instance: a 26.2 install
    must not lock a 26.3 instance (or a bare vanilla folder).

No network, no display, no real Minecraft: ``install_version`` /
``install_mod_loader`` only create the version folders a clone needs,
``_download_to`` writes known bytes, and HOME is redirected before cubeon
binds its paths.
"""
import json
import os
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home

_sandbox_home.isolate()

from cubeon import modpacks, mods  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


# --- fake network: URL -> bytes -------------------------------------------
_BLOBS = {}


def build_pack(path, *, name, mc_version, loader, loader_version, mods_spec,
               bundled=b"BUNDLED OVERRIDE JAR"):
    """A minimal .mrpack with `mods_spec` = [(filename, bytes), ...]."""
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
        "versionId": "1.0.0",
        "name": name,
        "summary": "install idempotency fixture",
        "dependencies": {"minecraft": mc_version, f"{loader}-loader": loader_version},
        "files": files,
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))
        if bundled is not None:
            zf.writestr("overrides/mods/bundled.jar", bundled)
        zf.writestr("overrides/config/pack.json", b"{}")


def profile_jars(profile_dir):
    try:
        return sorted(name for name in os.listdir(profile_dir)
                      if name.endswith((".jar", ".jar.disabled")))
    except OSError:
        return []


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-packidem-")
    game_dir = os.path.join(scratch, "minecraft")
    profiles_dir = os.path.join(scratch, "profiles")
    versions_dir = os.path.join(game_dir, "versions")
    os.makedirs(versions_dir)
    os.makedirs(profiles_dir)

    # Redirect every path the installer and the count helper read. modpacks
    # imported these names directly, and mods.py holds the implementations.
    modpacks.MINECRAFT_DIR = game_dir
    modpacks.PROFILES_DIR = profiles_dir
    mods.MINECRAFT_DIR = game_dir
    mods.PROFILES_DIR = profiles_dir

    # --- stubs: only what a real install would need from outside ----------
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
            raise AssertionError(f"unexpected download URL: {urls!r}")
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(payload)

    modpacks.install_version = fake_install_version
    modpacks.install_mod_loader = fake_install_loader
    modpacks._download_to = fake_download

    # Cubeon's own client mods (skins, Friends) are injected into the pack
    # profile at install time. They are not pack content, so neutralise them
    # here to keep the expected jar count exact.
    import cubeon.csl as csl
    import cubeon.cubeonfriends as friends
    csl.ensure_ready = lambda *a, **k: None
    friends.ensure_installed = lambda *a, **k: None

    mc, loader = "1.20.1", "fabric"
    legacy_profile = os.path.join(profiles_dir, mods.profile_key(mc, loader))

    # A hand-built instance already owns the legacy profile. The pack must NOT
    # merge into it; it gets its own clone + private profile.
    os.makedirs(legacy_profile, exist_ok=True)
    with open(os.path.join(legacy_profile, "my-handbuilt-mod.jar"), "wb") as fh:
        fh.write(b"HAND BUILT")

    pack_path = os.path.join(scratch, "pack.mrpack")

    def install(mods_spec):
        build_pack(pack_path, name="Idem Pack", mc_version=mc, loader=loader,
                   loader_version="0.15.7", mods_spec=mods_spec)
        return modpacks.install_modpack_from_file(pack_path)

    # --- install once: one row, one clone, real count ----------------------
    meta = install([("sodium.jar", b"SODIUM"), ("lithium.jar", b"LITHIUM"),
                    ("iris.jar", b"IRIS")])
    profile_dir = os.path.join(profiles_dir, meta["profile"])
    check("install: returns its own private profile",
          meta["profile"] != mods.profile_key(mc, loader), meta["profile"])
    check("install: the hand-built profile is untouched",
          os.path.isfile(os.path.join(legacy_profile, "my-handbuilt-mod.jar"))
          and profile_jars(legacy_profile) == ["my-handbuilt-mod.jar"],
          str(profile_jars(legacy_profile)))
    clones = [name for name in os.listdir(versions_dir)
              if name.startswith("1.20.1-fabric-idem-pack")]
    check("install: exactly one isolated version folder (plus the sources)",
          clones == ["1.20.1-fabric-idem-pack"],
          f"{clones} in {sorted(os.listdir(versions_dir))}")
    check("install: one installed row",
          len(modpacks.list_installed_modpacks()) == 1,
          str(modpacks.list_installed_modpacks()))
    check("install: the instance sidecar points at the private profile",
          (mods.read_instance_meta(meta["version_id"]) or {}).get("profile")
          == meta["profile"],
          str(mods.read_instance_meta(meta["version_id"])))
    expected = ["bundled.jar", "iris.jar", "lithium.jar", "sodium.jar"]
    check("install: profile holds exactly the pack's jars",
          profile_jars(profile_dir) == expected, str(profile_jars(profile_dir)))
    check("install: mod_count is the REAL jar count, not the manifest list",
          meta["mod_count"] == len(expected) == 4, str(meta.get("mod_count")))
    from cubeon import instances
    check("install: mod_count matches instances.mod_count()",
          instances.mod_count(mc, loader, meta["version_id"]) == meta["mod_count"],
          str(instances.mod_count(mc, loader, meta["version_id"])))
    check("install: the pack-owned jar list is recorded",
          sorted(meta.get("jars") or []) == expected, str(meta.get("jars")))
    check("install: the claim is released",
          modpacks.pack_install_for_instance(meta["version_id"]) is None)

    # --- reinstall with a bigger, DIFFERENT mod set -----------------------
    new_names = [f"reinstall-{i}.jar" for i in range(1, 8)]
    meta2 = install([(name, name.encode()) for name in new_names])
    expected2 = sorted(new_names + ["bundled.jar"])
    check("reinstall: same instance, not a second copy",
          meta2["version_id"] == meta["version_id"]
          and meta2["profile"] == meta["profile"],
          f"{meta2.get('version_id')} / {meta2.get('profile')}")
    check("reinstall: still one installed row",
          len(modpacks.list_installed_modpacks()) == 1,
          str(modpacks.list_installed_modpacks()))
    clones = [name for name in os.listdir(versions_dir)
              if name.startswith("1.20.1-fabric-idem-pack")]
    check("reinstall: still exactly one isolated version folder",
          clones == ["1.20.1-fabric-idem-pack"],
          f"{clones} in {sorted(os.listdir(versions_dir))}")
    check("reinstall: the old pack jars are pruned, not accumulated",
          profile_jars(profile_dir) == expected2, str(profile_jars(profile_dir)))
    check("reinstall: mod_count tracks the new set",
          meta2["mod_count"] == len(expected2) == 8, str(meta2.get("mod_count")))
    check("reinstall: mod_count matches instances.mod_count()",
          instances.mod_count(mc, loader, meta2["version_id"]) == 8,
          str(instances.mod_count(mc, loader, meta2["version_id"])))

    # --- a user-added jar survives a reinstall ----------------------------
    user_jar = os.path.join(profile_dir, "my-own-mod.jar")
    with open(user_jar, "wb") as fh:
        fh.write(b"USER MOD")
    meta3 = install([("tiny-a.jar", b"A"), ("tiny-b.jar", b"B")])
    check("reinstall: a hand-added jar is not treated as pack-owned",
          os.path.isfile(user_jar), str(profile_jars(profile_dir)))
    check("reinstall: pack jars shrink to the new manifest",
          profile_jars(profile_dir)
          == sorted(["bundled.jar", "my-own-mod.jar", "tiny-a.jar", "tiny-b.jar"]),
          str(profile_jars(profile_dir)))
    check("reinstall: mod_count includes the user's jar",
          meta3["mod_count"] == 4, str(meta3.get("mod_count")))
    check("reinstall: the recorded pack-owned list excludes the user's jar",
          sorted(meta3.get("jars") or [])
          == sorted(["bundled.jar", "tiny-a.jar", "tiny-b.jar"]),
          str(meta3.get("jars")))

    # --- de-duplicate a legacy marker next to the isolated clone ----------
    stale_dir = os.path.join(profiles_dir, "1.20.1-fabric-idem-pack-stale")
    os.makedirs(stale_dir, exist_ok=True)
    stale_marker = os.path.join(stale_dir, modpacks.MODPACK_META_FILENAME)
    with open(stale_marker, "w", encoding="utf-8") as fh:
        json.dump({"name": "Idem Pack", "mc_version": mc, "loader": loader,
                   "profile": "1.20.1-fabric-idem-pack-stale",
                   "version_id": "a-version-that-does-not-exist",
                   "mod_count": 30}, fh)
    # Make the stale marker NEWER: the existing version folder must still win.
    future = time.time() + 60
    os.utime(stale_marker, (future, future))
    listed = modpacks.list_installed_modpacks()
    check("dedupe: one row for one pack identity", len(listed) == 1,
          str([(m.get("name"), m.get("profile")) for m in listed]))
    check("dedupe: the entry whose version folder exists wins",
          listed and listed[0].get("version_id") == meta3["version_id"],
          str(listed[0].get("version_id") if listed else None))
    os.remove(stale_marker)
    os.rmdir(stale_dir)

    # --- instance-scoped in-flight claims --------------------------------
    # A real 26.3 instance the user can play, plus a bare vanilla folder with
    # no sidecar (deliberately unmatched: a 26.2 pack writes its own clone).
    real_263 = "26.3-fabric-real"
    os.makedirs(os.path.join(versions_dir, real_263), exist_ok=True)
    mods.write_instance_meta(real_263, {
        "profile": "26.3-fabric-real-profile",
        "name": "My 26.3 world",
        "mc_version": "26.3",
        "loader": "fabric",
    })
    os.makedirs(os.path.join(versions_dir, "26.3"), exist_ok=True)

    claim_vid = "26.2-fabric-other-pack"
    modpacks._mark_pack_install("26.2", "Other Pack", exclusive=True,
                                profile="26.2-fabric-other-pack-profile",
                                version_id=claim_vid)
    try:
        check("claim: the pack's OWN instance is locked",
              modpacks.pack_install_for_instance(claim_vid) == "Other Pack",
              str(modpacks.pack_install_for_instance(claim_vid)))
        check("claim: a real 26.3 instance is NOT locked",
              modpacks.pack_install_for_instance(real_263) is None,
              str(modpacks.pack_install_for_instance(real_263)))
        check("claim: a bare 26.3 vanilla folder is NOT locked",
              modpacks.pack_install_for_instance("26.3") is None,
              str(modpacks.pack_install_for_instance("26.3")))
        check("claim: the base-version view still reports the install",
              modpacks.pack_install_for("26.2") == "Other Pack",
              str(modpacks.pack_install_for("26.2")))
    finally:
        modpacks._unmark_pack_install("26.2")

    # A claim that only knows the profile (no version id yet) still matches
    # the instance whose sidecar names that profile - and nothing else.
    modpacks._mark_pack_install("26.2", "Early Pack", exclusive=True,
                                profile="26.3-fabric-real-profile")
    try:
        check("claim: a profile-only claim matches its own instance sidecar",
              modpacks.pack_install_for_instance(real_263) == "Early Pack",
              str(modpacks.pack_install_for_instance(real_263)))
        check("claim: an unrelated bare folder still is not matched",
              modpacks.pack_install_for_instance("26.3") is None)
    finally:
        modpacks._unmark_pack_install("26.2")
    check("claim: nothing is left claimed after cleanup",
          modpacks.active_pack_installs() == {},
          str(modpacks.active_pack_installs()))

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
