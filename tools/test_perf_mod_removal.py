"""Exercise performance-mod removal across repeated Play preparation and sync."""
import json
import ast
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import mods, perf_mods


class PerformanceRemovalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.lookups = []
        for module, name, value in (
                (mods, 'PROFILES_DIR', str(self.root / 'profiles')),
                (mods, 'MODS_DIR', str(self.root / 'game-mods')),
                (mods, 'MINECRAFT_DIR', str(self.root)),
                (mods, 'read_instance_meta', lambda vid: {'profile': vid} if vid else None),
                (perf_mods, 'get_mod_download', self.lookup),
                (perf_mods, 'download_mod', self.download)):
            context = patch.object(module, name, value)
            context.start()
            self.addCleanup(context.stop)
        self.profile = Path(mods.get_profile_dir('1.21.11', 'fabric', 'selected'))
        for slug in perf_mods.PERF_MOD_SLUGS:
            self.write_jar(self.profile / (slug + '.jar'), slug)
        if not (self.profile / 'moreculling.jar').exists():
            self.write_jar(self.profile / 'moreculling.jar', 'moreculling')

    def write_jar(self, path, identity):
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('fabric.mod.json', json.dumps({
                'schemaVersion': 1, 'id': identity, 'name': identity,
                'version': '1.0', 'environment': 'client', 'depends': {}}))

    def lookup(self, slug, **kwargs):
        self.lookups.append(slug)
        return {'filename': slug + '.jar', 'url': 'https://cdn.modrinth.com/test.jar'}

    def download(self, url, filename, **kwargs):
        profile = Path(mods.get_profile_dir(kwargs['mc_version'], kwargs['loader'],
                                            kwargs.get('version_id')))
        self.write_jar(profile / filename, kwargs['slug'])

    def play(self, instance='selected'):
        return perf_mods.ensure_installed('1.21.11', 'fabric', version_id=instance)

    def test_removed_more_culling_stays_removed_after_repeated_play_and_sync(self):
        mods.sync_mods_to_game('1.21.11', 'fabric', version_id='selected')
        mods.delete_mod('1.21.11', 'fabric', 'moreculling.jar', version_id='selected')
        for _ in range(3):
            report = self.play()
            mods.sync_mods_to_game('1.21.11', 'fabric', version_id='selected')
            self.assertFalse((self.profile / 'moreculling.jar').exists())
            self.assertFalse((self.root / 'game-mods' / 'moreculling.jar').exists())
            self.assertIn('moreculling', report['skipped'])
        self.assertEqual(self.lookups, [])
        self.assertEqual(len(list(self.profile.glob('*.jar'))), len(perf_mods.PERF_MODS))

    def test_disabled_then_removed_mod_and_manual_renamed_mod_are_remembered(self):
        mods.toggle_mod('1.21.11', 'fabric', 'moreculling.jar', version_id='selected')
        self.play()
        self.assertEqual(self.lookups, [])
        mods.delete_mod('1.21.11', 'fabric', 'moreculling.jar.disabled', version_id='selected')
        (self.profile / 'entityculling.jar').rename(self.profile / 'my-render-mod.jar')
        mods.delete_mod('1.21.11', 'fabric', 'my-render-mod.jar', version_id='selected')
        report = self.play()
        self.assertEqual(set(report['skipped']), {'moreculling', 'entityculling'})
        self.assertEqual(self.lookups, [])

    def test_removal_does_not_change_another_instance_and_explicit_reinstall_works(self):
        mods.delete_mod('1.21.11', 'fabric', 'moreculling.jar', version_id='selected')
        self.play('sibling')
        self.assertEqual(self.lookups, list(perf_mods.PERF_MOD_SLUGS))
        self.lookups.clear()
        # The explicit Mods-tab installation path may install it again.
        with patch.object(mods.global_mod_cache, 'get_or_fetch',
                          side_effect=lambda dest, *_: self.write_jar(dest, 'moreculling')):
            mods.download_mod('https://cdn.modrinth.com/test.jar', 'moreculling-new.jar',
                              slug='moreculling', project_id='51shyZVL',
                              mc_version='1.21.11', loader='fabric', version_id='selected')
        report = self.play()
        self.assertIn('moreculling', report['kept'])
        self.assertEqual(self.lookups, [])
        mods.sync_mods_to_game('1.21.11', 'fabric', version_id='selected')
        self.assertTrue((self.root / 'game-mods' / 'moreculling-new.jar').exists())

    def test_failed_preference_write_preserves_the_mod_and_shared_store(self):
        shared = self.root / 'stored-moreculling.jar'
        (self.profile / 'moreculling.jar').replace(shared)
        (self.profile / 'moreculling.jar').symlink_to(shared)
        with patch.object(perf_mods, 'write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                mods.delete_mod('1.21.11', 'fabric', 'moreculling.jar', version_id='selected')
        self.assertTrue((self.profile / 'moreculling.jar').exists())
        original = shared.read_bytes()
        mods.delete_mod('1.21.11', 'fabric', 'moreculling.jar', version_id='selected')
        self.play()
        self.assertEqual(shared.read_bytes(), original)
        self.assertEqual(self.lookups, [])

    def test_sidecar_identity_survives_a_dangling_store_link(self):
        jar = self.profile / 'moreculling.jar'
        jar.unlink()
        jar.symlink_to(self.root / 'missing-store.jar')
        mods._write_meta(str(self.profile), jar.name, None, project_id='51shyZVL')
        mods.delete_mod('1.21.11', 'fabric', jar.name, version_id='selected')
        self.assertFalse(jar.is_symlink())
        self.assertFalse(Path(mods._meta_path(str(self.profile), jar.name)).exists())
        self.assertIn('moreculling', self.play()['skipped'])
        self.assertEqual(self.lookups, [])

    def test_unreadable_preferences_do_not_restore_removed_mods(self):
        mods.delete_mod('1.21.11', 'fabric', 'moreculling.jar', version_id='selected')
        preference = self.profile / perf_mods.REMOVED_MODS_FILE
        for data in (b'broken', b'\xff', b'[]', b'{"removed":"moreculling"}'):
            preference.write_bytes(data)
            report = self.play()
            self.assertIn('removal preferences', report['detail'])
            self.assertEqual(self.lookups, [])
            self.assertFalse((self.profile / 'moreculling.jar').exists())

    def test_clean_profile_does_not_download_more_culling(self):
        self.play('clean')
        self.assertNotIn('moreculling', self.lookups)
        self.assertEqual(set(self.lookups), set(perf_mods.PERF_MOD_SLUGS))

    def test_legacy_managed_more_culling_is_disabled_once_and_not_synced(self):
        mods._write_meta(str(self.profile), 'moreculling.jar', 'moreculling',
                         project_id='51shyZVL')
        original = (self.profile / 'moreculling.jar').read_bytes()
        report = self.play()
        self.assertIn('disabled legacy More Culling', report['detail'])
        disabled = self.profile / 'moreculling.jar.disabled'
        self.assertEqual(disabled.read_bytes(), original)
        self.assertEqual(self.lookups, [])
        mods.sync_mods_to_game('1.21.11', 'fabric', version_id='selected')
        self.assertFalse((self.root / 'game-mods' / 'moreculling.jar').exists())
        self.play()
        # Deliberately re-enabling is respected on subsequent launches.
        mods.toggle_mod('1.21.11', 'fabric', disabled.name, version_id='selected')
        self.play()
        self.assertEqual((self.profile / 'moreculling.jar').read_bytes(), original)
        self.assertFalse(disabled.exists())

    def test_manual_pack_and_required_more_culling_are_preserved(self):
        for kind in ('manual', 'pack', 'required'):
            with self.subTest(kind=kind):
                profile = Path(mods.get_profile_dir('1.21.11', 'fabric', kind))
                for slug in (*perf_mods.PERF_MOD_SLUGS, 'moreculling'):
                    self.write_jar(profile / (slug + '.jar'), slug)
                if kind != 'manual':
                    mods._write_meta(str(profile), 'moreculling.jar', 'moreculling')
                if kind == 'pack':
                    (profile / '_modpack.json').write_text('{"jars":["moreculling.jar"]}')
                if kind == 'required':
                    with zipfile.ZipFile(profile / 'needs-culling.jar', 'w') as archive:
                        archive.writestr('fabric.mod.json', json.dumps({
                            'schemaVersion': 1, 'id': 'needs-culling', 'version': '1.0',
                            'depends': {'moreculling': '*'}}))
                self.play(kind)
                self.assertTrue((profile / 'moreculling.jar').exists())
                self.assertFalse((profile / 'moreculling.jar.disabled').exists())
        self.assertEqual(self.lookups, [])

    def test_retirement_failure_preserves_files_and_pending_operation_can_resume(self):
        mods._write_meta(str(self.profile), 'moreculling.jar', 'moreculling')
        with patch.object(perf_mods, 'write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                perf_mods.retire_legacy_more_culling('1.21.11', 'fabric', 'selected')
        self.assertTrue((self.profile / 'moreculling.jar').exists())
        with patch.object(perf_mods, 'toggle_mod', side_effect=OSError('file locked')):
            with self.assertRaises(OSError):
                perf_mods.retire_legacy_more_culling('1.21.11', 'fabric', 'selected')
        self.assertTrue((self.profile / 'moreculling.jar').exists())
        result = perf_mods.retire_legacy_more_culling('1.21.11', 'fabric', 'selected')
        self.assertEqual(result, ['moreculling.jar'])
        self.assertTrue((self.profile / 'moreculling.jar.disabled').exists())

    def test_retirement_cannot_overwrite_an_existing_disabled_copy(self):
        mods._write_meta(str(self.profile), 'moreculling.jar', 'moreculling')
        saved = self.profile / 'moreculling.jar.disabled'
        saved.write_bytes(b'original disabled backup')
        with self.assertRaises(ValueError):
            perf_mods.retire_legacy_more_culling('1.21.11', 'fabric', 'selected')
        self.assertTrue((self.profile / 'moreculling.jar').exists())
        self.assertEqual(saved.read_bytes(), b'original disabled backup')

    def test_explicit_download_before_first_launch_is_preserved(self):
        (self.profile / 'moreculling.jar').unlink()
        with patch.object(mods.global_mod_cache, 'get_or_fetch',
                          side_effect=lambda dest, *_: self.write_jar(dest, 'moreculling')):
            mods.download_mod('https://cdn.modrinth.com/test.jar', 'chosen.jar',
                              project_id='51shyZVL', slug='moreculling',
                              mc_version='1.21.11', loader='fabric', version_id='selected')
        self.play()
        self.assertTrue((self.profile / 'chosen.jar').exists())
        self.assertFalse((self.profile / 'chosen.jar.disabled').exists())

    def test_pending_migration_does_not_disable_a_replaced_filename(self):
        mods._write_meta(str(self.profile), 'moreculling.jar', 'moreculling')
        with patch.object(perf_mods, 'toggle_mod', side_effect=OSError('file locked')):
            with self.assertRaises(OSError):
                perf_mods.retire_legacy_more_culling('1.21.11', 'fabric', 'selected')
        self.write_jar(self.profile / 'moreculling.jar', 'other-mod')
        self.assertEqual(perf_mods.retire_legacy_more_culling(
            '1.21.11', 'fabric', 'selected'), [])
        self.assertTrue((self.profile / 'moreculling.jar').exists())

    def test_launch_retires_even_with_both_toggles_off_and_blocks_failed_migration(self):
        # Execute the actual prelaunch block without starting a JVM/network.
        source = Path(mods.__file__).with_name('launch.py').read_text()
        tree = ast.parse(source)
        launch = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == 'launch_game')
        block = next(n for n in launch.body if isinstance(n, ast.If)
                     and 'retire_legacy_more_culling' in ast.unparse(n))
        code = compile(ast.Module(body=[block], type_ignores=[]), 'launch.py', 'exec')
        statuses = []
        context = {'__package__': 'cubeon', 'cfg': {'client_mod_enabled': False,
                    'perf_mods_enabled': False}, 'mc_version': '1.21.11',
                   'loader': 'fabric', 'version_id': 'selected',
                   'status_cb': statuses.append}
        mods._write_meta(str(self.profile), 'moreculling.jar', 'moreculling')
        with patch.object(perf_mods, 'toggle_mod', side_effect=OSError('locked')):
            with self.assertRaisesRegex(RuntimeError, 'disable More Culling in Mods'):
                exec(code, context)
        self.assertTrue((self.profile / 'moreculling.jar').exists())
        exec(code, context)
        self.assertTrue((self.profile / 'moreculling.jar.disabled').exists())
        self.assertTrue(statuses)


if __name__ == '__main__':
    unittest.main()
