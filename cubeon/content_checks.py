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


def disable_problem_mod(target, option, *, runtime_versions=None):
    """Disable exactly one reviewed JAR, preserving it and rechecking offline."""
    from . import mods, storage
    from .file_safety import entry_name
    kind, mc_version, loader, version_id = target
    if kind != 'mod':
        raise ValueError('This action is only available for installed mods.')
    if storage.blocked():
        raise ValueError('Finish the storage operation before changing mods.')
    filename = entry_name(option.get('filename'), extensions=('.jar',))
    mods.require_mod_loader(mc_version, loader, 'disable a mod')
    directory = mods.resolve_profile_dir(mc_version, loader, version_id)
    expected = option.get('snapshot')
    if not expected:
        raise ValueError('Check compatibility again before disabling this mod.')
    expected = tuple(tuple(entry) for entry in expected)
    names = [filename, filename + mods.MOD_META_SUFFIX]
    if mods._doctor_profile_snapshot(directory, names) != expected:
        raise ValueError('This mod changed since the check. Check compatibility again.')
    entry = next((item for item in mods.list_mods(mc_version, loader, version_id)
                  if item['filename'] == filename and item.get('enabled')), None)
    if entry is None:
        raise ValueError('This mod is no longer enabled. Check compatibility again.')
    if entry.get('protected') or mods.is_protected_mod(entry, filename):
        raise ValueError('This mod is managed by Cubeon and cannot be disabled here.')
    owner = str(entry.get('mod_id') or '@' + filename).lower()
    if owner != option.get('owner') or mods._doctor_profile_snapshot(directory, names) != expected:
        raise ValueError('This mod changed since the check. Check compatibility again.')
    mods.toggle_mod(mc_version, loader, filename, version_id=version_id)
    try:
        current = check_content(target, runtime_versions=runtime_versions)
    except Exception as error:
        raise RuntimeError(f"{option['name']} was disabled, but the recheck failed: {error}") from error
    fixed = dict(dependency=owner, fix=f"Disabled {option['name']}; JAR kept for re-enabling")
    return dict(current, fixed=[*(current.get('fixed') or []), fixed])
