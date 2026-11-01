"""Opt-in rendering recovery, scoped to an existing instance's mod configs.

This is a compatibility workaround, not attribution of a user's rendering bug.
Only explicit Apply/Restore calls change files; normal launches remain untouched.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

SETTINGS = {
    'entityculling.json': {
        'skipEntityCulling': True,
        'skipBlockEntityCulling': True,
        'blockEntityFrustumCulling': False,
        'tickCulling': False,
    },
    'immediatelyfast.json': {'enhanced_batching': False},
}
BACKUP = 'cubeon-rendering-compat-backup.json'


def _read(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(f'{path.name} must contain an object')
    return value


def _write(path, value):
    fd, name = tempfile.mkstemp(prefix='.cubeon-render-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply(game_dir, *, restore=False):
    """Apply/restore supported keys, preserving other preferences and skin files.

    Missing mod configs are skipped rather than created before a mod seeds them.
    A backup is saved before changes. Restore preserves keys edited since Apply.
    """
    directory = Path(game_dir) / 'config'
    backup_path = directory / BACKUP
    if restore and not backup_path.exists():
        return []
    backup = _read(backup_path) if backup_path.exists() else {}
    targets = {}
    # Validate every existing input before writing any file.
    for filename in SETTINGS:
        path = directory / filename
        if path.exists():
            targets[filename] = _read(path)
    changes = {}
    for filename, data in targets.items():
        saved = backup.get(filename, {})
        if not isinstance(saved, dict):
            raise ValueError('Rendering backup is invalid')
        updated = dict(data)
        for key, value in SETTINGS[filename].items():
            if restore:
                old = saved.get(key)
                if old is None or key not in data or data[key] != value:
                    continue
                if (not isinstance(old, dict) or not isinstance(old.get('present'), bool)
                        or (old['present'] and 'value' not in old)):
                    raise ValueError('Rendering backup is invalid')
                if old['present']:
                    updated[key] = old['value']
                else:
                    updated.pop(key, None)
            else:
                # Only known keys in the existing mod generation are changed.
                if key not in data:
                    continue
                if key not in saved:
                    saved[key] = {'present': True, 'value': data[key]}
                updated[key] = value
        if updated != data:
            changes[filename] = updated
        if not restore and saved:
            backup[filename] = saved
    if not restore and changes:
        _write(backup_path, backup)
    for filename, data in changes.items():
        _write(directory / filename, data)
    if restore:
        backup_path.unlink()
    return list(changes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Apply or restore rendering compatibility after closing Minecraft.')
    parser.add_argument('game_dir', help='The affected instance game folder')
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    changed = apply(args.game_dir, restore=args.restore)
    print(('Restored: ' if args.restore else 'Applied: ') + (', '.join(changed) or 'no changes needed'))
