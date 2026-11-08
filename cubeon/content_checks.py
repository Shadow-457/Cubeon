"""Local compatibility detection, separate from user-authorized changes."""
import time
import os
import threading

from .mod_dependencies import run_dependency_doctor

_runtime_lock = threading.Lock()
_runtime_cache = {}


def _java_fingerprint(path):
    from .launch import _normalize_java_path
    executable = os.path.realpath(_normalize_java_path(path))
    stat = os.stat(executable)
    home = os.path.dirname(os.path.dirname(executable))
    related = []
    for name in ('release', 'lib/modules', 'lib/server/libjvm.so', 'lib/server/libjvm.dylib', 'bin/server/jvm.dll'):
        try:
            entry = os.stat(os.path.join(home, name))
            related.append((name, entry.st_dev, entry.st_ino, entry.st_mode, entry.st_size, entry.st_mtime_ns))
        except OSError:
            pass
    return executable, stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns, tuple(related)


def remember_runtime(target, java_path, major, configured_java=None):
    try:
        entry = (_java_fingerprint(java_path), java_path, major, configured_java)
    except (OSError, TypeError, ValueError):
        return
    with _runtime_lock:
        _runtime_cache[target[1:]] = entry
        while len(_runtime_cache) > 32:
            _runtime_cache.pop(next(iter(_runtime_cache)))


def cached_runtime(target):
    from .config import launch_java_path
    with _runtime_lock:
        entry = _runtime_cache.get(target[1:])
    if entry is None:
        return {}
    fingerprint, java_path, major, configured = entry
    try:
        if configured == launch_java_path() and fingerprint == _java_fingerprint(java_path):
            return {'java': str(major)} if major is not None else {}
    except (OSError, TypeError, ValueError):
        pass
    with _runtime_lock:
        _runtime_cache.pop(target[1:], None)
    return {}


def check_content(target, *, resolve=False, status_cb=None, runtime_versions=None):
    kind, mc_version, loader, version_id = target
    started = time.monotonic()
    if kind == "mod":
        report = run_dependency_doctor(
            mc_version, loader, version_id=version_id, auto_fix=resolve,
            check_online=resolve, status_cb=status_cb, runtime_versions=runtime_versions if runtime_versions is not None else cached_runtime(target))
    else:
        from .doctor import run_doctor
        report = run_doctor(
            mc_version, loader, version_id=version_id, auto_fix=resolve,
            check_online=False, include=["shaders" if kind == "shader" else "resourcepacks"],
            status_cb=status_cb, approve_cb=(lambda change: True) if resolve else None)
    return dict(report, elapsed=time.monotonic() - started)


def is_missing_dependency(problem):
    from .mods import DOCTOR_RUNTIME_IDS
    return (problem.get("kind") == "required" and problem.get("missing")
            and problem.get("dependency") not in DOCTOR_RUNTIME_IDS)
