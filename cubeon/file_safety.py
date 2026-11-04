"""Filename and directory boundaries for content stores and instance profiles."""
import os
import re
import tempfile
import shutil
import stat


def copy_source_stamp(path):
    """Metadata for a copied file/tree, including replacements and nested edits.

    This reads no payload bytes. Symlinked directory trees use normal staging;
    they cannot be safely represented by a walk that doesn't follow links.
    """
    try:
        def stamp(target):
            info = os.stat(target)
            return [info.st_dev, info.st_ino, info.st_size,
                    info.st_mtime_ns, info.st_ctime_ns, info.st_mode]

        result = [os.path.normcase(os.path.realpath(path)), stamp(path)]
        if stat.S_ISDIR(result[1][-1]):
            entries = []
            def fail(error):
                raise error
            for directory, folders, files in os.walk(path, onerror=fail):
                for name in sorted(folders + files):
                    child = os.path.join(directory, name)
                    if os.path.islink(child):
                        return None
                    entries.append([os.path.relpath(child, path), stamp(child)])
                folders.sort()
            result.append(entries)
        elif not stat.S_ISREG(result[1][-1]):
            return None
        return result
    except OSError:
        return None


def copied_entry_matches(source, destination, receipt):
    """Reuse only an unchanged source and its successfully published copy."""
    if not isinstance(receipt, list) or len(receipt) != 2:
        return False
    src = copy_source_stamp(source)
    return src is not None and src == receipt[0] and copy_source_stamp(destination) == receipt[1]


def copied_entry_receipt(source, destination, before):
    """Record a copy only if its source stayed unchanged during publication."""
    after = copy_source_stamp(source)
    dest = copy_source_stamp(destination)
    return [after, dest] if before is not None and before == after and dest is not None else None


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
