"""FPS renderer/effect settings: real file round trips and failure recovery."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import fps_mod_settings as fps


class ModSettings(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.directory = self.root / 'config'
        self.directory.mkdir()

    def write_json(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(value))
        return path

    def sync(self, enabled=True, sync=True):
        return fps.sync_mod_settings(self.root, enabled=enabled, sync_settings=sync)

    def test_renderer_flags_sync_and_restore_without_touching_driver_workarounds(self):
        original = {'performance': {'chunk_builder_threads': 8, 'use_fog_occlusion': False,
                                    'use_no_error_g_l_context': False, 'unknown': 'keep'},
                    'quality': {'hidden_fluid_culling': False},
                    'advanced': {'use_advanced_staging_buffers': False, 'cpu_render_ahead_limit': 1}}
        paths = [self.write_json(name, original) for name in
                 ('sodium-options.json', 'embeddium-options.json', 'rubidium-options.json')]
        report = self.sync()
        self.assertEqual(set(report['changed']), {p.name for p in paths})
        self.assertEqual(report['errors'], [])
        for path in paths:
            data = json.loads(path.read_text())
            self.assertEqual(data['performance']['chunk_builder_threads'], 2)
            self.assertTrue(data['performance']['use_fog_occlusion'])
            self.assertFalse(data['performance']['use_no_error_g_l_context'])
            self.assertEqual(data['advanced'], original['advanced'])
            self.assertNotIn('use_entity_culling', data['performance'])
        backup = (self.directory / fps.BACKUP).read_bytes()
        with patch.object(fps, 'write_json', wraps=fps.write_json) as write:
            self.assertEqual(self.sync()['changed'], [])
            write.assert_not_called()
        self.assertEqual((self.directory / fps.BACKUP).read_bytes(), backup)
        self.sync(False)
        for path in paths:
            self.assertEqual(json.loads(path.read_text()), original)

    def test_repeat_sync_preserves_first_backup_and_off_preserves_later_edits(self):
        path = self.write_json('sodium-options.json', {'performance': {'chunk_builder_threads': 6}})
        self.sync()
        path.write_text(json.dumps({'performance': {'chunk_builder_threads': 1}}))
        self.sync()
        self.assertEqual(json.loads(path.read_text())['performance']['chunk_builder_threads'], 2)
        self.sync(False)
        self.assertEqual(json.loads(path.read_text())['performance']['chunk_builder_threads'], 6)
        self.sync()
        path.write_text(json.dumps({'performance': {'chunk_builder_threads': 3}}))
        self.sync(False)
        self.assertEqual(json.loads(path.read_text())['performance']['chunk_builder_threads'], 3)

    def test_sync_off_is_a_true_noop_even_with_a_bad_backup(self):
        path = self.write_json('sodium-options.json', {'performance': {'chunk_builder_threads': 8}})
        original = path.read_bytes()
        (self.directory / fps.BACKUP).write_text('{broken')
        self.assertEqual(self.sync(sync=False), {'changed': [], 'errors': []})
        self.assertEqual(path.read_bytes(), original)

    def test_shaders_disable_without_changing_packs_comments_or_crlf(self):
        originals = {}
        for name in ('iris.properties', 'oculus.properties'):
            original = b'# settings\r\nshaderPack=My\\ Pack.zip\r\n enableShaders : true  \r\nother=keep\r\n'
            path = self.directory / name
            path.write_bytes(original)
            originals[path] = original
        self.sync()
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original.replace(b': true  \r\n', b': false\r\n'))
        self.sync(False)
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_effects_and_batching_keep_compatibility_and_other_hud_preferences(self):
        blur = {'cameraMotionBlur': True, 'temporalMotionBlur': False, 'cameraBlurIntensity': 1.75,
                'showEmotes': True, 'wingDepth': True, 'overlay': {'position': [20, 30]}}
        batching = {'enhanced_batching': False, 'fast_text_lookup': False,
                    'avoid_redundant_framebuffer_switching': False,
                    'debug_only_and_not_recommended_disable_hardware_conflict_handling': False}
        hud = self.write_json('cubeon-client-hud.json', blur)
        batch = self.write_json('immediatelyfast.json', batching)
        compat = self.write_json('entityculling.json', {'skipEntityCulling': True})
        compat_before = compat.read_bytes()
        self.sync()
        self.assertEqual(json.loads(hud.read_text()), dict(blur, cameraMotionBlur=False))
        data = json.loads(batch.read_text())
        self.assertFalse(data['enhanced_batching'])
        self.assertTrue(data['fast_text_lookup'])
        self.assertFalse(data['debug_only_and_not_recommended_disable_hardware_conflict_handling'])
        self.assertEqual(compat.read_bytes(), compat_before)
        self.sync(False)
        self.assertEqual(json.loads(hud.read_text()), blur)
        self.assertEqual(json.loads(batch.read_text()), batching)

    def test_iris_exact_false_codec_and_raw_value_restore(self):
        shader = self.directory / 'iris.properties'
        for value in ('false  ', 'FALSE', 'true', 'false', '\\u0066alse', ''):
            with self.subTest(value=value):
                original = 'enableShaders=' + value + '\n'
                shader.write_text(original)
                self.sync()
                # Actual Iris/Oculus enableShaders = !"false".equals(property).
                self.assertEqual(shader.read_text(), 'enableShaders=false\n')
                self.sync(False)
                self.assertEqual(shader.read_text(), original)

    def test_backup_failure_never_changes_a_config(self):
        path = self.write_json('sodium-options.json', {'performance': {'chunk_builder_threads': 8}})
        original = path.read_bytes()
        with patch.object(fps, 'write_json', side_effect=OSError('read-only')):
            report = self.sync()
        self.assertEqual(report['changed'], [])
        self.assertTrue(report['errors'])
        self.assertEqual(path.read_bytes(), original)

    def test_config_write_failure_keeps_backup_and_retry_recovers(self):
        path = self.write_json('sodium-options.json', {'performance': {'chunk_builder_threads': 8}})
        original = path.read_bytes()
        real_write = fps.write_json

        def fail_config(target, value):
            if Path(target) == path:
                raise OSError('config locked')
            real_write(target, value)

        with patch.object(fps, 'write_json', side_effect=fail_config):
            self.assertTrue(self.sync()['errors'])
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue((self.directory / fps.BACKUP).exists())
        self.assertEqual(self.sync()['changed'], ['sodium-options.json'])
        self.sync(False)
        self.assertEqual(json.loads(path.read_text()), json.loads(original))

    def test_corrupt_backups_and_configs_do_not_reset_player_settings(self):
        path = self.write_json('sodium-options.json', {'performance': {'chunk_builder_threads': 8}})
        original = path.read_bytes()
        marker = self.directory / fps.BACKUP
        marker.write_text('{broken')
        self.assertTrue(self.sync()['errors'])
        self.assertEqual(path.read_bytes(), original)
        marker.unlink()
        path.write_text('{invalid config')
        self.assertTrue(self.sync()['errors'])
        self.assertEqual(path.read_text(), '{invalid config')

    def test_ambiguous_shader_config_is_left_intact_and_other_files_still_work(self):
        shader = self.directory / 'iris.properties'
        shader.write_text('enableShaders=true\nenableShaders=false\n')
        original = shader.read_bytes()
        self.write_json('cubeon-client-hud.json', {'temporalMotionBlur': True})
        report = self.sync()
        self.assertTrue(report['errors'])
        self.assertEqual(shader.read_bytes(), original)
        self.assertIn('cubeon-client-hud.json', report['changed'])

    def test_escaped_duplicate_keys_and_continued_properties_are_not_misparsed(self):
        shader = self.directory / 'iris.properties'
        for text in ('enableShaders=true\nenable\\u0053haders=true\n',
                     'shaderPack=name\\\nenableShaders=true\n',
                     'EnableShaders=true\n'):
            with self.subTest(text=text):
                shader.write_text(text)
                report = self.sync()
                self.assertTrue(report['errors'])
                self.assertEqual(shader.read_text(), text)

    def test_no_fresh_configs_and_no_recreation_of_removed_files(self):
        self.assertEqual(self.sync(), {'changed': [], 'errors': []})
        self.assertEqual(list(self.directory.iterdir()), [])
        path = self.write_json('sodium-options.json', {'performance': {'chunk_builder_threads': 8}})
        self.sync()
        path.unlink()
        self.sync(False)
        self.assertFalse(path.exists())
        self.assertEqual(json.loads((self.directory / fps.BACKUP).read_text())['files'], {})


if __name__ == '__main__':
    unittest.main()
