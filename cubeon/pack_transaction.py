"""Rollback only the files owned/touched by one modpack install.

Profiles contain immutable store links; preserve those links without copying
their targets. Game folders can contain large saves, so capture individual pack
destinations there rather than copying the game folder.
"""
import logging
import os
import shutil
import tempfile

log = logging.getLogger(__name__)


class PackTransaction:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="cubeon-pack-rollback-")
        self.entries = {}

    def capture(self, path, *, created=False):
        path = os.path.abspath(path)
        if path in self.entries or any(
                path.startswith(parent + os.sep) for parent in self.entries):
            return
        backup = None
        if not created and os.path.lexists(path):
            backup = os.path.join(self.root, str(len(self.entries)))
            self._copy(path, backup)
        self.entries[path] = backup

    @staticmethod
    def _copy(source, dest):
        if os.path.islink(source):
            os.symlink(os.readlink(source), dest,
                       target_is_directory=os.path.isdir(source))
        elif os.path.isdir(source):
            shutil.copytree(source, dest, symlinks=True)
        else:
            shutil.copy2(source, dest)

    @staticmethod
    def _remove(path):
        if os.path.islink(path) or not os.path.isdir(path):
            if os.path.lexists(path):
                os.unlink(path)
        else:
            shutil.rmtree(path)

    def rollback(self):
        failures = []
        for path, backup in reversed(list(self.entries.items())):
            try:
                # Prepare the restore next to its destination before removing
                # anything; tempdir may be on a different filesystem.
                if backup is None:
                    self._remove(path)
                    continue
                parent = os.path.dirname(path)
                os.makedirs(parent, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=".pack-restore-", dir=parent) as work:
                    staged = os.path.join(work, "entry")
                    self._copy(backup, staged)
                    if os.path.isdir(path) and not os.path.islink(path):
                        self._remove(path)
                    os.replace(staged, path)
            except OSError:
                failures.append(path)
                log.warning("Could not restore pack file %s", path, exc_info=True)
        if failures:
            raise OSError(f"Could not restore {len(failures)} pack file(s). "
                          f"Recovery copies are kept in {self.root}")

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)
