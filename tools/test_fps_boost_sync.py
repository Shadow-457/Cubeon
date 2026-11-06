"""Opt-in FPS settings: repeated launches, backup recovery, codecs and UI saves."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import game_options as go
from ui.fps_boost import build_boost_options


class SyncedVideo(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.path = self.root / 'options.txt'
        self.original = ('graphicsPreset:"fancy"\nrenderDistance:20\nsimulationDistance:12\n'
                         'enableVsync:true\nmaxFps:144\nao:true\nparticles:0\n'
                         'resourcePacks:["my-pack"]\nkey_key.forward:key.keyboard.up\n')
        self.path.write_text(self.original)

    def sync(self, enabled=True, **kwargs):
        return go.sync_fps_boost(enabled, str(self.path), sync_settings=True,
                                 mc_version='26.3', **kwargs)

    def test_repeated_sync_enforces_edits_without_losing_originals(self):
        self.assertTrue(self.sync()['changed'])
        marker = Path(str(self.path) + '.cubeon-boost.json')
        first_backup = json.loads(marker.read_text())['before']
        first = self.path.read_bytes()
        self.assertFalse(self.sync()['changed'])
        self.assertEqual(self.path.read_bytes(), first)
        self.path.write_text(self.path.read_text().replace('renderDistance:4', 'renderDistance:30')
                             .replace('maxFps:260', 'maxFps:60').replace('particles:2', 'particles:0'))
        self.assertTrue(self.sync()['changed'])
        self.assertEqual(self.path.read_bytes(), first)
        self.assertEqual(json.loads(marker.read_text())['before'], first_backup)
        self.sync(False)
        self.assertEqual(self.path.read_text(), self.original)

    def test_sync_off_stops_enforcing_and_boost_off_preserves_later_edits(self):
        self.sync()
        edited = self.path.read_text().replace('maxFps:260', 'maxFps:90')
        self.path.write_text(edited)
        go.sync_fps_boost(True, str(self.path), sync_settings=False, mc_version='26.3')
        self.assertEqual(self.path.read_text(), edited)
        self.sync(False)
        self.assertEqual(self.path.read_text(), self.original.replace('maxFps:144', 'maxFps:90'))

    def test_upgrade_from_ordinary_boost_restores_the_original_settings(self):
        go.sync_fps_boost(True, str(self.path))
        self.sync()
        self.sync(False)
        self.assertEqual(self.path.read_text(), self.original)

    def test_failed_sync_write_can_restore_the_preceding_ordinary_boost(self):
        go.sync_fps_boost(True, str(self.path))
        previous = self.path.read_bytes()
        mkstemp = go.tempfile.mkstemp

        def full_for_options(*args, **kwargs):
            if kwargs.get('prefix') == '.cubeon-options-':
                raise OSError('disk full')
            return mkstemp(*args, **kwargs)

        with patch.object(go.tempfile, 'mkstemp', side_effect=full_for_options):
            self.assertIn('not writable', self.sync()['detail'])
        self.assertEqual(self.path.read_bytes(), previous)
        self.sync(False)
        self.assertEqual(self.path.read_text(), self.original)

    def test_backup_failure_and_corruption_never_overwrite_options(self):
        with patch.object(go, 'write_json', side_effect=OSError('read-only')):
            self.assertFalse(self.sync()['changed'])
        self.assertEqual(self.path.read_text(), self.original)
        Path(str(self.path) + '.cubeon-boost.json').write_text('{bad')
        self.assertFalse(self.sync()['changed'])
        self.assertEqual(self.path.read_text(), self.original)

    def test_first_launch_seeds_only_supported_keys_and_the_installed_data_version(self):
        self.path.unlink()
        jar = self.root / 'versions/26.3/26.3.jar'
        jar.parent.mkdir(parents=True)
        with zipfile.ZipFile(jar, 'w') as z:
            z.writestr('version.json', json.dumps({'world_version': 12345}))
        with patch.object(go, 'MINECRAFT_DIR', str(self.root)):
            self.sync()
        data = dict(line.split(':', 1) for line in self.path.read_text().splitlines())
        self.assertEqual(data['version'], '12345')
        self.assertEqual(data['graphicsPreset'], '"custom"')
        self.assertEqual(data['renderClouds'], '"false"')
        self.assertEqual(data['weatherRadius'], '3')
        self.assertEqual(data['cutoutLeaves'], 'false')
        self.assertEqual(data['renderDistance'], '4')
        self.assertEqual(data['simulationDistance'], '5')
        self.assertEqual(data['vignette'], 'false')
        self.assertNotIn('graphicsMode', data)
        self.assertNotIn('fancyGraphics', data)
        self.sync(False)
        self.assertEqual(self.path.read_text(), 'version:12345\n')

    def test_legacy_first_launch_uses_legacy_encodings(self):
        self.path.unlink()
        go.sync_fps_boost(True, str(self.path), sync_settings=True, mc_version='1.8.9')
        text = self.path.read_text()
        self.assertIn('fancyGraphics:false\n', text)
        self.assertIn('ao:0\n', text)
        self.assertIn('renderClouds:false\n', text)
        self.assertNotIn('simulationDistance:', text)
        self.assertNotIn('graphicsPreset:', text)
        self.assertNotIn('weatherRadius:', text)

    def test_unknown_version_does_not_get_invented_keys(self):
        self.path.unlink()
        result = go.sync_fps_boost(True, str(self.path), sync_settings=True, mc_version='future-snapshot')
        self.assertFalse(result['changed'])
        self.assertFalse(self.path.exists())
        self.path.write_text('maxFps:60\nrenderClouds:"true"\n')
        go.sync_fps_boost(True, str(self.path), sync_settings=True, mc_version='future-snapshot')
        self.assertEqual(self.path.read_text(), 'maxFps:260\nrenderClouds:"false"\n')

    def test_crlf_unrelated_lines_and_instance_isolation(self):
        original = self.original.replace('\n', '\r\n').encode()
        self.path.write_bytes(original)
        sibling = self.root / 'other-options.txt'
        sibling.write_bytes(original)
        self.sync()
        self.assertNotIn(b'\n', self.path.read_bytes().replace(b'\r\n', b''))
        self.sync(False)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(sibling.read_bytes(), original)


class BoostControls(unittest.TestCase):
    def setUp(self):
        self.cfg = {'fps_boost_enabled': True}
        self.save = Mock()
        self.status = Mock()
        self.row = build_boost_options(self.cfg, self.save, self.status,
                                       accent='#00ff00', text_color='#ffffff')
        self.sync, self.menu = self.row.controls
        self.repaint = patch('ui.fps_boost.thread_safe_ui.refresh').start()
        self.addCleanup(patch.stopall)

    def test_sync_and_each_optional_choice_persist_independently(self):
        self.sync.value = True
        self.sync.on_change(SimpleNamespace(control=self.sync))
        self.assertTrue(self.cfg['fps_boost_sync_settings'])
        choices = [i for i in self.menu.items if i.data]
        self.assertEqual([i.data for i in choices], ['moreculling', 'ebe', 'exordium'])
        for item in choices:
            item.on_click(SimpleNamespace(control=item))
        self.assertEqual(self.cfg['fps_boost_optional_mods'], ['moreculling', 'ebe', 'exordium'])
        choices[1].on_click(SimpleNamespace(control=choices[1]))
        self.assertEqual(self.cfg['fps_boost_optional_mods'], ['moreculling', 'exordium'])

    def test_save_failure_rolls_back_preferences_and_the_visible_choice(self):
        self.save.side_effect = OSError('read-only')
        self.sync.value = True
        self.sync.on_change(SimpleNamespace(control=self.sync))
        self.assertFalse(self.sync.value)
        self.assertNotIn('fps_boost_sync_settings', self.cfg)
        self.menu.items[1].on_click(SimpleNamespace(control=self.menu.items[1]))
        self.assertFalse(self.menu.items[1].checked)
        self.assertNotIn('fps_boost_optional_mods', self.cfg)

    def test_boost_off_ignores_stale_control_events(self):
        self.row.disabled = True
        self.sync.value = True
        self.sync.on_change(SimpleNamespace(control=self.sync))
        self.menu.items[1].on_click(SimpleNamespace(control=self.menu.items[1]))
        self.save.assert_not_called()
        self.assertFalse(self.sync.value)


if __name__ == '__main__':
    unittest.main()
