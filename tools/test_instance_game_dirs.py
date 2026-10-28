"""Each instance plays in its own game folder (worlds + configs).

The bug this locks down: `launch_game` passed one --gameDir for every install,
so `saves/`, `config/` and `options.txt` were shared - a world created in
1.21.11 was "the" world in 1.8.9, and changing a Sodium setting in one
instance changed it in all of them.

What is pinned here:
  1. every version id gets its own folder under <game>/instances/
  2. the deliberately shared folders (staged mods/packs, CustomSkinLoader,
     screenshots, crash reports) still resolve to the one real location
  3. saves/, config/ and options.txt are NOT shared: writing in one instance
     never shows up in another
  4. the pre-existing shared world/config move into the FIRST instance folder
     (nothing "disappears" on update), and only into the first
  5. a hostile version id cannot escape instances/
  6. two ids that sanitize the same stay apart
  7. launch.py passes that folder as --gameDir, runs the JVM in it, and points
     options.txt / sodium / entityculling at it

Run: python tools/test_instance_game_dirs.py
"""
import ast
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

from cubeon import paths  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


MC = paths.MINECRAFT_DIR
INST = paths.INSTANCES_GAME_DIR
SHARED = paths.SHARED_GAME_LINKS

print("1. an install gets its own game folder")
print(f"  (sandbox: {MC})")
a = paths.game_dir_for("1.21.11")
b = paths.game_dir_for("1.8.9")
check("the folder is under instances/", a.startswith(INST + os.sep), a)
check("two installs get two folders", a != b, f"{a} / {b}")
check("the same install is stable", paths.game_dir_for("1.21.11") == a)

print()
print("2. the shared folders still point at the one real location")
for name in SHARED:
    link = os.path.join(a, name)
    real = os.path.join(MC, name)
    linked = os.path.realpath(link) == os.path.realpath(real)
    check(f"{name}/ resolves to the shared folder", linked,
          f"{os.path.realpath(link)} != {os.path.realpath(real)}")
check("the staged mods folder is the one sync_mods_to_game writes",
      os.path.realpath(os.path.join(a, "mods")) == os.path.realpath(paths.MODS_DIR))

print()
print("3. worlds and configs are per instance")
for name in ("saves", "config"):
    link = os.path.join(a, name)
    check(f"{name}/ is a real folder, not a link",
          os.path.isdir(link) and not os.path.islink(link))
check("options.txt is a real file per instance",
      not os.path.islink(os.path.join(a, "options.txt")))
check("the two instances do not share a saves folder",
      os.path.realpath(os.path.join(a, "saves"))
      != os.path.realpath(os.path.join(b, "saves")))
os.makedirs(os.path.join(a, "config"), exist_ok=True)
with open(os.path.join(a, "config", "sodium-options.json"), "w") as fh:
    fh.write('{"mine": true}')
check("a config written in one instance is not in the other",
      not os.path.exists(os.path.join(b, "config", "sodium-options.json")))

print()
print("4. the player's existing single-folder state is adopted once")
legacy_mc = paths.MINECRAFT_DIR
# Simulate a pre-instance-folder install: shared saves/, config/, options.txt,
# and no instances/ tree at all.
for name in ("saves", "config"):
    import shutil
    shutil.rmtree(os.path.join(INST, "1.21.11"), ignore_errors=True)
    shutil.rmtree(os.path.join(INST, "1.8.9"), ignore_errors=True)
    shutil.rmtree(os.path.join(legacy_mc, name), ignore_errors=True)
    shutil.rmtree(os.path.join(legacy_mc, "instances"), ignore_errors=True)

# paths caches nothing, so a fresh call must build the tree from scratch.
os.makedirs(os.path.join(legacy_mc, "saves", "MyWorld"), exist_ok=True)
with open(os.path.join(legacy_mc, "saves", "MyWorld", "level.dat"), "wb") as fh:
    fh.write(b"level")
os.makedirs(os.path.join(legacy_mc, "config"), exist_ok=True)
with open(os.path.join(legacy_mc, "config", "iris.properties"), "w") as fh:
    fh.write("shaders=on\n")
with open(os.path.join(legacy_mc, "options.txt"), "w") as fh:
    fh.write("maxFps:120\n")

first = paths.game_dir_for("1.21.11")
check("the old world moved into the first instance",
      os.path.isfile(os.path.join(first, "saves", "MyWorld", "level.dat")))
check("... and is gone from the shared root",
      not os.path.exists(os.path.join(legacy_mc, "saves", "MyWorld")))
check("the old options.txt moved too",
      os.path.isfile(os.path.join(first, "options.txt")))
