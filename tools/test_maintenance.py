"""
Offline regression suite for cubeon/maintenance.py - the self-organizing
tidy-up that keeps ~/.cubeon_minecraft from filling with stray asset objects,
superseded store copies and foreign-launcher leftovers.

Runs under a sandboxed HOME (see tools/_sandbox_home.py), so everything is
real files in a tempdir and nothing touches the developer's game dir.

The invariants it pins down:
  - stray `<2-hex>/assets/objects` trees are MERGED into assets/objects/, never
    deleted while they still hold a unique object;
  - a store jar a profile still links to is NEVER pruned, even if it is older;
  - older copies of a name family are pruned down to the newest;
  - temp files (.part/.tmp) go; game content (saves/, mods/) is untouched;
  - foreign leftovers are MOVED to _legacy/, not deleted;
  - a second pass is a no-op (idempotent).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402

_sandbox_home.isolate()

from cubeon import maintenance  # noqa: E402
from cubeon.paths import (  # noqa: E402
    CUBEON_HOME, GLOBAL_MODS_DIR, MINECRAFT_DIR, PROFILES_DIR,
)

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def main():
    # --- stub a launch so every dir exists --------------------------------
    os.makedirs(GLOBAL_MODS_DIR, exist_ok=True)
    os.makedirs(os.path.join(MINECRAFT_DIR, "saves"), exist_ok=True)

    # --- 1. stray asset dir with a UNIQUE object --------------------------
    stray_unique = os.path.join(MINECRAFT_DIR, "ab", "assets", "objects", "ab",
                                "ab" + "0" * 38)
    write(stray_unique, b"UNIQUE-ASSET")
    # a stray dir whose object ALREADY exists in the real store
    real = write(os.path.join(MINECRAFT_DIR, "assets", "objects", "cd", "cd" + "1" * 38), b"REAL")
    stray_dupe = os.path.join(MINECRAFT_DIR, "ef", "assets", "objects", "cd", "cd" + "1" * 38)
    write(stray_dupe, b"REAL")

    # --- 2. store duplicates ---------------------------------------------
    # family A: three unreferenced copies -> only the newest survives
    a_old = write(os.path.join(GLOBAL_MODS_DIR, "cubeon-client-1.0.0+mc1.20-1.21.jar"), b"OLD" * 10)
    a_mid = write(os.path.join(GLOBAL_MODS_DIR, "cubeon-client-1.0.0+mc1.20-1.21.11111111.jar"), b"MID" * 10)
    a_new = write(os.path.join(GLOBAL_MODS_DIR, "cubeon-client-1.0.0+mc1.20-1.21.22222222.jar"), b"NEW" * 10)
    os.utime(a_old, (1000, 1000))
    os.utime(a_mid, (2000, 2000))
    os.utime(a_new, (3000, 3000))
    # family B: two copies, the OLDER one is linked from a profile -> both stay
    b_old = write(os.path.join(GLOBAL_MODS_DIR, "sodium-0.5.jar"), b"S" * 10)
    b_new = write(os.path.join(GLOBAL_MODS_DIR, "sodium-0.5.abc12345.jar"), b"S2" * 10)
    os.utime(b_old, (1000, 1000))
    os.utime(b_new, (3000, 3000))
    prof = os.path.join(PROFILES_DIR, "1.20.1-fabric")
    os.makedirs(prof, exist_ok=True)
    try:
        os.symlink(b_old, os.path.join(prof, "sodium-0.5.jar"))
        linked = True
    except OSError:
        linked = False

    # --- 3. temp files ----------------------------------------------------
    stray_temp = write(os.path.join(GLOBAL_MODS_DIR, ".fetch-9-abc.part.part"), b"")
    home_temp = write(os.path.join(CUBEON_HOME, ".atomic-zzz.tmp"), b"")

    # --- 4. foreign leftovers --------------------------------------------
    write(os.path.join(MINECRAFT_DIR, "TlauncherProfiles.json"), b"{}")
    write(os.path.join(MINECRAFT_DIR, "tlLoader", "Tweaker.log"), b"log")
    write(os.path.join(MINECRAFT_DIR, "TempOptifineStore-1.0.json"), b"{}")

    # --- 5. game content that must survive -------------------------------
    save = write(os.path.join(MINECRAFT_DIR, "saves", "world", "level.dat"), b"WORLD")
    mod = write(os.path.join(MINECRAFT_DIR, "mods", "keepme.jar"), b"MOD")

    # --- dry run changes NOTHING -----------------------------------------
    dry = maintenance.scan()
    check("dry run finds the stray dirs", dry["stray_dirs"] == 2, str(dry))
    check("dry run does not move assets", os.path.isfile(stray_unique))
    check("dry run does not prune", os.path.isfile(a_old))

    # --- apply ------------------------------------------------------------
    rep = maintenance.organize(apply=True)

    check("unique stray object merged into the real store",
          os.path.isfile(os.path.join(MINECRAFT_DIR, "assets", "objects", "ab", "ab" + "0" * 38)))
    check("stray dirs removed once emptied",
          not os.path.exists(os.path.join(MINECRAFT_DIR, "ab"))
          and not os.path.exists(os.path.join(MINECRAFT_DIR, "ef")))
    check("redundant stray object dropped, real one intact",
          os.path.isfile(real) and not os.path.exists(stray_dupe))

    check("only the newest unreferenced copy survives",
          os.path.isfile(a_new) and not os.path.exists(a_old) and not os.path.exists(a_mid))
    check("referenced older copy is NEVER pruned",
          (not linked) or os.path.isfile(b_old))
    check("newest copy always kept", os.path.isfile(b_new))
    check("store duplicate report is non-zero", rep["store_dupes"] >= 2, str(rep))

    check("temp files removed",
          not os.path.exists(stray_temp) and not os.path.exists(home_temp))
    check("foreign leftovers archived",
          os.path.isfile(os.path.join(maintenance.LEGACY_DIR, "TlauncherProfiles.json"))
          and os.path.isfile(os.path.join(maintenance.LEGACY_DIR, "tlLoader", "Tweaker.log"))
          and not os.path.exists(os.path.join(MINECRAFT_DIR, "TlauncherProfiles.json")))

    check("saves untouched", os.path.isfile(save))
    check("mods untouched", os.path.isfile(mod))

    # --- idempotent -------------------------------------------------------
    rep2 = maintenance.organize(apply=True)
    check("second pass is a no-op",
          rep2["stray_dirs"] == 0 and rep2["store_dupes"] == 0
          and rep2["legacy_moved"] == 0 and rep2["temp_files"] == 0, str(rep2))
    check("no foreign entry re-created in the game root",
          not os.path.exists(os.path.join(MINECRAFT_DIR, "TlauncherProfiles.json")))

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
