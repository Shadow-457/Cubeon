import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager

import psutil

from .atomicio import write_json
from .paths import CUBEON_HOME

log = logging.getLogger(__name__)

RECORD_PATH = os.path.join(CUBEON_HOME, "running_game.json")
_lock = threading.RLock()
_sessions = None
_processes = {}
_recovery_thread = None


def _process_identity(pid: int) -> dict | None:
    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None
        return {"created": process.create_time(), "boot": psutil.boot_time()}
    except (psutil.Error, ValueError, OSError):
        return None


def _pid_alive(pid: int) -> bool:
    return _process_identity(pid) is not None


def _live(rec: dict) -> bool:
    process = _processes.get(rec.get("session_id"))
    if process is not None:
        try:
            return process.poll() is None
        except Exception:
            return False
    identity = rec.get("identity")
    return bool(identity and identity == _process_identity(rec["pid"]))


@contextmanager
def _write_transaction():
    os.makedirs(os.path.dirname(RECORD_PATH), exist_ok=True)
    with open(RECORD_PATH + ".lock", "a+b") as fh:
        if os.name == "nt":
            import msvcrt
            fh.write(b"\0")
            fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _disk_sessions():
    try:
        with open(RECORD_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        records = data.get("sessions", [data]) if isinstance(data, dict) else []
        return [rec for rec in records if isinstance(rec, dict)
                and type(rec.get("pid")) is int and rec["pid"] > 0
                and isinstance(rec.get("session_id"), str) and rec["session_id"]
                and isinstance(rec.get("identity"), dict)] if isinstance(records, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _proven_dead(rec):
    if rec["session_id"] in _processes:
        return not _live(rec)
    try:
        process = psutil.Process(rec["pid"])
        return (not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
                or {"created": process.create_time(), "boot": psutil.boot_time()} != rec["identity"])
    except psutil.NoSuchProcess:
        return True
    except (psutil.Error, OSError, ValueError):
        return False


def _persist() -> None:
    try:
        with _write_transaction():
            merged = {rec["session_id"]: rec for rec in _disk_sessions()
                      if not _proven_dead(rec)}
            merged.update({rec["session_id"]: rec for rec in _sessions})
            _sessions[:] = sorted(merged.values(), key=lambda rec: rec.get("started", 0))
            if _sessions:
                write_json(RECORD_PATH, {**_sessions[-1], "sessions": _sessions})
            else:
                try:
                    os.unlink(RECORD_PATH)
                except FileNotFoundError:
                    pass
    except Exception:
        log.debug("watchdog record persistence failed", exc_info=True)


def _load() -> None:
    global _sessions
    if _sessions is not None:
        return
    _sessions = []
    try:
        with open(RECORD_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        records = data.get("sessions", [data]) if isinstance(data, dict) else []
        if isinstance(records, list):
            seen = set()
            for rec in records:
                if (isinstance(rec, dict)
                        and type(rec.get("pid")) is int and rec["pid"] > 0
                        and isinstance(rec.get("session_id"), str)
                        and rec["session_id"] and rec["session_id"] not in seen
                        and isinstance(rec.get("identity"), dict)
                        and _live(rec)):
                    _sessions.append(rec)
                    seen.add(rec["session_id"])
        _persist()
    except (OSError, ValueError, TypeError):
        pass
    if _sessions:
        _start_recovery_watch()


def _prune() -> bool:
    before = len(_sessions)
    _sessions[:] = [rec for rec in _sessions if _live(rec)]
    active = {rec["session_id"] for rec in _sessions}
    for session_id in list(_processes):
        if session_id not in active:
            _processes.pop(session_id, None)
    if len(_sessions) != before:
        _persist()
        return True
    return False


def _reconcile_username() -> None:
    try:
        from .friends_service import FriendsService
        FriendsService.reconcile_username_active()
    except Exception:
        log.debug("watchdog username reconciliation failed", exc_info=True)


def _start_recovery_watch() -> None:
    global _recovery_thread
    if _recovery_thread is not None and _recovery_thread.is_alive():
        return

    def watch():
        global _recovery_thread
        while True:
            time.sleep(1.0)
            with _lock:
                changed = _prune()
                done = not _sessions
                if done:
                    _recovery_thread = None
            if changed:
                _reconcile_username()
            if done:
                return

    _recovery_thread = threading.Thread(target=watch, name="cubeon-game-recovery", daemon=True)
    _recovery_thread.start()


def register(pid: int, version_id: str = "", username: str = "", *, process=None,
             session_id: str | None = None) -> str | None:
    try:
        with _lock:
            _load()
            _prune()
            if type(pid) is not int or pid <= 0:
                return None
            session_id = session_id or uuid.uuid4().hex
            rec = {"pid": pid, "version": version_id, "started": time.time(),
                   "session_id": session_id, "identity": _process_identity(pid),
                   "username": _valid_username(username)}
            if process is not None:
                _processes[session_id] = process
            if not _live(rec):
                _processes.pop(session_id, None)
                return None
            _sessions.append(rec)
            _persist()
            return session_id
    except Exception:
        log.debug("watchdog registration failed", exc_info=True)
        return None


def clear(session_id: str | None = None) -> bool:
    with _lock:
        _load()
        if session_id is None:
            return _prune()
        for rec in _sessions:
            if rec["session_id"] == session_id:
                if _live(rec):
                    return False
                _sessions.remove(rec)
                _processes.pop(session_id, None)
                _persist()
                return True
        return False


def stale_session() -> dict | None:
    with _lock:
        _load()
        for rec in reversed(_sessions):
            if _live(rec):
                return dict(rec)
        return None


def _valid_username(value) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_]{3,16}", value) else ""


def effective_username(configured_username) -> str:
    rec = stale_session()
    return _valid_username(rec.get("username") if rec else configured_username)


def terminate(pid: int, session_id: str | None = None) -> bool:
    with _lock:
        _load()
        rec = next((dict(rec) for rec in reversed(_sessions)
                    if rec["pid"] == pid and
                    (session_id is None or rec["session_id"] == session_id)), None)
    if rec is None or not rec.get("identity"):
        return False
    try:
        process = psutil.Process(pid)
        if {"created": process.create_time(), "boot": psutil.boot_time()} != rec["identity"]:
            return False
        process.terminate()
        try:
            process.wait(timeout=2)
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    except psutil.NoSuchProcess:
        pass
    except psutil.Error:
        return False
    if clear(rec["session_id"]):
        _reconcile_username()
    return not _live(rec)
