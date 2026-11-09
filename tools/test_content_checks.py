"""Offline detection and explicit resolution against real JARs and UI callbacks."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
import test_mod_prelaunch_dependencies as fixtures
from cubeon import mods, net, thread_safe_ui, content_checks
from cubeon.content_checks import check_content
from ui import content_checks as checks_ui
from app_driver import DriverPage
from test_content_install_feedback import QueuedThread


class LocalCheckTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DependencyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.target = ('mod', self.fixture.mc, 'fabric', self.fixture.instance)

    def test_missing_detection_is_read_only_offline_and_repeatable(self):
        before = mods._doctor_profile_snapshot(str(self.fixture.profile))
        with patch.object(mods, 'get_mod_download', side_effect=AssertionError('network')) as lookup, \
                patch.object(net, 'get_json', side_effect=AssertionError('network')), \
                patch.object(net, 'download_to', side_effect=AssertionError('download')):
            cold = check_content(self.target)
            warm = check_content(self.target)
        self.assertEqual(cold['unfixed'], warm['unfixed'])
        self.assertEqual(cold['unfixed'][0]['dependency'], 'cloth-config')
        self.assertTrue(cold['unfixed'][0]['missing'])
        self.assertFalse(cold['fixed'])
        self.assertFalse(lookup.called)
        self.assertEqual(before, mods._doctor_profile_snapshot(str(self.fixture.profile)))
        self.assertGreaterEqual(cold['elapsed'], 0)
        self.assertFalse(list(self.fixture.profile.rglob('.cubeon-auto-doctor.json')))

    def test_declared_conflicts_and_duplicates_keep_both_names(self):
        profile = self.fixture.profile
        profile.joinpath('alpha.jar').write_bytes(fixtures.jar('alpha', '1', breaks={'beta': '*'}))
        profile.joinpath('beta.jar').write_bytes(fixtures.jar('beta', '1'))
        profile.joinpath('beta-copy.jar').write_bytes(fixtures.jar('beta', '1'))
        report = check_content(self.target)
        conflict = next(problem for problem in report['unfixed'] if problem['kind'] == 'conflict')
        self.assertIn('alpha', conflict['detail'])
        self.assertIn('beta', conflict['detail'])
        duplicate = next(problem for problem in report['unfixed'] if problem['kind'] == 'duplicate')
        self.assertIn('beta-copy.jar', duplicate['detail'])
        self.assertIn('beta.jar', duplicate['detail'])
        self.assertEqual({option['filename'] for option in duplicate['disable_options']}, {'beta.jar', 'beta-copy.jar'})
        self.assertTrue(profile.joinpath('beta-copy.jar').exists())

    def test_explicit_resolution_installs_then_local_check_is_clean(self):
        self.fixture.remote_jar('cloth-config')
        with patch.object(mods, 'get_mod_download', side_effect=self.fixture.lookup), \
                patch.object(mods, 'get_mod_versions', return_value=[]), \
                patch.object(net, 'download_to', side_effect=self.fixture.download):
            report = check_content(self.target, resolve=True)
        self.assertFalse(report['unfixed'])
        self.assertTrue(report['fixed'])
        self.assertTrue(self.fixture.downloads)
        self.assertFalse(check_content(self.target)['unfixed'])

    def test_disable_incompatible_mod_keeps_jar_and_other_instance_offline(self):
        filename = 'rei.jar'
        original = fixtures.jar('roughlyenoughitems', '1', {'minecraft': '1.21.1'})
        self.fixture.profile.joinpath(filename).write_bytes(original)
        sibling = Path(mods.get_profile_dir(self.fixture.mc, 'fabric', 'other-instance'))
        sibling.joinpath(filename).write_bytes(original)
        issue = next(problem for problem in check_content(self.target)['unfixed']
                     if problem['kind'] == 'incompatible')
        option = issue['disable_options'][0]
        self.assertEqual(option['filename'], filename)
        backup = self.fixture.profile.joinpath(filename + '.disabled')
        backup.write_bytes(b'previous disabled copy')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            content_checks.disable_problem_mod(self.target, option)
        self.assertEqual(self.fixture.profile.joinpath(filename).read_bytes(), original)
        self.assertEqual(backup.read_bytes(), b'previous disabled copy')
        backup.unlink()
        with patch.object(net, 'get_json', side_effect=AssertionError('network')), \
                patch.object(net, 'download_to', side_effect=AssertionError('download')):
            result = content_checks.disable_problem_mod(self.target, option)
        self.assertEqual(self.fixture.profile.joinpath(filename + '.disabled').read_bytes(), original)
        self.assertFalse(self.fixture.profile.joinpath(filename).exists())
        self.assertEqual(sibling.joinpath(filename).read_bytes(), original)
        self.assertTrue(self.fixture.profile.joinpath('moreculling-1.6.2.jar').exists())
        self.assertFalse(any(problem['kind'] == 'incompatible' for problem in result['unfixed']))
        with self.assertRaises(ValueError):
            content_checks.disable_problem_mod(self.target, option)
        mods.toggle_mod(self.fixture.mc, 'fabric', filename + '.disabled', version_id=self.fixture.instance)
        self.assertEqual(self.fixture.profile.joinpath(filename).read_bytes(), original)

    def test_disable_rejects_changed_jar_and_protected_mod(self):
        filename = 'rei.jar'
        self.fixture.profile.joinpath(filename).write_bytes(fixtures.jar('rei', '1', {'minecraft': '1.21.1'}))
        issue = next(problem for problem in check_content(self.target)['unfixed']
                     if problem['kind'] == 'incompatible')
        option = issue['disable_options'][0]
        replacement = fixtures.jar('rei', '2', {'minecraft': '>=1.21'})
        self.fixture.profile.joinpath(filename).write_bytes(replacement)
        with self.assertRaisesRegex(ValueError, 'changed'):
            content_checks.disable_problem_mod(self.target, option)
        self.assertEqual(self.fixture.profile.joinpath(filename).read_bytes(), replacement)
        protected = 'cubeon-client-test.jar'
        self.fixture.profile.joinpath(protected).write_bytes(fixtures.jar('cubeon', '1', {'minecraft': '1.21.1'}))
        issue = next(problem for problem in check_content(self.target)['unfixed'] if problem['mod'] == 'cubeon')
        self.assertEqual(issue['disable_options'], [])
        forged = dict(filename=protected, owner='cubeon', name='Cubeon Client',
                      snapshot=mods._doctor_profile_snapshot(str(self.fixture.profile),
                                                            [protected, protected + mods.MOD_META_SUFFIX]))
        with self.assertRaisesRegex(ValueError, 'managed'):
            content_checks.disable_problem_mod(self.target, forged)

    def test_conflict_offers_either_mod_and_disable_reveals_dependents(self):
        profile = self.fixture.profile
        profile.joinpath('alpha.jar').write_bytes(fixtures.jar('alpha', '1', breaks={'beta': '*'}))
        profile.joinpath('beta.jar').write_bytes(fixtures.jar('beta', '1'))
        profile.joinpath('dependent.jar').write_bytes(fixtures.jar('dependent', '1', {'beta': '*'}))
        conflict = next(problem for problem in check_content(self.target)['unfixed'] if problem['kind'] == 'conflict')
        self.assertEqual({option['filename'] for option in conflict['disable_options']}, {'alpha.jar', 'beta.jar'})
        beta = next(option for option in conflict['disable_options'] if option['filename'] == 'beta.jar')
        report = content_checks.disable_problem_mod(self.target, beta)
        self.assertTrue(profile.joinpath('alpha.jar').exists())
        self.assertTrue(any(problem['dependency'] == 'beta' and problem.get('missing') for problem in report['unfixed']))

    def test_changes_invalidate_warm_metadata(self):
        check_content(self.target)
        self.fixture.profile.joinpath('cloth.jar').write_bytes(fixtures.jar('cloth-config', '16.1.0'))
        self.assertFalse(check_content(self.target)['unfixed'])
        self.fixture.profile.joinpath('cloth.jar').write_bytes(fixtures.jar('cloth-config', '1.0'))
        self.assertTrue(check_content(self.target)['unfixed'])

    def test_bundled_conflict_disables_the_parent_and_missing_dependency_the_requester(self):
        profile = self.fixture.profile
        profile.joinpath('alpha.jar').write_bytes(fixtures.jar('alpha', '1', breaks={'child': '*'}))
        profile.joinpath('umbrella.jar').write_bytes(fixtures.jar('umbrella', '1', nested={
            'child': fixtures.jar('child', '1')}))
        report = check_content(self.target)
        conflict = next(problem for problem in report['unfixed'] if problem['kind'] == 'conflict')
        self.assertEqual({option['filename'] for option in conflict['disable_options']}, {'alpha.jar', 'umbrella.jar'})
        missing = next(problem for problem in report['unfixed'] if problem.get('missing'))
        self.assertEqual(missing['disable_options'][0]['filename'], 'moreculling-1.6.2.jar')
        parent = next(option for option in conflict['disable_options'] if option['filename'] == 'umbrella.jar')
        result = content_checks.disable_problem_mod(self.target, parent)
        self.assertTrue(profile.joinpath('umbrella.jar.disabled').exists())
        self.assertTrue(profile.joinpath('alpha.jar').exists())
        self.assertFalse(any(problem['kind'] == 'conflict' for problem in result['unfixed']))

    def test_list_names_match_checks_and_preserve_filename_and_identity(self):
        self.fixture.profile.joinpath('c2me.jar').write_bytes(fixtures.jar('c2me', '1'))
        with zipfile.ZipFile(self.fixture.profile / 'c2me.jar', 'w') as archive:
            archive.writestr('fabric.mod.json', json.dumps({
                'id': 'c2me', 'version': '1', 'name': 'Concurrent Chunk Management Engine',
                'depends': {'java': '>=25'}}))
        entry = next(mod for mod in mods.list_mods(self.fixture.mc, 'fabric', self.fixture.instance)
                     if mod['filename'] == 'c2me.jar')
        self.assertEqual(entry['display_name'], 'Concurrent Chunk Management Engine')
        self.assertEqual(entry['mod_id'], 'c2me')
        self.assertTrue(check_content(self.target)['runtime_unverified'])

    def test_java_checks_reuse_verified_runtime_without_probing(self):
        java = self.fixture.folder / 'jdk' / 'bin' / 'java'
        java.parent.mkdir(parents=True)
        java.write_text('verified test executable')
        self.fixture.profile.joinpath('c2me.jar').write_bytes(fixtures.jar('c2me', '1', {'java': '>=25'}))
        content_checks.remember_runtime(self.target, str(java), 21)
        self.addCleanup(content_checks._runtime_cache.clear)
        with patch('cubeon.launch.java_major_version', side_effect=AssertionError('Java probe')):
            report = check_content(self.target)
        problem = next(problem for problem in report['unfixed'] if problem['dependency'] == 'java')
        self.assertIn('installed: 21', problem['detail'])
        java.write_text('changed executable')
        report = check_content(self.target)
        self.assertIn('java', report['runtime_unverified'])
        self.assertFalse(any(problem['dependency'] == 'java' for problem in report['unfixed']))


class ResultsUITests(unittest.TestCase):
    def setUp(self):
        self.page = DriverPage()
        self.state = {}
        self.target = ('mod', '1.21.11', 'fabric', 'instance-A')
        self.missing = dict(kind='required', missing=True, dependency='cloth-config', mod='More Culling',
                            detail='More Culling requires Cloth Config >=16 (missing)')
        self.conflict = dict(kind='conflict', dependency='beta', mod='Alpha', detail='Alpha conflicts with Beta')
        self.clean = dict(checked=2, fixed=[], unfixed=[])
        self.patches = [patch('threading.Thread', QueuedThread), patch.object(thread_safe_ui, 'refresh')]
        for context in self.patches:
            context.start()
            self.addCleanup(context.stop)
        QueuedThread.jobs.clear()

    def open(self, entries=None, **kwargs):
        return checks_ui.show_content_issues(self.page, self.state, self.target,
            dict(checked=2, fixed=[], unfixed=entries or [self.missing]), **kwargs)

    def test_open_is_not_consent_and_labels_match_the_issues(self):
        with patch.object(checks_ui, 'check_content') as check:
            missing = self.open()
            self.assertEqual(missing.actions[1].content, 'Install')
            conflict = self.open([self.conflict])
            self.assertEqual(conflict.actions[1].content, 'Resolve')
            mixed = self.open([self.missing, self.conflict])
            self.assertEqual(mixed.actions[1].content, 'Install & resolve')
        self.assertFalse(check.called)
        self.assertEqual(QueuedThread.jobs, [])
        self.assertFalse(self.state.get('fixing_mods'))

    def test_action_is_single_flight_captures_instance_and_rechecks(self):
        completed = []
        dialog = self.open(on_done=completed.append, runtime_versions={'java': '21'})
        self.state['selected_version'] = 'instance-B'
        with patch.object(checks_ui, 'check_content', side_effect=[self.clean, self.clean]) as check:
            dialog.actions[1].on_click(None)
            dialog.actions[1].on_click(None)
            self.assertEqual(len(QueuedThread.jobs), 1)
            self.assertEqual(self.state['fixing_mods'], 'instance-A')
            self.assertTrue(dialog.actions[0].disabled)
            QueuedThread.jobs.pop()()
        self.assertEqual(check.call_args_list[0].args, (self.target,))
        self.assertTrue(check.call_args_list[0].kwargs['resolve'])
        self.assertEqual(check.call_args_list[0].kwargs['runtime_versions'], {'java': '21'})
        self.assertNotIn('resolve', check.call_args_list[1].kwargs)
        self.assertFalse(dialog.actions[1].visible)
        self.assertIsNone(self.state['fixing_mods'])
        self.assertEqual(len(completed), 1)

    def test_busy_game_or_installer_blocks_changes(self):
        for key in ('running_version', 'installing_version', 'launching_version', 'fixing_mods'):
            self.state.clear()
            dialog = self.open()
            self.state[key] = 'instance-B'
            dialog.actions[1].on_click(None)
            self.assertEqual(QueuedThread.jobs, [], key)
            self.assertFalse(dialog.actions[1].disabled)

    def test_failed_action_keeps_named_results_and_retry_available(self):
        dialog = self.open()
        with patch.object(checks_ui, 'check_content', side_effect=OSError('offline')):
            dialog.actions[1].on_click(None)
            QueuedThread.jobs.pop()()
        self.assertIsNone(self.state['fixing_mods'])
        self.assertFalse(dialog.actions[1].disabled)
        self.assertTrue(dialog.actions[1].visible)
        dialog.actions[0].on_click(None)
        self.assertFalse(dialog.open)

    def test_disable_is_explicit_single_flight_and_rechecks_captured_instance(self):
        option = dict(filename='rei.jar', name='Roughly Enough Items', owner='rei', snapshot=[['rei.jar', 1]])
        issue = dict(kind='incompatible', detail='REI requires Minecraft ~1.21', disable_options=[option])
        completed = []
        dialog = self.open([issue], on_done=completed.append)
        from _fuzz_common import walk
        button = next(control for control in walk(dialog) if getattr(control, 'data', None) == 'content-disable-rei.jar')
        self.assertEqual(button.content, 'Disable mod')
        self.assertEqual(QueuedThread.jobs, [])
        self.state['selected_version'] = 'instance-B'
        with patch.object(checks_ui, 'disable_problem_mod', return_value=self.clean) as disable, \
                patch.object(checks_ui, 'check_content') as resolve:
            button.on_click(None)
            button.on_click(None)
            dialog.actions[1].on_click(None)
            self.assertEqual(len(QueuedThread.jobs), 1)
            self.assertTrue(button.disabled)
            self.assertTrue(dialog.actions[1].disabled)
            QueuedThread.jobs.pop()()
            disable.assert_called_once_with(self.target, option, runtime_versions=None)
            resolve.assert_not_called()
        self.assertFalse(dialog.actions[1].visible)
        self.assertEqual(completed, [self.clean])
        self.assertIsNone(self.state['fixing_mods'])

    def test_disable_is_blocked_while_game_or_another_install_is_active(self):
        from _fuzz_common import walk
        option = dict(filename='rei.jar', name='REI', owner='rei')
        issue = dict(kind='incompatible', detail='Wrong version', disable_options=[option])
        for key in ('running_version', 'installing_version', 'launching_version', 'fixing_mods'):
            self.state.clear()
            dialog = self.open([issue])
            button = next(control for control in walk(dialog) if getattr(control, 'data', None) == 'content-disable-rei.jar')
            self.state[key] = 'instance-B'
            button.on_click(None)
            self.assertEqual(QueuedThread.jobs, [])
            self.assertFalse(button.disabled)
        self.state.clear()
        from cubeon import storage
        for owner, name in ((checks_ui, 'any_busy'), (storage, 'blocked')):
            dialog = self.open([issue])
            button = next(control for control in walk(dialog) if getattr(control, 'data', None) == 'content-disable-rei.jar')
            with patch.object(owner, name, return_value=True):
                button.on_click(None)
            self.assertEqual(QueuedThread.jobs, [])
            self.assertFalse(button.disabled)

    def test_failed_disable_releases_buttons_for_retry(self):
        from _fuzz_common import walk
        option = dict(filename='rei.jar', name='REI', owner='rei')
        dialog = self.open([dict(kind='incompatible', detail='Wrong version', disable_options=[option])])
        button = next(control for control in walk(dialog) if getattr(control, 'data', None) == 'content-disable-rei.jar')
        with patch.object(checks_ui, 'disable_problem_mod', side_effect=OSError('locked file')):
            button.on_click(None)
            QueuedThread.jobs.pop()()
        self.assertFalse(button.disabled)
        self.assertFalse(dialog.actions[1].disabled)
        self.assertIsNone(self.state['fixing_mods'])


if __name__ == '__main__':
    unittest.main()
