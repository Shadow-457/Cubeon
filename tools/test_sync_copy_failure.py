"""A failed fallback copy never leaves a truncated jar in the game folder (9.9).

`sync_mods_to_game` links each enabled profile jar into `MINECRAFT_DIR/mods`
and falls back to `shutil.copyfile` when linking is not possible. If that copy
fails (disk full, I/O error) the partial file stayed in `mods/`, the launch
raised a raw OSError, and the game tried to load a corrupt jar.

Locked-in behaviour:
  * the hard-link path is unchanged;
  * a successful copy fallback links/copies the exact bytes and is recorded in
    the sync manifest;
  * a failing copy removes the partial destination, writes no manifest, and
    raises a `RuntimeError` that names the mod and keeps the cause (`__cause__`).

Run: python tools/test_sync_copy_failure.py
"""
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

MC, LOADER = "1.20.1", "fabric"


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def error_of(fn):
    try:
        fn()
    except Exception as ex:
        return ex
    return None


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-sync-copy-")
    game_dir = os.path.join(scratch, "minecraft")
    profiles_dir = os.path.join(scratch, "profiles")
    mods_dir = os.path.join(game_dir, "mods")
    mods.MINECRAFT_DIR = game_dir
    mods.PROFILES_DIR = profiles_dir
    mods.MODS_DIR = mods_dir
    os.makedirs(mods_dir, exist_ok=True)
    profile = mods.get_profile_dir(MC, LOADER)
    with open(os.path.join(profile, "sodium.jar"), "wb") as fh:
        fh.write(b"good-jar-bytes")
    dst = os.path.join(mods_dir, "sodium.jar")
    manifest = os.path.join(mods_dir, ".cubeon-synced.json")

    # --- 1. hard links still work -----------------------------------------
    mods.sync_mods_to_game(MC, LOADER)
    check("a normal sync puts the jar in the game folder", os.path.isfile(dst))
    check("and records it in the manifest", os.path.isfile(manifest),
          manifest)

    # --- 2. the copy fallback still works when linking is unavailable -----
    os.remove(dst)
    os.remove(manifest)
    with patch.object(mods.os, "link", side_effect=OSError("cross-device link")):
        mods.sync_mods_to_game(MC, LOADER)
    with open(dst, "rb") as fh:
        check("the fallback copy has the full contents",
              fh.read() == b"good-jar-bytes")
    check("the copied jar is recorded too", os.path.isfile(manifest))

    # --- 3. a failing copy leaves nothing behind ---------------------------
    os.remove(dst)
    with open(manifest, "rb") as fh:
        before_manifest = fh.read()

    def partial_copy(src, dest):
        with open(dest, "wb") as fh:
            fh.write(b"partial")
        raise OSError(28, "No space left on device")

    ex = None
    with patch.object(mods.os, "link", side_effect=OSError("cross-device link")), \
            patch.object(mods.shutil, "copyfile", partial_copy):
        ex = error_of(lambda: mods.sync_mods_to_game(MC, LOADER))
    check("a failing copy raises a readable RuntimeError",
          isinstance(ex, RuntimeError), repr(ex))
    check("the error names the mod",
          isinstance(ex, RuntimeError) and "sodium.jar" in str(ex), repr(ex))
    check("the error keeps the original cause",
          isinstance(ex, RuntimeError) and isinstance(ex.__cause__, OSError),
          repr(getattr(ex, "__cause__", None)))
    check("the truncated jar was removed", not os.path.exists(dst), dst)
    with open(manifest, "rb") as fh:
        check("the failed sync did not rewrite the manifest",
              fh.read() == before_manifest)

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
