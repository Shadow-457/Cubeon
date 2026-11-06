"""Play must reject escaped version paths before writes or command building."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import launch, versions, watchdog


class VersionSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'game'
        self.vdir = self.game / 'versions'
        self.vdir.mkdir(parents=True)
        self.patch = patch.object(versions, 'MINECRAFT_DIR', str(self.game))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def profile(self, name, data):
        folder = self.vdir / name
        folder.mkdir(exist_ok=True)
        (folder / (name + '.json')).write_text(json.dumps(data))
        return folder

    def test_escaped_ids_never_reach_install_or_command_builder(self):
        with patch.object(versions, '_seed_version_json') as seed, \
                patch.object(launch.mll.command, 'get_minecraft_command') as command:
            for value in ('../escape', 'nested/id', '..\\escape', '/tmp/escape',
                          'C:escape', '\x00', '.', '..', '', None):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        versions.install_version(value, lambda x: None, lambda x: None, lambda x: None)
                    with self.assertRaises(ValueError):
                        launch.build_launch_command(value, 'Pilot', 1024, 854, 480)
            seed.assert_not_called()
            command.assert_not_called()

    def test_inherited_paths_and_cycles_are_refused(self):
        self.profile('bad', {'id': 'bad', 'inheritsFrom': '../outside'})
        self.profile('a', {'id': 'a', 'inheritsFrom': 'b'})
        self.profile('b', {'id': 'b', 'inheritsFrom': 'a'})
        self.profile('bad-jar', {'jar': '..\\outside'})
        for name in ('bad', 'a', 'bad-jar'):
            with self.assertRaises(ValueError):
                versions.validate_launch_profile(name)

    def test_custom_names_and_shared_base_references_stay_valid(self):
        self.profile('My World 世界', {'inheritsFrom': '1.21.11', 'jar': '1.21.11'})
        self.profile('1.21.11', {'id': '1.21.11', 'jar': '1.21.11'})
        versions.validate_launch_profile('My World 世界')

    def test_external_symlinks_cannot_be_normalized_or_deleted(self):
        outside = self.root / 'outside'
        outside.mkdir()
        sentinel = outside / 'loose.json'
        sentinel.write_text('{"id":"linked"}')
        (outside / 'linked.jar').write_bytes(b'PK' + bytes(100))
        (self.vdir / 'linked').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            versions.delete_version('linked')
        self.assertEqual(versions.get_installed_versions(), [])
        self.assertFalse((outside / 'linked.json').exists())
        folder = self.profile('json-link', {'id': 'json-link'})
        (folder / 'json-link.json').unlink()
        (folder / 'json-link.json').symlink_to(sentinel)
        with self.assertRaises(ValueError):
            versions.validate_launch_profile('json-link')

        # A foreign launcher's alternate filename must not bypass the guard
        # when the tolerant scanner normalizes it to the canonical name.
        alternate = self.vdir / 'alternate'
        alternate.mkdir()
        (alternate / 'foreign.json').symlink_to(sentinel)
        (alternate / 'foreign.jar').symlink_to(outside / 'linked.jar')
        versions.get_installed_versions()
        self.assertFalse((alternate / 'alternate.json').exists())
        self.assertFalse((alternate / 'alternate.jar').exists())

    def test_live_install_cannot_be_deleted(self):
        folder = self.profile('1.21.11', {'id': '1.21.11'})
        with versions._active_install('1.21.11'), self.assertRaises(ValueError):
            versions.delete_version('1.21.11')
        self.assertTrue(folder.exists())

    def test_disappearing_version_root_does_not_break_the_picker(self):
        with patch.object(versions.os, 'listdir', side_effect=FileNotFoundError):
            self.assertEqual(versions.get_installed_versions(), [])

    def test_transitive_dependents_protect_their_base(self):
        self.profile('1.21.11', {'id': '1.21.11'})
        self.profile('loader', {'inheritsFrom': '1.21.11'})
        self.profile('pack', {'inheritsFrom': 'loader'})
        self.profile('jar-user', {'jar': '1.21.11'})
        self.assertEqual(versions.dependents_of('1.21.11'), ['jar-user', 'loader', 'pack'])
        with patch.object(watchdog, 'stale_session', return_value={'version': 'pack'}):
            with self.assertRaises(ValueError):
                versions.delete_version('1.21.11')

    def test_existing_game_blocks_backend_before_configuration_writes(self):
        with patch.object(watchdog, 'stale_session', return_value={'version': 'other'}), \
                patch.object(launch, 'game_dir_for') as folders:
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                launch.launch_game('1.21.11', 'Pilot', 1024, 854, 480, None,
                                   mc_version='1.21.11', loader='vanilla', cfg={})
            folders.assert_not_called()

    def test_renamed_instance_uses_recorded_java_requirement(self):
        folder = self.profile('Survival 2.0', {'id': 'Survival 2.0'})
        (folder / '_cubeon_instance.json').write_text('{"mc_version":"1.21.11"}')
        self.assertEqual(launch.required_java_major('Survival 2.0'), 21)

    def test_java_probe_reuses_success_but_invalidates_replaced_binary(self):
        binary = self.root / 'java'
        binary.write_bytes(b'java-21')
        binary.chmod(0o755)
        with patch.object(launch.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout='', stderr='openjdk version "21.0.1"')) as run:
            self.assertEqual(launch.java_major_version(str(binary)), 21)
            self.assertEqual(launch.java_major_version(str(binary)), 21)
            self.assertEqual(run.call_count, 1)
            binary.write_bytes(b'java-25-replacement')
            run.return_value.stderr = 'openjdk version "25.0.1"'
            self.assertEqual(launch.java_major_version(str(binary)), 25)
            self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
