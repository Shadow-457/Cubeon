"""Two builds of one mod in a profile: the NEWER build must reach the game (9.1).

Report: `sync_mods_to_game` linked the older Sodium/Fabric API/Lithium build
because `_version_key` returned the Minecraft version (the longest dotted run,
e.g. `(1, 20, 1)`) for both files.  The pairs below are the reported ones.

Run: python tools/test_sync_newest_mod.py
"""
import os
import shutil
import sys
import tempfile

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()

from cubeon import mods  # noqa: E402  (after the env isolation)

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def sync_choice(filenames, mtimes=None):
    """Put `filenames` in a fake profile, sync, return what the game gets."""
    root = tempfile.mkdtemp(prefix="cubeon-sync-test-")
    profile = os.path.join(root, "profile")
    game_mods = os.path.join(root, "game-mods")
    os.makedirs(profile)
    os.makedirs(game_mods)
    for name in filenames:
        with open(os.path.join(profile, name), "wb") as fh:
            fh.write(b"jar")
    for name, stamp in (mtimes or {}).items():
        os.utime(os.path.join(profile, name), (stamp, stamp))
    real_dir, real_mods = mods.get_profile_dir, mods.MODS_DIR
    mods.get_profile_dir = lambda *a, **k: profile
    mods.MODS_DIR = game_mods
    try:
        mods.sync_mods_to_game("1.20.1", "fabric")
        return sorted(n for n in os.listdir(game_mods) if n.endswith(".jar"))
    finally:
        mods.get_profile_dir = real_dir
        mods.MODS_DIR = real_mods
        shutil.rmtree(root, ignore_errors=True)


print("reported pairs (Minecraft version used to win the tie)")
pairs = [
    ("sodium-fabric-0.5.3+mc1.20.1.jar",
     "sodium-fabric-0.6.0+mc1.20.1.jar"),
    ("fabric-api-0.140.0+1.20.1.jar",
     "fabric-api-0.155.2+1.20.1.jar"),
    ("lithium-fabric-mc1.20.1-0.11.2.jar",
     "lithium-fabric-mc1.20.1-0.12.0.jar"),
]
for old, new in pairs:
    got = sync_choice([old, new])
    check(f"{new} wins over {old}", got == [new], f"synced={got}")

print("\nreported pairs in the reverse directory order")
for old, new in pairs:
    got = sync_choice([new, old])
    check(f"{new} still wins", got == [new], f"synced={got}")

print("\n0.10.0 is newer than 0.9.0 (numeric, not lexical)")
got = sync_choice(["lithium-fabric-mc1.20.1-0.9.0.jar",
                   "lithium-fabric-mc1.20.1-0.10.0.jar"])
check("0.10.0 wins", got == ["lithium-fabric-mc1.20.1-0.10.0.jar"],
      f"synced={got}")

print("\nequal version keys: the newer FILE (mtime) wins")
a = "sodium-fabric-0.6.0+mc1.20.1.jar"
b = "sodium-fabric-0.6.0+mc1.20.1-backup.jar"
got = sync_choice([a, b], mtimes={a: 1_600_000_000, b: 1_700_000_000})
check("the later-mtime build wins", got == [b], f"synced={got}")
got = sync_choice([a, b], mtimes={a: 1_700_000_000, b: 1_600_000_000})
check("and it flips with the mtimes", got == [a], f"synced={got}")

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
