"""Launch disk work with link support unavailable: reuse copies without stale bytes."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import content, global_mod_cache as cache, mods


class CopyStaging(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.profile = self.root / 'profile'
        self.game = self.root / 'game'
        self.profile.mkdir(); self.game.mkdir()
        self.patches = [patch.object(mods, 'MODS_DIR', str(self.game)),
                        patch.object(mods, 'MINECRAFT_DIR', str(self.root)),
                        patch.object(mods, 'get_profile_dir', return_value=str(self.profile)),
                        patch.object(mods, 'mod_identity', side_effect=lambda d, n: ('', '', n)),
                        patch.object(mods.os, 'link', side_effect=OSError('link unavailable'))]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def sync(self):
        mods.sync_mods_to_game('26.3', 'fabric')

    def test_unchanged_copies_do_not_read_or_write_payloads_or_manifests(self):
        (self.profile / 'mod.jar').write_bytes(b'original')
        self.sync()
        stamps = {p.name: p.stat().st_mtime_ns for p in self.game.iterdir()}
        with patch.object(mods.shutil, 'copyfile', side_effect=AssertionError('recopied mod')):
            self.sync()
        self.assertEqual(stamps, {p.name: p.stat().st_mtime_ns for p in self.game.iterdir()})

    def test_same_size_source_replacement_and_destination_edits_restage(self):
        source = self.profile / 'mod.jar'; source.write_bytes(b'original')
        self.sync()
        before = source.stat()
        replacement = self.profile / 'new'; replacement.write_bytes(b'replaced')
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(replacement, source)
        self.sync()
        dest = self.game / 'mod.jar'
        self.assertEqual(dest.read_bytes(), b'replaced')
        before = dest.stat(); dest.write_bytes(b'tampered')
        os.utime(dest, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.sync()
        self.assertEqual(dest.read_bytes(), b'replaced')

    def test_profile_switch_and_disable_preserve_ownership(self):
        source = self.profile / 'mod.jar'; source.write_bytes(b'profileA')
        self.sync()
        other = self.root / 'other'; other.mkdir()
        (other / 'mod.jar').write_bytes(b'profileB')
        with patch.object(mods, 'get_profile_dir', return_value=str(other)):
            self.sync()
        self.assertEqual((self.game / 'mod.jar').read_bytes(), b'profileB')
        self.sync()
        self.assertEqual((self.game / 'mod.jar').read_bytes(), b'profileA')
        source.rename(self.profile / 'mod.jar.disabled')
        self.sync()
        self.assertFalse((self.game / 'mod.jar').exists())
        self.assertEqual(mods._read_copy_receipts(str(self.game), mods._SYNC_MANIFEST), {})

    def test_quilt_warning_packs_are_backed_up_without_adopting_them_into_selected_profile(self):
        originals = {}
        for count in range(18):
            path = self.game / f'pack-{count}.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('pack.mcmeta' if count < 15 else 'shaders/program.fsh', '{}')
            originals[path.name] = path.read_bytes()
        (self.profile / 'selected.jar').write_bytes(b'current instance')
        self.sync()
        backup = self.root / 'mods_user_backup'
        self.assertEqual(originals, {p.name: p.read_bytes() for p in backup.iterdir()})
        self.assertEqual(list(self.game.glob('*.zip')), [])
        self.assertEqual([p.name for p in self.profile.iterdir()], ['selected.jar'])
        self.sync()
        self.assertEqual(originals, {p.name: p.read_bytes() for p in backup.iterdir()})

    def test_unknown_or_real_mod_archives_are_preserved(self):
        unknown = self.game / 'unknown.zip'; unknown.write_bytes(b'unreadable')
        for name, entries in [('mod.zip', ['fabric.mod.json', 'pack.mcmeta']),
                              ('coremod.zip', ['example/Core.class', 'pack.mcmeta']),
                              ('other.zip', ['readme.txt'])]:
            with zipfile.ZipFile(self.game / name, 'w') as archive:
                for entry in entries:
                    archive.writestr(entry, '{}')
        self.sync()
        self.assertEqual(len(list(self.game.glob('*.zip'))), 4)
        self.assertFalse((self.root / 'mods_user_backup').exists())

    def test_backup_collision_and_store_link_preserve_originals(self):
        backup = self.root / 'mods_user_backup'; backup.mkdir()
        (backup / 'pack.zip').symlink_to('missing-target')
        source = self.profile / 'pack.zip'
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('shaders/program.fsh', 'keep')
        staged = self.game / 'pack.zip'; staged.symlink_to(source)
        original = source.read_bytes()
        self.sync()
        self.assertTrue((backup / 'pack.zip').is_symlink())
        self.assertEqual((backup / 'pack.1.zip').read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(staged.exists())

    def test_failed_pack_backup_preserves_source_and_stops_staging(self):
        source = self.game / 'pack.zip'
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('pack.mcmeta', '{}')
        original = source.read_bytes()
        with patch.object(mods.os, 'replace', side_effect=PermissionError('file locked')):
            with self.assertRaises(PermissionError):
                self.sync()
        self.assertEqual(source.read_bytes(), original)

    def test_optional_copy_cache_failure_keeps_successfully_staged_mods(self):
        source = self.profile / 'mod.jar'; source.write_bytes(b'original')
        self.sync()
        source.write_bytes(b'replaced')
        with patch.object(mods, 'write_json', side_effect=OSError('cache read-only')):
            self.sync()
        self.assertEqual((self.game / 'mod.jar').read_bytes(), b'replaced')

    def test_pack_archives_and_folder_copies_reuse_and_detect_nested_edits(self):
        replacements = {'resourcepack': dict(content.CONTENT_TYPES['resourcepack'], dir=str(self.game))}
        (self.profile / 'pack.zip').write_bytes(b'pack-one')
        folder = self.profile / 'folder-pack'; folder.mkdir()
        (folder / 'nested').mkdir(); (folder / 'nested/texture.png').write_bytes(b'texture1')
        with patch.dict(content.CONTENT_TYPES, replacements), \
                patch.object(content, 'profile_dir', return_value=str(self.profile)), \
                patch.object(content, '_adopt_foreign_entries'), \
                patch.object(content.os, 'symlink', side_effect=OSError('symlink unavailable')):
            def sync(): content._sync_content_type('resourcepack', '26.3', 'fabric')
            sync()
            marker = self.game / content._STAGED_MARKER
            stamp = marker.stat().st_mtime_ns
            with patch.object(content.shutil, 'copyfile', side_effect=AssertionError('recopied pack')), \
                    patch.object(content.shutil, 'copytree', side_effect=AssertionError('recopied folder')):
                sync()
            self.assertEqual(marker.stat().st_mtime_ns, stamp)
            (folder / 'nested/texture.png').write_bytes(b'texture2')
            sync()
            self.assertEqual((self.game / 'folder-pack/nested/texture.png').read_bytes(), b'texture2')
            (self.game / 'pack.zip').write_bytes(b'pack-bad')
            sync()
            self.assertEqual((self.game / 'pack.zip').read_bytes(), b'pack-one')

    def test_local_store_hashes_unchanged_source_once_and_invalidates_replacements(self):
        source = self.profile / 'mod.jar'; source.write_bytes(b'original')
        store = self.root / 'store'; store.mkdir()
        with patch.object(cache, 'GLOBAL_MODS_DIR', str(store)), \
                patch.object(cache, '_HASH_INDEX_PATH', str(store / 'index.json')), \
                patch.object(cache, '_hash_file', wraps=cache._hash_file) as hashes:
            cache._verified_hash.cache_clear()
            dest = str(self.game / 'mod.jar')
            cache.put_file(str(source), dest)
            hashes.reset_mock()
            cache.put_file(str(source), dest)
            self.assertFalse(any(call.args[0] == str(source) for call in hashes.call_args_list))
            hashes.reset_mock()
            cache.put_file(str(source), dest)
            self.assertEqual(hashes.call_count, 0)
            source.write_bytes(b'replaced')
            cache.put_file(str(source), dest)
            self.assertEqual(Path(dest).read_bytes(), b'replaced')


if __name__ == '__main__':
    unittest.main()
