"""
Offline regression suite for the global mods store <-> profile link engine and
the launch-time sync (cubeon/global_mod_cache.py + cubeon/mods.py).

No network, no display. Everything runs under a sandboxed HOME, so the store,
profiles and the game's mods/ dir are all real files in a tempdir - the point
is to exercise the actual bytes-on-disk logic: deduping, human naming, cross
profile reuse, disabled handling, and (the reason this suite exists) what
happens when a profile holds a dangling link into the store.

Covers regressions that used to be real failures:
  - sync_mods_to_game() crashed the whole launch on the FIRST dangling link in
    a profile (FileNotFoundError from link/copy), so a single deleted store
    file made every launch die before the game started.
  - delete_mod() silently left dangling links behind: it removed the sidecar
    but os.path.exists() is False for a dead link, so the jar entry itself
    survived forever.
  - list_profiles()/list_mods() counting or crashing on dead links.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

from cubeon import global_mod_cache as store  # noqa: E402
from cubeon import mods  # noqa: E402
from cubeon.paths import GLOBAL_MODS_DIR, MODS_DIR, PROFILES_DIR  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


def store_files():
    if not os.path.isdir(GLOBAL_MODS_DIR):
        return []
    return [f for f in os.listdir(GLOBAL_MODS_DIR)
            if f.endswith(".jar") and not f.startswith(".")]


def main():
    # --- store engine: dedupe + human naming -------------------------------
    a1 = tempfile.NamedTemporaryFile(suffix=".jar", delete=False)
    a1.write(b"A" * 100)
    a1.close()
    a2 = tempfile.NamedTemporaryFile(suffix=".jar", delete=False)
    a2.write(b"B" * 100)
    a2.close()

    p1 = os.path.join(PROFILES_DIR, "1.20.1-fabric")
    os.makedirs(p1, exist_ok=True)

    dest1 = os.path.join(p1, "sodium-0.1.jar")
    dest2 = os.path.join(p1, "sodium-0.2.jar")

    store.put_file(a1.name, dest1)
    check("put_file: stores one real jar under a human name",
          os.path.islink(dest1) and os.path.isfile(dest1))
    check("put_file: store holds exactly one file for the first install",
          store_files() == ["sodium-0.1.jar"], store_files())

    # Same bytes under a second name must NOT duplicate the store copy.
    store.put_file(a1.name, dest2)
    check("put_file: identical bytes reuse the stored copy (no dup in store)",
          store_files() == ["sodium-0.1.jar"], store_files())
    check("put_file: second profile link also resolves to the same bytes",
          os.readlink(dest2) == os.path.join(GLOBAL_MODS_DIR, "sodium-0.1.jar")
          or open(dest2, "rb").read() == b"A" * 100)

    original_link = os.lstat(dest2)
    store.put_file(a1.name, dest2)
    after_link = os.lstat(dest2)
    check("put_file: unchanged profile link keeps its inode and ctime",
          (original_link.st_ino, original_link.st_ctime_ns) ==
          (after_link.st_ino, after_link.st_ctime_ns))

    # Different bytes with the same human name get disambiguated, never clobber.
    dest3 = os.path.join(p1, "sodium-0.1.jar")  # name clash with different bytes
    store.put_file(a2.name, dest3)
    files = sorted(store_files())
    check("put_file: differing bytes under a taken name are disambiguated",
          len(files) == 2 and any("sodium-0.1." in f for f in files), files)
    check("put_file: both distinct jars readable",
          all(os.path.isfile(os.path.join(GLOBAL_MODS_DIR, f)) for f in files))

    # --- list_profiles: count matches what list_mods shows -----------------
    profiles = mods.list_profiles()
    this = [p for p in profiles if p["key"] == "1.20.1-fabric"]
    check("list_profiles: profile visible with correct count",
          this and this[0]["mod_count"] == 2, this)

    # --- sync: disabled jars skipped, stale game mods wiped, dedupe ---------
    # Enable/disable: name one of the profile entries as disabled.
    os.rename(os.path.join(p1, "sodium-0.2.jar"),
              os.path.join(p1, "sodium-0.2.jar.disabled"))
    # A leftover jar in the game mods dir from a different profile must be wiped.
    os.makedirs(MODS_DIR, exist_ok=True)
    stale = os.path.join(MODS_DIR, "stale-other-profile.jar")
    with open(stale, "wb") as f:
        f.write(b"OLD")

    mods.sync_mods_to_game("1.20.1", "fabric")
    game = set(os.listdir(MODS_DIR))
    check("sync: stale game mods wiped",
          "stale-other-profile.jar" not in game, game)
    check("sync: disabled jar NOT synced to game",
          "sodium-0.2.jar" not in game, game)
    check("sync: enabled jar synced to game",
          "sodium-0.1.jar" in game, game)

    staged = os.path.join(MODS_DIR, "sodium-0.1.jar")
    manifest = os.path.join(MODS_DIR, mods._SYNC_MANIFEST)
    original_jar, original_manifest = os.stat(staged), os.stat(manifest)
    mods.sync_mods_to_game("1.20.1", "fabric")
    check("sync: unchanged relaunch leaves jar ctime untouched",
          os.stat(staged).st_ctime_ns == original_jar.st_ctime_ns)
    check("sync: unchanged relaunch leaves ownership manifest untouched",
          os.stat(manifest).st_ctime_ns == original_manifest.st_ctime_ns)

    # Another profile can use the same filename/size for DIFFERENT bytes.
    alternate = os.path.join(PROFILES_DIR, "1.21.1-fabric")
    os.makedirs(alternate, exist_ok=True)
    with open(os.path.join(alternate, "sodium-0.1.jar"), "wb") as fh:
        fh.write(b"C" * 100)
    mods.sync_mods_to_game("1.21.1", "fabric")
    check("sync: same-named jar from another profile replaces old bytes",
          open(staged, "rb").read() == b"C" * 100)
    mods.sync_mods_to_game("1.20.1", "fabric")
    check("sync: switching back restores the selected profile's bytes",
          open(staged, "rb").read() == b"B" * 100)

    os.rename(os.path.join(p1, "sodium-0.1.jar"),
              os.path.join(p1, "sodium-0.1.jar.disabled"))
    mods.sync_mods_to_game("1.20.1", "fabric")
    check("sync: disabling a retained jar removes it from the game",
          not os.path.lexists(staged))
    os.rename(os.path.join(p1, "sodium-0.1.jar.disabled"),
              os.path.join(p1, "sodium-0.1.jar"))
    mods.sync_mods_to_game("1.20.1", "fabric")

    mods.sync_mods_to_game("1.20.1", "vanilla")
    check("sync: vanilla clears every managed jar",
          not any(name.endswith(".jar") for name in os.listdir(MODS_DIR)))
    mods.sync_mods_to_game("1.20.1", "fabric")

    # A dead managed link has no bytes, but still needs to lose its filename.
    dead_staged = os.path.join(MODS_DIR, "missing-staged.jar")
    os.symlink(os.path.join(MODS_DIR, "no-such-store-file"), dead_staged)
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump({"files": ["sodium-0.1.jar", "missing-staged.jar"]}, fh)
    mods.sync_mods_to_game("1.20.1", "fabric")
    check("sync: dangling managed game link is removed",
          not os.path.lexists(dead_staged))

    # --- DANGLE LINK REGRESSIONS (the reason this suite exists) -------------
    # Simulate a store file that was deleted/moved out from under a profile
    # link (pre-global-store links into an old cache, manual store cleanup,
    # a removed pack's shared jar, ...).
    dead_src = tempfile.NamedTemporaryFile(suffix=".jar", delete=False)
    dead_src.write(b"GHOST")
    dead_src.close()
    dead_profile = os.path.join(p1, "ghost-1.0.jar")
    store.put_file(dead_src.name, dead_profile)   # proper store-backed entry
    os.remove(dead_src.name)
    dead_store = os.path.join(GLOBAL_MODS_DIR, "ghost-1.0.jar")
    os.remove(dead_store)                          # ...then the store copy vanishes

    check("dangle: link target really is gone",
          os.path.islink(dead_profile) and not os.path.exists(dead_profile))

    listed = [m["filename"] for m in mods.list_mods("1.20.1", "fabric")]
    check("list_mods: dangling link skipped, not listed",
          "ghost-1.0.jar" not in listed and "sodium-0.1.jar" in listed, listed)
    check("list_mods: does not crash on dangling links", True)

    # sync_mods_to_game must survive the dangle and still ship the good mod.
    game_dir = MODS_DIR
    for f in os.listdir(game_dir):
        os.remove(os.path.join(game_dir, f))
    try:
        mods.sync_mods_to_game("1.20.1", "fabric")
        check("sync: does not crash on a dangling profile link", True)
    except Exception as ex:
        check("sync: does not crash on a dangling profile link", False, repr(ex))
    game = set(os.listdir(MODS_DIR))
    check("sync: good mod still synced despite the dangle",
          "sodium-0.1.jar" in game, game)
    check("sync: dangled jar NOT placed in game mods",
          "ghost-1.0.jar" not in game, game)

    # delete_mod must remove the dangling link (os.path.lexists), not leave it.
    try:
        mods.delete_mod("1.20.1", "fabric", "ghost-1.0.jar")
        check("delete_mod: removes a dangling link", True)
    except Exception as ex:
        check("delete_mod: removes a dangling link", False, repr(ex))
    check("delete_mod: dangled link gone from profile",
          not os.path.lexists(os.path.join(p1, "ghost-1.0.jar")))
    # The store file for it is already gone, so the store must now be clean.
    check("delete_mod: no leftover store file",
          "ghost-1.0.jar" not in store_files(), store_files())

    # The healthy entry survives the whole ordeal untouched.
    check("healthy: good jar still installed after dangle cleanup",
          os.path.isfile(os.path.join(p1, "sodium-0.1.jar")))

    # --- store files survive profile deletes (cross-profile reuse) -----------
    # Install the same jar into a SECOND profile: store copy is shared.
    p2 = os.path.join(PROFILES_DIR, "1.20.1-quilt")
    os.makedirs(p2, exist_ok=True)
    dest_other = os.path.join(p2, "sodium-0.1.jar")
    store.put_file(a1.name, dest_other)
    before = len(store_files())
    mods.delete_mod("1.20.1", "quilt", "sodium-0.1.jar")
    check("delete from one profile keeps store copy (shared)",
          len(store_files()) == before, store_files())

    import threading
    from concurrent.futures import ThreadPoolExecutor
    rendezvous = threading.Barrier(2)
    temporary_paths = []
    dest = os.path.join(p1, "concurrent.jar")
    def fetch(tmp):
        temporary_paths.append(tmp)
        with open(tmp, "wb") as f:
            f.write(b"concurrent complete bytes")
        rendezvous.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(store.get_or_fetch, dest, fetch) for _ in range(2)]
        errors = []
        for job in jobs:
            try:
                job.result(timeout=10)
            except Exception as ex:
                errors.append(str(ex))
    check("same-destination concurrent fetches use unique temporary files", len(set(temporary_paths)) == 2)
    check("same-destination concurrent fetches both complete", not errors, errors)
    check("same-destination final bytes remain complete", os.path.isfile(dest) and open(dest, "rb").read() == b"concurrent complete bytes")
    check("concurrent fetch temporary files cleaned", not any(os.path.lexists(p) for p in temporary_paths))

    from unittest.mock import patch
    before_bytes = open(dest, "rb").read()
    with patch.object(store.os, "symlink", side_effect=OSError("unavailable")), \
            patch.object(store.os, "link", side_effect=OSError("unavailable")), \
            patch.object(store.shutil, "copyfile", side_effect=OSError("interrupted")):
        raised = False
        try:
            store.link_into_place(a2.name, dest)
        except OSError:
            raised = True
    check("failed link copy preserves existing destination", open(dest, "rb").read() == before_bytes)
    check("failed link copy reports the interruption", raised)

    for p in (a1.name, a2.name):
        try:
            os.remove(p)
        except OSError:
            pass

    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
