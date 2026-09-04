"""
Cubeon backup system.

Zips up the Cubeon-managed data a player would actually be upset to lose
(mod profiles, skins/capes, profile picture, server configs, and the
launcher config itself) into a single .zip under CUBEON_HOME/backups.
Vanilla `saves/` lives under MINECRAFT_DIR (shared with other launchers)
and can be huge, so it's included only if the caller opts in.

Design goals:
  - Never block the UI thread - every public entry point here is meant to
    be called from a background thread (main.py / settings UI already
    does this for other long-running work).
  - Never raise past its own boundary. A failed backup should produce a
    BackupResult with ok=False and a message, not a stack trace the UI
    has to catch.
  - Config-driven scheduling: "activated" and "adjusted" from settings,
    persisted like every other setting, and enforced with a plain
    timestamp check rather than a background OS-level cron/task-scheduler
    entry (keeps it portable and dependency-free across Win/macOS/Linux).
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .paths import (
    CUBEON_HOME, CONFIG_PATH, SKINS_DIR, CAPES_DIR, PFP_DIR,
    SERVERS_DIR, PROFILES_DIR, MINECRAFT_DIR,
)

log = logging.getLogger(__name__)

BACKUPS_DIR = os.path.join(CUBEON_HOME, "backups")
BACKUP_META_PATH = os.path.join(BACKUPS_DIR, "backup_settings.json")

# Vanilla world saves - shared with other launchers, can be many GB, so this
# is opt-in only (see BackupSettings.include_saves).
SAVES_DIR = os.path.join(MINECRAFT_DIR, "saves")

# What gets zipped, keyed by a stable id so settings can enable/disable
# individual items later without breaking old saved preferences.
# (label, absolute path, always_included)
_BACKUP_SOURCES = [
    ("config", "Launcher settings", CONFIG_PATH, True),
    ("mod_profiles", "Mod profiles (per version/loader)", PROFILES_DIR, True),
    ("skins", "Skins", SKINS_DIR, True),
    ("capes", "Capes", CAPES_DIR, True),
    ("profile_picture", "Profile picture", PFP_DIR, True),
    ("servers", "Local server configs", SERVERS_DIR, True),
    ("saves", "World saves (can be large)", SAVES_DIR, False),
]

DEFAULT_BACKUP_SETTINGS = {
    "enabled": False,
    # "manual" | "daily" | "weekly"
    "frequency": "manual",
    "include_saves": False,
    "keep_last": 5,          # rotate old auto-backups, 0 = keep all
    "last_backup_ts": None,  # epoch seconds, set after each successful backup
}


@dataclass
class BackupResult:
    ok: bool
    message: str
    path: str | None = None
    size_bytes: int = 0


@dataclass
class BackupInfo:
    path: str
    filename: str
    size_bytes: int
    created_ts: float


def load_backup_settings() -> dict:
    try:
        with open(BACKUP_META_PATH, "r") as f:
            data = json.load(f)
        return {**DEFAULT_BACKUP_SETTINGS, **data}
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return dict(DEFAULT_BACKUP_SETTINGS)


def save_backup_settings(settings: dict) -> None:
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    with open(BACKUP_META_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def _iter_files(root: str):
    """Yield (absolute_path, arcname) for every file under root, or the
    single file itself if root isn't a directory. Silently skips anything
    that vanishes mid-walk (e.g. a mod being deleted concurrently) instead
    of failing the whole backup over one file."""
    if not os.path.exists(root):
        return
    if os.path.isfile(root):
        yield root, os.path.basename(root)
        return
    root_parent = os.path.dirname(root.rstrip(os.sep))
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            try:
                if not os.path.isfile(full):
                    continue
                arc = os.path.relpath(full, root_parent)
                yield full, arc
            except OSError:
                continue


def create_backup(include_saves: bool | None = None, dest_dir: str | None = None,
                   progress_cb=None) -> BackupResult:
    """Creates a timestamped zip of everything in _BACKUP_SOURCES (plus
    saves/ if include_saves is truthy). Returns a BackupResult - never
    raises.

    progress_cb, if given, is called as progress_cb(done_files, total_files)
    periodically so a caller on a background thread can update a UI
    progress bar via its own thread-safe update mechanism.
    """
    settings = load_backup_settings()
    if include_saves is None:
        include_saves = settings.get("include_saves", False)

    dest_dir = dest_dir or BACKUPS_DIR
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as ex:
        return BackupResult(False, f"Couldn't create backup folder: {ex}")

    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    out_path = os.path.join(dest_dir, f"cubeon-backup-{ts}.zip")

    sources = [s for s in _BACKUP_SOURCES if s[3] or (s[0] == "saves" and include_saves)]

    # Pre-scan file list so we can report progress and give an accurate
    # "nothing to back up" message instead of writing an empty zip.
    all_files = []
    for _key, _label, path, _always in sources:
        all_files.extend(_iter_files(path))

    if not all_files:
        return BackupResult(False, "Nothing to back up yet - no config, mods, skins, or servers found.")

    tmp_path = out_path + ".partial"
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, (full, arc) in enumerate(all_files, 1):
                try:
                    zf.write(full, arc)
                except OSError as ex:
                    log.warning("skipping unreadable file during backup: %s (%s)", full, ex)
                if progress_cb and (i % 25 == 0 or i == len(all_files)):
                    try:
                        progress_cb(i, len(all_files))
                    except Exception:
                        pass
        os.replace(tmp_path, out_path)
    except OSError as ex:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return BackupResult(False, f"Backup failed: {ex}")

    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0

    settings["last_backup_ts"] = time.time()
    save_backup_settings(settings)

    _rotate_old_backups(dest_dir, settings.get("keep_last", 5))

    return BackupResult(True, f"Backup saved ({_human_size(size)}).", out_path, size)


def _rotate_old_backups(dest_dir: str, keep_last: int) -> None:
    """Deletes oldest cubeon-backup-*.zip files beyond keep_last. keep_last
    <= 0 means keep everything (no rotation)."""
    if not keep_last or keep_last <= 0:
        return
    try:
        backups = list_backups(dest_dir)
    except OSError:
        return
    if len(backups) <= keep_last:
        return
    # list_backups returns newest-first; drop everything past keep_last
    for old in backups[keep_last:]:
        try:
            os.remove(old.path)
        except OSError as ex:
            log.warning("couldn't rotate out old backup %s (%s)", old.path, ex)


def list_backups(dest_dir: str | None = None) -> list[BackupInfo]:
    """Returns known backups, newest first."""
    dest_dir = dest_dir or BACKUPS_DIR
    if not os.path.isdir(dest_dir):
        return []
    out = []
    for fn in os.listdir(dest_dir):
        if not (fn.startswith("cubeon-backup-") and fn.endswith(".zip")):
            continue
        full = os.path.join(dest_dir, fn)
        try:
            st = os.stat(full)
        except OSError:
            continue
        out.append(BackupInfo(full, fn, st.st_size, st.st_mtime))
    out.sort(key=lambda b: b.created_ts, reverse=True)
    return out


def restore_backup(zip_path: str, progress_cb=None) -> BackupResult:
    """Extracts a backup zip back over CUBEON_HOME / MINECRAFT_DIR. Existing
    files with the same relative path are overwritten; nothing outside the
    original backup's own paths is touched or deleted, so anything created
    since the backup (new mods, new skins) is left alone rather than wiped
    to match the snapshot.
    """
    if not os.path.isfile(zip_path):
        return BackupResult(False, "Backup file not found.")

    # The archive's arcnames were built relative to each source's parent
    # directory (see _iter_files), and every source lives under either
    # CUBEON_HOME or MINECRAFT_DIR - so restoring relative to CUBEON_HOME's
    # parent (i.e. the user's home / the shared root both dirs sit under)
    # would only work if they share a common ancestor. They don't always
    # (e.g. MINECRAFT_DIR can be a completely different drive on Windows).
    # So instead we restore each entry by re-deriving which known root it
    # belongs to, based on its top-level folder name.
    roots_by_top = {
        os.path.basename(CONFIG_PATH): os.path.dirname(CONFIG_PATH),
        os.path.basename(PROFILES_DIR.rstrip(os.sep)): os.path.dirname(PROFILES_DIR.rstrip(os.sep)),
        os.path.basename(SKINS_DIR.rstrip(os.sep)): os.path.dirname(SKINS_DIR.rstrip(os.sep)),
        os.path.basename(CAPES_DIR.rstrip(os.sep)): os.path.dirname(CAPES_DIR.rstrip(os.sep)),
        os.path.basename(PFP_DIR.rstrip(os.sep)): os.path.dirname(PFP_DIR.rstrip(os.sep)),
        os.path.basename(SERVERS_DIR.rstrip(os.sep)): os.path.dirname(SERVERS_DIR.rstrip(os.sep)),
        os.path.basename(SAVES_DIR.rstrip(os.sep)): os.path.dirname(SAVES_DIR.rstrip(os.sep)),
    }

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            total = len(names)
            for i, name in enumerate(names, 1):
                top = name.split("/", 1)[0]
                root = roots_by_top.get(top)
                if root is None:
                    log.warning("skipping unknown entry in backup: %s", name)
                    continue
                dest = os.path.join(root, name)
                # Guard against zip-slip: resolved dest must stay under root.
                if not os.path.abspath(dest).startswith(os.path.abspath(root) + os.sep):
                    log.warning("skipping suspicious backup entry: %s", name)
                    continue
                if name.endswith("/"):
                    os.makedirs(dest, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(name) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                if progress_cb and (i % 25 == 0 or i == total):
                    try:
                        progress_cb(i, total)
                    except Exception:
                        pass
    except (zipfile.BadZipFile, OSError) as ex:
        return BackupResult(False, f"Restore failed: {ex}")

    return BackupResult(True, "Backup restored.")


def is_due(settings: dict | None = None) -> bool:
    """Whether a scheduled backup should run now, based on frequency and
    last_backup_ts. Manual-only or disabled schedules are never due."""
    settings = settings or load_backup_settings()
    if not settings.get("enabled"):
        return False
    freq = settings.get("frequency", "manual")
    if freq == "manual":
        return False
    last = settings.get("last_backup_ts")
    if not last:
        return True
    interval = {"daily": 86400, "weekly": 7 * 86400}.get(freq)
    if interval is None:
        return False
    return (time.time() - last) >= interval


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


_human_size = human_size  # internal alias used within this module
