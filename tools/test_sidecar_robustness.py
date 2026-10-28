"""Corrupt sidecars degrade to "unknown", and sidecar writes are atomic (9.8).

`_read_meta` and `read_instance_meta` caught `(OSError, JSONDecodeError)`, but
invalid UTF-8 raises `UnicodeDecodeError` (a `ValueError`) - so one corrupted
`.cubeon.json`/`_cubeon_instance.json` aborted a Play-tab repaint or a mod
listing. `_read_meta` also returned whatever JSON it parsed, so a list body
made every `.get()` caller raise `AttributeError`.

`write_instance_meta` and `get_profile_dir` wrote through a fixed `.tmp` name
(or not atomically at all), so a crash mid-write could leave a truncated file
or two writers could collide on the same temp.

Locked-in behaviour:
  * both readers catch `(OSError, ValueError)` and return None for a non-dict;
  * `profile_key_for`/`resolve_profile_dir` fall back to the legacy shared key
    instead of raising on a corrupt sidecar;
  * `write_instance_meta`/`get_profile_dir` write atomically through
    `atomicio.write_json` (unique temp + fsync), leaving the old file intact
    and no temp behind when the write fails;
  * `list_profiles` ignores a corrupt `_profile.json` instead of raising.

Run: python tools/test_sidecar_robustness.py
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import mods  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def error_of(fn):
    try:
        return None, fn()
    except Exception as ex:
        return ex, None


def write_bytes(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(body)


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-sidecar-")
    game_dir = os.path.join(scratch, "minecraft")
    profiles_dir = os.path.join(scratch, "profiles")
    mods.MINECRAFT_DIR = game_dir
    mods.PROFILES_DIR = profiles_dir
    versions_dir = os.path.join(game_dir, "versions")
    os.makedirs(versions_dir, exist_ok=True)
    os.makedirs(profiles_dir, exist_ok=True)

    def vdir(vid):
        path = os.path.join(versions_dir, vid)
        os.makedirs(path, exist_ok=True)
        return path

    def sidecar(vid, body):
        path = os.path.join(vdir(vid), mods.INSTANCE_META_FILENAME)
        write_bytes(path, body)
        return path

    # --- 1. read_instance_meta --------------------------------------------
    sidecar("bad-utf8", b'{"mc_version": "\xff\xfe"}')
    ex, value = error_of(lambda: mods.read_instance_meta("bad-utf8"))
    check("invalid UTF-8 does not raise", ex is None, repr(ex))
    check("invalid UTF-8 reads as no sidecar", value is None, repr(value))

    sidecar("a-list", b'["not", "a", "dict"]')
    ex, value = error_of(lambda: mods.read_instance_meta("a-list"))
    check("a list sidecar does not raise", ex is None, repr(ex))
    check("a list sidecar reads as no sidecar", value is None, repr(value))

    write_bytes(os.path.join(vdir("good"), mods.INSTANCE_META_FILENAME),
                b'{"profile": "iso-1", "mc_version": "1.20.1"}')
    check("a real sidecar still reads",
          mods.read_instance_meta("good") == {"profile": "iso-1",
                                              "mc_version": "1.20.1"})

    # resolve_profile_dir is used almost everywhere; a corrupt sidecar must
    # fall back to the legacy key instead of taking the caller down.
    ex, path = error_of(lambda: mods.resolve_profile_dir("1.20.1", "fabric",
                                                         "bad-utf8"))
    check("resolve_profile_dir survives a corrupt sidecar", ex is None, repr(ex))
    check("it falls back to the legacy profile key",
          path == os.path.join(profiles_dir, "1.20.1-fabric"), str(path))

    # --- 2. _read_meta -----------------------------------------------------
    profile = os.path.join(profiles_dir, "1.20.1-fabric")
    os.makedirs(profile, exist_ok=True)
    meta_path = os.path.join(profile, "mod.jar" + mods.MOD_META_SUFFIX)
    write_bytes(meta_path, b'{"slug": "\xff\xfe"}')
    ex, value = error_of(lambda: mods._read_meta(profile, "mod.jar"))
    check("a mod sidecar with invalid UTF-8 does not raise", ex is None, repr(ex))
    check("it reads as no metadata", value is None, repr(value))

    write_bytes(meta_path, b'["slug", "sodium"]')
    ex, value = error_of(lambda: mods._read_meta(profile, "mod.jar"))
    check("a list mod sidecar does not raise", ex is None, repr(ex))
    check("a list mod sidecar reads as no metadata", value is None, repr(value))

    write_bytes(meta_path, b'{"slug": "sodium"}')
    check("a real mod sidecar still reads",
          mods._read_meta(profile, "mod.jar") == {"slug": "sodium"})

    # --- 3. atomic write_instance_meta ------------------------------------
    write_bytes(os.path.join(vdir("atomic"), mods.INSTANCE_META_FILENAME),
                b'{"profile": "old"}')
    ex, ok = error_of(lambda: mods.write_instance_meta(
        "atomic", {"profile": "new", "mc_version": "1.20.1"}))
    check("a normal sidecar write succeeds", ex is None and ok is True, repr(ex))
    with open(os.path.join(vdir("atomic"), mods.INSTANCE_META_FILENAME),
              encoding="utf-8") as fh:
        check("the new sidecar is valid JSON and complete",
              json.load(fh) == {"profile": "new", "mc_version": "1.20.1"})
    leftovers = [n for n in os.listdir(vdir("atomic")) if n.endswith(".tmp")]
    check("no temp file is left behind", not leftovers, str(leftovers))

    # A failure mid-write must leave the previous sidecar byte-intact.
    before = open(os.path.join(vdir("atomic"), mods.INSTANCE_META_FILENAME),
                  "rb").read()
    with patch.object(mods.json, "dump", side_effect=OSError("disk full")):
        ex, ok = error_of(lambda: mods.write_instance_meta(
            "atomic", {"profile": "never-written"}))
    check("a failing write reports failure instead of raising",
          ex is None and ok is False, f"{ex!r} {ok!r}")
    after = open(os.path.join(vdir("atomic"), mods.INSTANCE_META_FILENAME),
                 "rb").read()
    check("a failing write leaves the old sidecar intact", after == before)
    leftovers = [n for n in os.listdir(vdir("atomic")) if n.endswith(".tmp")]
    check("a failing write cleans up its temp file", not leftovers,
          str(leftovers))

    # --- 4. get_profile_dir writes its meta atomically, list_profiles -----
    path = mods.get_profile_dir("1.21.1", "fabric")
    with open(os.path.join(path, mods.PROFILE_META_FILENAME),
              encoding="utf-8") as fh:
        check("a new profile records its version and loader",
              json.load(fh) == {"mc_version": "1.21.1", "loader": "fabric"})
    leftovers = [n for n in os.listdir(path) if n.endswith(".tmp")]
    check("creating a profile leaves no temp file", not leftovers, str(leftovers))

    for label, body in (("invalid UTF-8", b'\xff\xfe'),
                        ("a JSON list", b'["x"]'),
                        ("corrupt JSON", b"{not json")):
        with open(os.path.join(path, "mod.jar"), "wb") as fh:
            fh.write(b"jar")
        write_bytes(os.path.join(path, mods.PROFILE_META_FILENAME), body)
        ex, rows = error_of(mods.list_profiles)
        check(f"list_profiles survives {label} in _profile.json",
              ex is None, repr(ex))
        check(f"the {label} profile is still listed without metadata",
              rows == [{"key": "1.21.1-fabric", "mc_version": None,
                        "loader": None, "mod_count": 1}], str(rows))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
