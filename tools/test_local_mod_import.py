"""Local imports validate actual archives, retain backups and survive UI races."""
import asyncio
import builtins
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import config, local_mods, mods, thread_safe_ui
from ui.local_mod_import import LocalModImport
from app_driver import DriverPage
from test_content_install_feedback import QueuedThread


class LocalImports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profiles = self.root / 'profiles'
        self.patch = patch.object(mods, 'PROFILES_DIR', str(self.profiles))
        self.patch.start(); self.addCleanup(self.patch.stop)

    def jar(self, name='example.jar', identity='example', version='1.0', depends=None, environment='*', loader='fabric'):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as archive:
            if loader == 'fabric':
                archive.writestr('fabric.mod.json', json.dumps({'id': identity, 'name': identity.title(), 'version': version,
                                   'depends': depends or {'minecraft': '>=1.21 <1.22'}, 'environment': environment}))
            elif loader == 'forge':
                archive.writestr('META-INF/mods.toml', f'[[mods]]\nmodId="{identity}"\nversion="{version}"\n')
            archive.writestr('content.bin', version)
        return str(path)

    def review(self, paths):
        return local_mods.review_files(paths, '1.21.11', 'fabric')

    def install(self, path):
        review = self.review([path])
        return local_mods.import_review(review, review['entries'])

    @property
    def profile(self):
        return Path(mods.resolve_profile_dir('1.21.11', 'fabric'))

    def test_preview_is_read_only_and_rejects_wrong_loader_version_server_and_nonmods(self):
        files = [self.jar(), self.jar('forge.jar', loader='forge'),
                 self.jar('wrong-version.jar', identity='wrong', depends={'minecraft': '1.20.1'}),
                 self.jar('server.jar', identity='server', environment='server'), self.jar('library.jar', loader='none')]
        corrupt = self.root / 'corrupt.jar'; corrupt.write_text('not a jar')
        review = self.review(files + [str(corrupt)])
        self.assertEqual([e['status'] for e in review['entries']], ['ready'] + ['blocked'] * 5)
        self.assertFalse(self.profiles.exists())
        self.assertIn('forge', review['entries'][1]['detail'])
        self.assertIn('1.20.1', review['entries'][2]['detail'])
        self.assertIn('server-only', review['entries'][3]['detail'])

    def test_duplicate_bytes_even_with_renamed_file_are_not_installed_twice(self):
        source = self.jar()
        self.assertEqual(self.install(source)[0]['status'], 'imported')
        renamed = self.root / 'renamed.jar'; shutil.copyfile(source, renamed)
        review = self.review([str(renamed)])
        self.assertEqual(review['entries'][0]['status'], 'duplicate')
        result = local_mods.import_review(review, review['entries'])[0]
        self.assertEqual(result['filename'], 'example.jar')
        self.assertEqual(sorted(p.name for p in self.profile.glob('*.jar')), ['example.jar'])

    def test_replacement_requires_selection_and_retains_old_bytes_and_metadata(self):
        old = self.jar('old.jar'); self.install(old)
        old_bytes = Path(old).read_bytes()
        mods._write_meta(str(self.profile), 'old.jar', 'example')
        new = self.jar('new.jar', version='2.0')
        review = self.review([new]); entry = review['entries'][0]
        self.assertEqual(entry['status'], 'replace')
        refused = local_mods.import_review(review, [entry])[0]
        self.assertEqual(refused['status'], 'failed')
        self.assertTrue((self.profile / 'old.jar').exists())
        result = local_mods.import_review(review, [entry], replace=True)[0]
        self.assertEqual(result['status'], 'imported')
        self.assertFalse((self.profile / 'old.jar').exists())
        self.assertEqual((self.profile / 'old.jar.disabled').read_bytes(), old_bytes)
        self.assertEqual(mods._read_meta(str(self.profile), 'old.jar.disabled')['slug'], 'example')

    def test_same_name_replacement_keeps_multiple_backups(self):
        source = self.jar(); self.install(source)
        for version in ('2.0', '3.0'):
            self.jar(version=version)
            review = self.review([source])
            self.assertEqual(local_mods.import_review(review, review['entries'], replace=True)[0]['status'], 'imported')
        self.assertEqual(len(list(self.profile.glob('*.jar.disabled'))), 2)
        self.assertEqual(mods.read_mod_metadata(str(self.profile / 'example.jar'))['version'], '3.0')

    def test_modified_source_or_profile_is_rejected_after_review(self):
        path = self.jar(); review = self.review([path])
        self.jar(version='2.0')
        self.assertIn('file changed', local_mods.import_review(review, review['entries'])[0]['detail'])
        path = self.jar('new.jar'); review = self.review([path])
        self.install(self.jar('old.jar', version='3.0'))
        result = local_mods.import_review(review, review['entries'], replace=True)[0]
        self.assertIn('Installed mods changed', result['detail'])
        self.assertFalse((self.profile / 'new.jar').exists())

    def test_failed_publication_restores_old_mod_and_sidecar(self):
        self.install(self.jar('old.jar'))
        mods._write_meta(str(self.profile), 'old.jar', 'example')
        review = self.review([self.jar('new.jar', version='2.0')])
        original_open = builtins.open
        def failed_open(path, mode='r', *args, **kwargs):
            if mode == 'xb' and str(path) == str(self.profile / 'new.jar'):
                raise PermissionError('disk refused publication')
            return original_open(path, mode, *args, **kwargs)
        with patch('cubeon.local_mods.os.link', side_effect=OSError('no hardlinks')), patch('builtins.open', side_effect=failed_open):
            result = local_mods.import_review(review, review['entries'], replace=True)[0]
        self.assertEqual(result['status'], 'failed')
        self.assertTrue((self.profile / 'old.jar').exists())
        self.assertFalse((self.profile / 'old.jar.disabled').exists())
        self.assertEqual(mods._read_meta(str(self.profile), 'old.jar')['slug'], 'example')

    def test_dependency_warning_resolves_from_same_batch(self):
        main = self.jar(depends={'minecraft': '>=1.21', 'helper': '>=2'})
        self.assertIn('helper', self.review([main])['entries'][0]['warnings'][0])
        helper = self.jar('helper.jar', identity='helper', version='2.0')
        review = self.review([main, helper])
        self.assertEqual(review['entries'][0]['warnings'], [])
        warnings = local_mods.selection_warnings(review, [review['entries'][0]])
        self.assertIn('helper', warnings[main][0])

    def test_invalid_file_does_not_prevent_other_batch_imports(self):
        wrong = self.jar('wrong.jar', depends={'minecraft': '1.20'})
        review = self.review([wrong, self.jar()])
        results = local_mods.import_review(review, review['entries'])
        self.assertEqual([r['status'] for r in results], ['failed', 'imported'])

    def test_two_selected_builds_are_not_both_enabled(self):
        review = self.review([self.jar('one.jar'), self.jar('two.jar', version='2.0')])
        self.assertEqual(review['entries'][1]['status'], 'blocked')
        results = local_mods.import_review(review, review['entries'], replace=True)
        self.assertEqual([r['status'] for r in results], ['imported', 'failed'])
        self.assertEqual(len(list(self.profile.glob('*.jar'))), 1)

    def test_managed_identity_cannot_be_smuggled_through_renamed_jar(self):
        review = self.review([self.jar(identity='customskinloader')])
        self.assertEqual(review['entries'][0]['status'], 'blocked')

    def test_profile_rebinding_after_review_never_writes_to_another_profile(self):
        review = local_mods.review_files([self.jar()], '1.21.11', 'fabric', version_id='capture-instance')
        with patch.object(mods, 'read_instance_meta', return_value={'profile': 'other-instance'}):
            result = local_mods.import_review(review, review['entries'])[0]
        self.assertEqual(result['status'], 'failed')
        self.assertIn('profile changed', result['detail'])
        self.assertFalse((self.profiles / 'other-instance').exists())

    def test_core_entry_points_share_validation(self):
        with self.assertRaises(ValueError):
            mods.add_mod_file('1.21.11', 'fabric', self.jar(loader='none'))
        with self.assertRaises(ValueError):
            mods.install_local_mod(self.jar(), '1.21.11', 'vanilla')

    def test_review_ui_waits_for_selection_and_imports_outside_tree_lock(self):
        self.install(self.jar('old.jar'))
        review = self.review([self.jar('new.jar', version='2.0'), self.jar('helper.jar', identity='helper')])
        page, finished, closed = DriverPage(), Mock(), Mock()
        QueuedThread.jobs.clear()
        with patch.object(thread_safe_ui, 'refresh'), patch('threading.Thread', QueuedThread):
            prompt = LocalModImport(page, review, instance_label='My instance', finished=finished, closed=closed).open()
            self.assertFalse((self.profile / 'new.jar').exists())
            self.assertFalse(prompt.choices[0][1].value)
            prompt.choices[0][1].value = True
            prompt._selection_changed()
            prompt._import(); prompt._import()
            self.assertEqual(len(QueuedThread.jobs), 1)
            prompt._close(); closed.assert_not_called()
            def actual_import(*args, **kwargs):
                self.assertFalse(thread_safe_ui.TREE_LOCK._is_owned())
                return real_import(*args, **kwargs)
            real_import = local_mods.import_review
            with patch.object(local_mods, 'import_review', side_effect=actual_import):
                QueuedThread.jobs.pop()()
            self.assertEqual(prompt.phase, 'done')
            finished.assert_called_once()
            self.assertEqual(finished.call_args.args[0][0]['status'], 'imported')
            prompt._close(); prompt._close(); closed.assert_called_once()

    def test_file_picker_failure_delivers_reason_and_restores_handler(self):
        callback, failed = Mock(), Mock()
        async def pick_files(**kwargs):
            raise RuntimeError('zenity unavailable')
        picker = SimpleNamespace(pick_files=pick_files, on_result=callback)
        page = SimpleNamespace(run_task=lambda task: asyncio.run(task()))
        config.run_file_picker(page, picker, on_files=Mock(), on_error=failed)
        self.assertIn('zenity', str(failed.call_args.args[0]))
        self.assertIs(picker.on_result, callback)


if __name__ == '__main__':
    unittest.main()
