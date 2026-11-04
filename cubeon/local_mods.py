"""Offline, reviewed local JAR imports. Existing builds stay recoverable."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import threading
import zipfile
import zlib

from . import mods, global_mod_cache
from .file_safety import download_name, entry_name

_IMPORT_LOCK = threading.RLock()
MAX_FILES = 100
MAX_JAR_BYTES = 256 * 1024 * 1024


def _digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect(path, mc_version, loader):
    source = Path(path)
    if source.suffix.lower() != '.jar':
        raise ValueError('Choose a mod JAR (.jar), not a ZIP pack or installer.')
    if not source.is_file():
        raise ValueError('This file is missing or cannot be read.')
    if not 0 < source.stat().st_size <= MAX_JAR_BYTES:
        raise ValueError('The mod must be between 1 byte and 256 MB.')
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > 20000 or sum(e.file_size for e in entries) > 1024**3:
                raise ValueError('This archive is too large to validate as a mod.')
            if archive.testzip():
                raise ValueError('The JAR is damaged. Download a fresh copy.')
            names = {e.filename for e in entries}
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError, zlib.error, EOFError) as error:
        raise ValueError('The JAR is damaged or unreadable. Download a fresh copy.') from error
    metadata = mods.read_mod_metadata(str(source), loader)
    if not metadata or not isinstance(metadata.get('id'), str) or not metadata['id']:
        raise ValueError('No readable Fabric, Quilt, Forge or NeoForge mod descriptor was found.')
    reason = mods._doctor_local_incompatibility(metadata, mc_version, loader)
    if reason:
        raise ValueError(reason.replace('This installed build', 'This mod'))
    if metadata.get('environment') == 'server':
        raise ValueError('This is a server-only mod. Choose a client or universal build.')
    # Forge archives can declare several top-level mods; Fabric provides aliases.
    identities = {metadata['id'].lower(), *(metadata.get('provided') or {})}
    return metadata, identities, _digest(source), download_name(source.name, ('.jar',))


def _installed(directory, loader):
    entries = []
    if not os.path.isdir(directory):
        return entries
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(('.jar', '.jar.disabled')):
            continue
        entry_name(name, extensions=('.jar', '.jar.disabled'))
        path = os.path.join(directory, name)
        metadata = mods.read_mod_metadata(path, loader) or {}
        identities = {str(metadata.get('id') or '').lower(), *(metadata.get('provided') or {})} - {''}
        try:
            digest = _digest(path)
        except OSError:
            digest = None
        entries.append({'filename': name, 'sha256': digest, 'ids': identities,
                        'enabled': not name.endswith('.disabled'),
                        'protected': mods.is_protected_mod(mods._read_meta(directory, name), name),
                        'metadata': metadata})
    return entries


def _classify(entry, installed):
    same = next((item for item in installed if item['sha256'] == entry['sha256']), None)
    if same:
        entry.update(status='duplicate', existing_filename=same['filename'], detail=f"Already installed as {same['filename']}" +
                     ('' if same['enabled'] else ' (disabled; enable it in Installed).'))
        return
    collisions = [item for item in installed
                  if item['filename'].removesuffix('.disabled') == entry['filename']
                  or (item['enabled'] and item['ids'] & set(entry['ids']))]
    if (any(item['protected'] for item in collisions) or mods.is_protected_mod(None, entry['filename'])
            or any(mods.is_protected_mod(None, identity + '.jar') for identity in entry['ids'])):
        entry.update(status='blocked', detail='Cubeon manages this mod. Its installed build is protected.')
        return
    entry['replaces'] = [{'filename': item['filename'], 'sha256': item['sha256']} for item in collisions]
    entry['status'] = 'replace' if collisions else 'ready'
    entry['detail'] = ('Replace ' + ', '.join(item['filename'] for item in collisions) +
                       '; keep the old files disabled.' if collisions else 'Ready to import')


def review_files(paths, mc_version, loader, *, version_id=None):
    """Read/hash locally off the UI thread; this preview creates no profile files."""
    mods.require_mod_loader(mc_version, loader, 'import local mods')
    if len(paths) > MAX_FILES:
        raise ValueError('Choose up to 100 mods at a time.')
    directory = mods.resolve_profile_dir(mc_version, loader, version_id)
    installed = _installed(directory, loader)
    entries, selected_hashes, selected_ids = [], set(), set()
    for raw in paths:
        path = str(raw or '')
        entry = {'path': path, 'filename': Path(path).name, 'name': Path(path).name,
                 'status': 'blocked', 'detail': '', 'replaces': [], 'warnings': [], 'profile': directory}
        try:
            metadata, identities, digest, filename = _inspect(path, mc_version, loader)
            entry.update(filename=filename, name=metadata.get('name') or filename,
                         version=metadata.get('version') or '', ids=sorted(identities),
                         sha256=digest, metadata=metadata, size=Path(path).stat().st_size)
            _classify(entry, installed)
            if entry['status'] in ('ready', 'replace'):
                if digest in selected_hashes or selected_ids & identities:
                    entry.update(status='blocked', detail='Another selected file supplies this mod. Import one build at a time.')
                else:
                    selected_hashes.add(digest)
                    selected_ids.update(identities)
        except (ValueError, OSError) as error:
            entry['detail'] = str(error)
        entries.append(entry)
    providers = mods._doctor_runtime_versions(mc_version, loader, version_id)
    for item in installed:
        if item['enabled']:
            for identity in item['ids']:
                providers[identity] = item['metadata'].get('version') or None
    for entry in entries:
        if entry['status'] in ('ready', 'replace'):
            metadata, bundled = mods._doctor_metadata(entry['path'], loader)
            entry['provided'] = bundled
    review = {'mc_version': mc_version, 'loader': loader, 'version_id': version_id,
              'entries': entries, 'providers': providers,
              'installed_ids': {item['filename']: sorted(item['ids']) for item in installed}}
    warnings = selection_warnings(review, [e for e in entries if e['status'] in ('ready', 'replace')])
    for entry in entries:
        entry['warnings'] = warnings.get(entry['path'], [])
    return review


def selection_warnings(review, selected):
    """Pure snapshot calculation; checkbox changes must never scan archives."""
    providers = dict(review['providers'])
    for entry in selected:
        for previous in entry['replaces']:
            for identity in review['installed_ids'].get(previous['filename'], []):
                providers.pop(identity, None)
    for entry in selected:
        providers.update(entry.get('provided', {}))
    warnings = {}
    for entry in selected:
        notes = warnings.setdefault(entry['path'], [])
        for identity, predicate in (entry['metadata'].get('depends') or {}).items():
            if identity not in providers:
                notes.append(f'Missing dependency: {identity} {predicate}')
            elif providers[identity] and not mods.version_satisfies(providers[identity], predicate):
                notes.append(f'Requires {identity} {predicate}; available: {providers[identity]}')
    return warnings


def _disabled_name(directory, filename):
    if not os.path.lexists(os.path.join(directory, filename + '.disabled')):
        return filename + '.disabled'
    stem = filename.removesuffix('.jar')
    index = 2
    while os.path.lexists(os.path.join(directory, f'{stem}.previous-{index}.jar.disabled')):
        index += 1
    return f'{stem}.previous-{index}.jar.disabled'


def import_entry(entry, mc_version, loader, *, version_id=None, replace=False):
    """Revalidate preview bytes/conflicts, stage, then publish with rollback."""
    mods.require_mod_loader(mc_version, loader, 'import a local mod')
    with _IMPORT_LOCK:
        metadata, identities, digest, filename = _inspect(entry['path'], mc_version, loader)
        if digest != entry.get('sha256') or filename != entry.get('filename'):
            raise ValueError('The selected file changed. Choose it again to review the new contents.')
        directory = mods.resolve_profile_dir(mc_version, loader, version_id)
        if directory != entry.get('profile'):
            raise ValueError('The instance profile changed since this review. Choose the files again.')
        directory = mods.get_profile_dir(mc_version, loader, version_id)
        fresh = dict(entry, replaces=[])
        _classify(fresh, _installed(directory, loader))
        if fresh['status'] == 'duplicate':
            return {'status': 'duplicate', 'filename': fresh['existing_filename'], 'detail': fresh['detail']}
        if fresh['status'] == 'blocked':
            raise ValueError(fresh['detail'])
        if fresh['replaces'] != entry.get('replaces', []):
            raise ValueError('Installed mods changed since this review. Choose the files again.')
        if fresh['replaces'] and not replace:
            raise ValueError('Another build is installed. Review and select Replace before importing.')
        moved = []
        published = False
        destination = os.path.join(directory, filename)
        with tempfile.TemporaryDirectory(prefix='.local-import-', dir=directory) as stage:
            staged = os.path.join(stage, filename)
            global_mod_cache.put_file(entry['path'], staged, hashes={'sha256': digest})
            final = dict(entry, replaces=[])
            _classify(final, _installed(directory, loader))
            if final['status'] not in ('ready', 'replace') or final['replaces'] != fresh['replaces']:
                raise ValueError('Installed mods changed while staging. Review the files again.')
            try:
                for previous in fresh['replaces']:
                    old = previous['filename']
                    backup = _disabled_name(directory, old.removesuffix('.disabled'))
                    src, dst = os.path.join(directory, old), os.path.join(directory, backup)
                    os.rename(src, dst)
                    moved.append((src, dst))
                    old_meta, new_meta = mods._meta_path(directory, old), mods._meta_path(directory, backup)
                    if os.path.isfile(old_meta):
                        os.rename(old_meta, new_meta)
                        moved.append((old_meta, new_meta))
                # Exclusive creation never overwrites a file appearing mid-import.
                try:
                    os.link(staged, destination)
                except OSError:
                    with open(staged, 'rb') as source, open(destination, 'xb') as output:
                        published = True
                        import shutil
                        shutil.copyfileobj(source, output)
                published = True
            except BaseException:
                if published:
                    os.unlink(destination)
                for src, dst in reversed(moved):
                    os.rename(dst, src)
                raise
        return {'status': 'imported', 'filename': filename,
                'replaced': [item['filename'] for item in fresh['replaces']]}


def import_review(review, selected, *, replace=False, progress=None):
    results = []
    claimed_ids = set()
    for index, entry in enumerate(selected):
        if progress:
            progress(index, len(selected), entry['name'])
        try:
            if claimed_ids & set(entry.get('ids', [])):
                raise ValueError('Two selected files supply the same mod. Select one build.')
            result = import_entry(entry, review['mc_version'], review['loader'],
                                  version_id=review['version_id'], replace=replace)
            if result['status'] == 'imported':
                claimed_ids.update(entry.get('ids', []))
        except (ValueError, OSError) as error:
            result = {'status': 'failed', 'filename': entry['filename'], 'detail': str(error)}
        results.append(result)
    return results
