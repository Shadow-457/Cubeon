"""Pack overrides must not silently replace the player's own shared files (8.8).

`_extract_overrides` sends `config/`, `options.txt`, `servers.dat`, ... into
MINECRAFT_DIR - the folder every instance shares - and used `os.replace`, so
installing a pack replaced the user's keybinds, video settings and server list
for ALL instances, with no copy of what was lost.

Locked-in behaviour:
  * options/servers files that already exist are KEPT (the pack's copy is not
    applied), and the status line says how many;
  * any other existing shared file is copied to
    `<MINECRAFT_DIR>/.cubeon-override-backup/<timestamp>/<rel>` before it is
    replaced;
  * new files are written normally and new content does not create a backup.

Run: python tools/test_modpack_overrides_keep.py
"""
import os
import sys
import tempfile
import zipfile

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import modpacks  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-overrides-")
    game_dir = os.path.join(scratch, "minecraft")
    os.makedirs(os.path.join(game_dir, "config"))
    modpacks.MINECRAFT_DIR = game_dir
    for rel, text in (("options.txt", "USER OPTIONS"),
                      ("servers.dat", "USER SERVERS"),
                      ("config/foo.txt", "USER CONFIG")):
        with open(os.path.join(game_dir, rel), "w", encoding="utf-8") as fh:
            fh.write(text)

    archive = os.path.join(scratch, "overrides.zip")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("overrides/options.txt", "PACK OPTIONS")
        zf.writestr("overrides/servers.dat", "PACK SERVERS")
        zf.writestr("overrides/config/foo.txt", "PACK CONFIG")
        zf.writestr("overrides/config/new.txt", "NEW CONFIG")

    statuses = []
    with zipfile.ZipFile(archive) as zf:
        written = set()
        count = modpacks._extract_overrides(zf, os.path.join(scratch, "profile"),
                                            statuses.append, written=written)

    check("no override mod jars were counted", count == 0, str(count))
    check("the user's options.txt is kept",
          read(os.path.join(game_dir, "options.txt")) == "USER OPTIONS")
    check("the user's servers.dat is kept",
          read(os.path.join(game_dir, "servers.dat")) == "USER SERVERS")
    check("other pack config still applies",
          read(os.path.join(game_dir, "config", "foo.txt")) == "PACK CONFIG")
    check("a brand new file is written",
          read(os.path.join(game_dir, "config", "new.txt")) == "NEW CONFIG")

    backup_root = os.path.join(game_dir, ".cubeon-override-backup")
    backups = []
    for root, _dirs, names in os.walk(backup_root):
        backups.extend(os.path.join(root, name) for name in names)
    check("the replaced file was backed up first",
          len(backups) == 1 and read(backups[0]) == "USER CONFIG",
          str(backups))
    check("the backup keeps the relative path inside a timestamped folder",
          backups and backups[0].endswith(os.path.join("config", "foo.txt"))
          and os.path.basename(os.path.dirname(os.path.dirname(backups[0])))
          != "",
          str(backups))
    check("the status line says what was kept",
          any("Kept 2" in s for s in statuses), str(statuses))
    check("the status line says what was backed up",
          any("backed up 1" in s for s in statuses), str(statuses))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
