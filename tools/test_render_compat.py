"""Exercise reversible rendering recovery on real isolated config files."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cubeon import render_compat as compat


class RenderingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game = self.root / 'instance'
        self.config = self.game / 'config'
        self.config.mkdir(parents=True)
        self.original = {
            'entityculling.json': {'skipEntityCulling': False,
                                  'skipBlockEntityCulling': False,
                                  'blockEntityFrustumCulling': True,
                                  'tickCulling': True,
                                  'entityWhitelist': ['minecraft:beacon'],
                                  'sleepDelay': 125},
            'immediatelyfast.json': {'enhanced_batching': True, 'font_atlas_size': 2048},
        }
        for filename, value in self.original.items():
            (self.config / filename).write_text(json.dumps(value))

    def tearDown(self):
        self.temp.cleanup()

    def test_apply_restore_preserves_appearance_other_configs_and_originals(self):
        skin = self.config / 'cubeon-cosmetics.json'
        skin.write_text('{"back":"giant_wings"}')
        other = self.root / 'other-instance'
        other.mkdir()
        changed = compat.apply(self.game)
        self.assertEqual(set(changed), set(self.original))
        actual = json.loads((self.config / 'entityculling.json').read_text())
        self.assertTrue(actual['skipEntityCulling'])
        self.assertFalse(actual['tickCulling'])
        self.assertEqual(actual['entityWhitelist'], ['minecraft:beacon'])
        self.assertEqual(actual['sleepDelay'], 125)
        self.assertEqual(skin.read_text(), '{"back":"giant_wings"}')
        self.assertEqual(list(other.iterdir()), [])
        backup = (self.config / compat.BACKUP).read_bytes()
        self.assertEqual(compat.apply(self.game), [])
        self.assertEqual((self.config / compat.BACKUP).read_bytes(), backup)
        self.assertEqual(set(compat.apply(self.game, restore=True)), set(self.original))
        for filename, value in self.original.items():
            self.assertEqual(json.loads((self.config / filename).read_text()), value)
        self.assertFalse((self.config / compat.BACKUP).exists())

    def test_restore_preserves_subsequent_user_changes(self):
        compat.apply(self.game)
        path = self.config / 'immediatelyfast.json'
        data = json.loads(path.read_text())
        data['enhanced_batching'] = True
        data['font_atlas_size'] = 4096
        path.write_text(json.dumps(data))
        compat.apply(self.game, restore=True)
        self.assertEqual(json.loads(path.read_text()), data)

    def test_missing_and_older_mod_configs_are_not_seeded_or_extended(self):
        (self.config / 'entityculling.json').unlink()
        (self.config / 'immediatelyfast.json').write_text('{"font_atlas_size":1024}')
        self.assertEqual(compat.apply(self.game), [])
        self.assertFalse((self.config / compat.BACKUP).exists())
        self.assertEqual(json.loads((self.config / 'immediatelyfast.json').read_text()),
                         {'font_atlas_size': 1024})
        self.assertEqual(compat.apply(self.root / 'not-created'), [])
        self.assertFalse((self.root / 'not-created').exists())

    def test_invalid_second_config_cannot_partially_apply_first(self):
        before = (self.config / 'entityculling.json').read_bytes()
        (self.config / 'immediatelyfast.json').write_text('broken json')
        with self.assertRaises(ValueError):
            compat.apply(self.game)
        self.assertEqual((self.config / 'entityculling.json').read_bytes(), before)
        self.assertFalse((self.config / compat.BACKUP).exists())

    def test_stable_workaround_disabled_mods_are_not_reinstalled(self):
        from cubeon import perf_mods
        mods = [{'slug': slug, 'filename': slug + '.jar' +
                 ('.disabled' if slug in ('entityculling', 'immediatelyfast') else ''),
                 'enabled': slug not in ('entityculling', 'immediatelyfast')}
                for slug in perf_mods.PERF_MOD_SLUGS]
        with patch.object(perf_mods, 'list_mods', return_value=mods), \
                patch.object(perf_mods, 'get_mod_download') as download:
            result = perf_mods.ensure_installed('1.21.11', 'fabric', repair_dependencies=False)
        download.assert_not_called()
        self.assertIn('entityculling', result['kept'])
        self.assertIn('immediatelyfast', result['kept'])


if __name__ == '__main__':
    unittest.main()
