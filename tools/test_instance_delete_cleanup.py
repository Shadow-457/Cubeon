"""Deleting an instance forgets its play entry and can remove its own profile (11.5).

`versions.delete_version` only removes `versions/<id>`: an isolated instance's
private mod profile (often GBs) stayed on disk forever, and its `last played`
entry survived so a reinstall showed the old date. And deleting a base version
that another installed instance `inheritsFrom` left that instance broken with
no warning.

Locked-in behaviour:
  * `versions.dependents_of(vid)` lists installed ids that inherit from it;
  * `mods.private_profile_for_deletion(vid)` offers a profile only when it is
    truly private (never the legacy shared key, never one another instance
    still references) and reports its size;
  * `mods.delete_instance_profile(key)` refuses anything outside the profiles
    folder;
  * `instances.forget_played(vid)` removes only that id.

Run: python tools/test_instance_delete_cleanup.py
"""
import json
import os
import sys
import tempfile

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import instances, mods, versions  # noqa: E402

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
    scratch = tempfile.mkdtemp(prefix="cubeon-inst-delete-")
    game_dir = os.path.join(scratch, "minecraft")
    profiles_dir = os.path.join(scratch, "profiles")
    os.makedirs(profiles_dir)
    versions.MINECRAFT_DIR = game_dir
    mods.MINECRAFT_DIR = game_dir
    mods.PROFILES_DIR = profiles_dir
    play_store = os.path.join(scratch, "instance_play.json")
    instances._PLAY_STORE = play_store

    vdir = os.path.join(game_dir, "versions")

    # --- 1. dependents ------------------------------------------------
    write(os.path.join(vdir, "1.20.1", "1.20.1.json"),
          json.dumps({"id": "1.20.1"}))
    write(os.path.join(vdir, "fabric-loader-0.15.7-1.20.1",
                       "fabric-loader-0.15.7-1.20.1.json"),
          json.dumps({"id": "fabric-loader-0.15.7-1.20.1",
                      "inheritsFrom": "1.20.1"}))
    write(os.path.join(vdir, "1.21", "1.21.json"),
          json.dumps({"id": "1.21"}))
    write(os.path.join(vdir, "broken", "broken.json"), "{not json")
    check("dependents_of finds an inheriting instance",
          versions.dependents_of("1.20.1")
          == ["fabric-loader-0.15.7-1.20.1"],
          str(versions.dependents_of("1.20.1")))
    check("dependents_of is empty for a leaf version",
          versions.dependents_of("1.21") == [])
    check("dependents_of survives corrupt JSON",
          versions.dependents_of("broken") == [])

    # --- 2. private profile detection ---------------------------------
    ls_key = mods.profile_key("1.20.1", "fabric")
    mods.write_instance_meta("legacy", {"mc_version": "1.20.1",
                                        "loader": "fabric",
                                        "profile": ls_key})
    check("a legacy shared profile is never offered",
          mods.private_profile_for_deletion("legacy") is None)

    iso_dir = os.path.join(profiles_dir, "iso-profile")
    os.makedirs(iso_dir)
    write(os.path.join(iso_dir, "sodium.jar"), "x" * 1000)
    write(os.path.join(iso_dir, "config", "a.txt"), "x" * 24)
    mods.write_instance_meta("iso", {"mc_version": "1.20.1",
                                     "loader": "fabric",
                                     "profile": "iso-profile"})
    found = mods.private_profile_for_deletion("iso")
    check("an isolated instance's own profile is offered",
          found is not None and found[0] == "iso-profile", str(found))
    check("its size is reported", found is not None and found[1] == 1024,
          str(found))

    os.makedirs(os.path.join(profiles_dir, "shared-prof"))
    for vid in ("shared-a", "shared-b"):
        mods.write_instance_meta(vid, {"mc_version": "1.20.1",
                                       "loader": "fabric",
                                       "profile": "shared-prof"})
    check("a profile used by another instance is not offered",
          mods.private_profile_for_deletion("shared-a") is None)
    check("an unsafe id is refused",
          mods.private_profile_for_deletion("../evil") is None)

    # --- 3. deleting the profile --------------------------------------
    mods.delete_instance_profile("iso-profile")
    check("the confirmed private profile is gone",
          not os.path.exists(iso_dir))
    raised = None
    try:
        mods.delete_instance_profile("../escape")
    except ValueError as ex:
        raised = ex
    check("deleting outside the profiles folder is refused",
          isinstance(raised, ValueError), repr(raised))
    mods.delete_instance_profile("does-not-exist")  # must not raise
    check("a missing profile is a no-op", True)

    # --- 4. forgetting the play entry ---------------------------------
    write(play_store, json.dumps({"iso": 100.0, "keep": 200.0}))
    instances.forget_played("iso")
    store = instances.play_store()
    check("the deleted instance's play date is forgotten",
          "iso" not in store and store.get("keep") == 200.0, str(store))
    instances.forget_played("never-played")
    check("forgetting an absent id is a no-op",
          instances.play_store() == {"keep": 200.0})

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
