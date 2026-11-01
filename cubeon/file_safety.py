"""Filename and directory boundaries for content stores and instance profiles."""
import os
import re
import tempfile
import shutil


def entry_name(name, *, extensions=None):
    if (not isinstance(name, str) or not name or name in ('.', '..')
            or name.startswith('.') or any(c in name for c in '/\\:')
            or any(ord(c) < 32 for c in name) or name.rstrip(' .') != name):
        raise ValueError('Refusing a filename outside the content folder.')
    if extensions and not name.lower().endswith(extensions):
        raise ValueError('This file has an unsupported content extension.')
    return name


def inside(root, path):
    try:
        root, path = os.path.realpath(root), os.path.realpath(path)
        return os.path.commonpath((root, path)) == root and path != root
    except (OSError, ValueError):
        return False


def child_directory(root, *names):
    path = root
    for name in names:
        path = os.path.join(path, entry_name(name))
    if not inside(root, path):
        raise ValueError('This content folder points outside its storage directory.')
    return path


def download_name(name, extensions):
    base = os.path.basename(str(name or '').replace('\\', '/'))
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', base).strip(' .')
    if not base or not base.lower().endswith(extensions):
        raise ValueError('The download has no supported filename.')
    if base.split('.', 1)[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
            *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        base = '_' + base
    return entry_name(base, extensions=extensions)


def replace_directory(staged, destination):
    """Publish a prepared folder, restoring the old entry if placement fails."""
    if not os.path.lexists(destination):
        os.replace(staged, destination)
        return
    fd, backup = tempfile.mkstemp(prefix='.previous-', dir=os.path.dirname(destination))
    os.close(fd)
    os.remove(backup)
    os.replace(destination, backup)
    try:
        os.replace(staged, destination)
    except BaseException:
        os.replace(backup, destination)
        raise
    if os.path.isdir(backup) and not os.path.islink(backup):
        shutil.rmtree(backup)
    else:
        os.remove(backup)
