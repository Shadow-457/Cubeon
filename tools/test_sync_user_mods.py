"""sync_mods_to_game must never wipe jars the user put in mods/ by hand (9.2).

Before this fix it removed EVERY *.jar in the shared MINECRAFT_DIR/mods
folder on every launch. A hand-copied mod vanished, and on Windows a jar held
open by a running session turned the launch into a raw PermissionError.

Locked-in behaviour:
  1. only jars listed in .cubeon-synced.json are deleted
  2. any other jar is MOVED to MINECRAFT_DIR/mods_user_backup (never deleted)
  3. a locked jar raises the clear "close it and try again" RuntimeError
  4. vanilla clears our jars and records that nothing was linked
  5. an unreadable manifest degrades to "nothing is ours" (back up, don't delete)

Run: python tools/test_sync_user_mods.py
"""
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

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


class Sandbox:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="cubeon-sync-user-")
        self.profile = os.path.join(self.root, "profile")
        self.game = os.path.join(self.root, "game")
        self.mods = os.path.join(self.game, "mods")
        self.backup = os.path.join(self.game, "mods_user_backup")
        os.makedirs(self.profile)
        os.makedirs(self.mods)

    def write(self, folder, name, data=b"jar"):
        path = os.path.join(folder, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def manifest(self, files):
        path = os.path.join(self.mods, ".cubeon-synced.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"files": files}, fh)

    def manifest_files(self):
        try:
            with open(os.path.join(self.mods, ".cubeon-synced.json"),
                      encoding="utf-8") as fh:
                return json.load(fh).get("files")
        except (OSError, ValueError):
            return None

    def mod_jars(self):
        return sorted(n for n in os.listdir(self.mods) if n.endswith(".jar"))

    def backups(self):
        try:
            return sorted(os.listdir(self.backup))
        except OSError:
            return []

    def sync(self, loader="fabric"):
        real = (mods.get_profile_dir, mods.MODS_DIR, mods.MINECRAFT_DIR)
        mods.get_profile_dir = lambda *a, **k: self.profile
        mods.MODS_DIR = self.mods
        mods.MINECRAFT_DIR = self.game
        try:
            mods.sync_mods_to_game("1.20.1", loader)
        finally:
            mods.get_profile_dir, mods.MODS_DIR, mods.MINECRAFT_DIR = real

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


print("our stale jar is replaced; a hand-added jar is preserved")
s = Sandbox()
try:
    s.write(s.profile, "sodium.jar")
    s.write(s.mods, "old-synced.jar")
    s.write(s.mods, "my-own-mod.jar")
    s.manifest(["old-synced.jar"])
    s.sync()
    check("the stale linked jar is gone",
          "old-synced.jar" not in s.mod_jars(), f"mods={s.mod_jars()}")
    check("the user's jar is moved to the backup folder",
          s.backups() == ["my-own-mod.jar"], f"backups={s.backups()}")
    check("the user's jar is not in mods/ any more",
          "my-own-mod.jar" not in s.mod_jars(), f"mods={s.mod_jars()}")
    check("this launch's jar is linked",
          "sodium.jar" in s.mod_jars(), f"mods={s.mod_jars()}")
    check("the manifest records only what we linked",
          s.manifest_files() == ["sodium.jar"],
          f"manifest={s.manifest_files()}")
    s.sync()
    check("a second sync does not back the user's jar up twice",
          s.backups() == ["my-own-mod.jar"], f"backups={s.backups()}")
finally:
    s.close()

print("\nvanilla clears our jars but preserves the user's")
s = Sandbox()
try:
    s.write(s.mods, "old-synced.jar")
    s.write(s.mods, "my-own-mod.jar")
    s.manifest(["old-synced.jar"])
    s.sync("vanilla")
    check("no jars are left in mods/", s.mod_jars() == [], f"mods={s.mod_jars()}")
    check("the user's jar survives in the backup",
          s.backups() == ["my-own-mod.jar"], f"backups={s.backups()}")
    check("the manifest is emptied", s.manifest_files() == [],
          f"manifest={s.manifest_files()}")
finally:
    s.close()

print("\na jar held open by another game session fails with a clear message")
s = Sandbox()
try:
    s.write(s.mods, "locked.jar")
    s.manifest(["locked.jar"])
    error = None
    with patch.object(mods.os, "remove", side_effect=PermissionError):
        try:
            s.sync()
        except RuntimeError as ex:
            error = ex
    check("a RuntimeError explains what to do",
          error is not None and "close it and try again" in str(error),
          f"error={error!r}")
    check("the locked jar is left alone",
          s.mod_jars() == ["locked.jar"], f"mods={s.mod_jars()}")
finally:
    s.close()

print("\nan unreadable manifest backs up instead of deleting")
s = Sandbox()
try:
    s.write(s.mods, "unknown.jar")
    with open(os.path.join(s.mods, ".cubeon-synced.json"), "w",
              encoding="utf-8") as fh:
        fh.write("{not json")
    s.sync()
    check("the jar is moved to the backup",
          s.backups() == ["unknown.jar"], f"backups={s.backups()}")
    check("nothing was deleted", s.mod_jars() == [], f"mods={s.mod_jars()}")
finally:
    s.close()

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