second = paths.game_dir_for("1.8.9")
check("the second instance starts empty",
      not os.path.exists(os.path.join(second, "saves"))
      or not os.listdir(os.path.join(second, "saves")))
check("... and gets no copy of the first instance's options.txt",
      not os.path.exists(os.path.join(second, "options.txt")))

print()
print("5. a hostile install id cannot escape instances/")
weird = paths.game_dir_for("../../etc/evil")
check("no path traversal", os.path.realpath(weird).startswith(
    os.path.realpath(INST) + os.sep), weird)
check("the folder name is sanitized",
      ".." not in os.path.basename(weird) and "/" not in os.path.basename(weird),
      weird)

print()
print("6. ids that sanitize the same stay apart")
one = paths.game_dir_for("1.21 test")
two = paths.game_dir_for("1.21_test")
check("two different ids, two folders", one != two, f"{one} / {two}")
check("both are real folders", os.path.isdir(one) and os.path.isdir(two))

print()
print("7. the active instance pointer")
paths.set_active_game_dir(first)
check("round-trips", paths.active_game_dir() == os.path.realpath(first),
      paths.active_game_dir())
with open(paths.ACTIVE_INSTANCE_PATH, "w") as fh:
    fh.write("{not json")
check("a corrupt pointer falls back to the shared folder",
      paths.active_game_dir() == MC)

print()
print("8. launch.py uses it")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "cubeon", "launch.py"), encoding="utf-8").read()
check("the game dir is resolved per launch", "game_dir_for(version_id)" in SRC)
check("it becomes --gameDir via mll", '"gameDirectory": game_dir' in SRC)
check("the JVM runs inside it", "cwd=game_dir" in SRC)
check("options.txt is the instance's",
      "game_options.options_path(game_dir)" in SRC)
check("sodium's config is the instance's",
      "perf_mods.sodium_config_path(game_dir)" in SRC)
check("entityculling's config is the instance's",
      "perf_mods.entityculling_config_path(game_dir)" in SRC)
check("the active instance is recorded", "set_active_game_dir(game_dir)" in SRC)

TREE = ast.parse(SRC)
for node in ast.walk(TREE):
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "game_dir_for":
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id == "version_id":
                break
        else:
            check("game_dir_for is called with version_id", False, ast.dump(node))
        break

print()
print("9. a read-only lookup creates nothing")
# The import UI asks "is this world already in that instance?" while drawing a
# list. That must never create an instance folder - the first folder created
# adopts the old shared world, so a read would steal it for an instance the
# player never launched.
ghost = paths.game_dir_for("9.9.9-not-launched", create=False)
check("create=False names where a launch WOULD put it",
      os.path.join(INST) in ghost, ghost)
check("... and creates nothing", not os.path.exists(ghost), ghost)
from cubeon import importer  # noqa: E402
check("the import check's saves_dir(create=False) creates nothing",
      not os.path.exists(importer.saves_dir("9.9.9-not-launched", create=False)))
check("... and names the instance's saves/, not the shared root",
      importer.saves_dir("9.9.9-not-launched", create=False).startswith(
          os.path.join(INST, "")),
      importer.saves_dir("9.9.9-not-launched", create=False))
check("and the folder is still absent afterwards",
      not os.path.exists(ghost), ghost)

print()
print("10. backups keep each instance's worlds apart")
from cubeon import backup  # noqa: E402
for base, world in ((first, "WorldOne"), (second, "WorldTwo")):
    w = os.path.join(base, "saves", world)
    os.makedirs(w, exist_ok=True)
    with open(os.path.join(w, "level.dat"), "wb") as fh:
        fh.write(world.encode())
backup_dest = tempfile.mkdtemp(prefix="cubeon-bk-")
result = backup.create_backup(include_saves=True, dest_dir=backup_dest)
check("the backup is written", result.ok, result.message)
names = zipfile.ZipFile(result.path).namelist()
one = f"instances/{os.path.basename(first)}/saves/WorldOne/level.dat"
two = f"instances/{os.path.basename(second)}/saves/WorldTwo/level.dat"
check("both instances' worlds are in it", one in names and two in names, str(names))
os.remove(os.path.join(first, "saves", "WorldOne", "level.dat"))
os.remove(os.path.join(second, "saves", "WorldTwo", "level.dat"))
restored = backup.restore_backup(result.path)
check("restore reports success", restored.ok, restored.message)
check("each world came back to its own instance",
      os.path.isfile(os.path.join(first, "saves", "WorldOne", "level.dat"))
      and os.path.isfile(os.path.join(second, "saves", "WorldTwo", "level.dat")))
check("neither instance got the other's world",
      not os.path.exists(os.path.join(first, "saves", "WorldTwo"))
      and not os.path.exists(os.path.join(second, "saves", "WorldOne")))

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
