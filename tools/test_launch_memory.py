"""Heap precedence through real mll profile assembly and live Settings edits."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from cubeon import config, launch, theme
from ui.settings_tab import _java_defaults_panel


class LaunchMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name, value in [('MINECRAFT_DIR', str(self.root)),
                            ('stable_uuid', lambda: 'test-uuid'),
                            ('find_java_for_version', lambda *args: None)]:
            patcher = patch.object(launch, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def profile(self, version, jvm, *, parent=None):
        folder = self.root / 'versions' / version
        folder.mkdir(parents=True)
        data = {'id': version, 'type': 'release', 'libraries': [],
                'mainClass': 'game.Main', 'assets': 'test',
                'assetIndex': {'id': 'test'},
                'arguments': {'jvm': jvm,
                              'game': ['--gameDir', '${game_directory}',
                                       '--server', '-Xmx2G']}}
        if parent:
            data['inheritsFrom'] = parent
            data['arguments']['game'] = []
        path = folder / (version + '.json')
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def command(self, custom='', enabled=True):
        return launch.build_launch_command(
            'pack', 'Alex', 5120, 854, 480, custom_jvm_flags=custom,
            default_jvm_flags_enabled=enabled, game_dir=str(self.root / 'my-world'))

    def test_inherited_profile_cannot_reduce_selected_five_gb(self):
        base = self.profile('base', ['-Xmx2G', '-Xms2G', '-Dpack.setting=true',
                                     '-cp', '${classpath}'])
        pack = self.profile('pack', ['-XX:MaxHeapSize=2147483648',
                                     '-XX:InitialHeapSize=2G'], parent='base')
        originals = [path.read_bytes() for path in (base, pack)]
        argv = self.command()
        jvm = argv[1:argv.index('game.Main')]
        self.assertEqual([arg for arg in jvm if arg.startswith(('-Xmx', '-Xms',
                         '-XX:MaxHeapSize=', '-XX:InitialHeapSize='))],
                         ['-Xmx5120M', '-Xms512M'])
        self.assertIn('-Dpack.setting=true', jvm)
        self.assertIn('-cp', jvm)
        self.assertEqual(argv[argv.index('game.Main') + 1:],
                         ['--gameDir', str(self.root / 'my-world'), '--server', '-Xmx2G'])
        self.assertEqual([path.read_bytes() for path in (base, pack)], originals)

    def test_last_explicit_custom_heap_wins_over_profile_and_slider(self):
        self.profile('pack', ['-Xmx2G', '-Xms2G', '-cp', '${classpath}'])
        custom = '-Xmx6G -XX:MaxHeapSize=3G -Xms1G -XX:InitialHeapSize=768M'
        argv = self.command(custom)
        jvm = argv[1:argv.index('game.Main')]
        heap = [arg for arg in jvm if arg.startswith(('-Xmx', '-Xms', '-XX:MaxHeapSize=',
                                                    '-XX:InitialHeapSize='))]
        self.assertEqual(heap, ['-XX:MaxHeapSize=3G', '-XX:InitialHeapSize=768M'])
        report = launch.memory_limit_report(5120, custom_jvm_flags=custom)
        self.assertEqual(report, {'source': 'custom', 'flag': '-XX:MaxHeapSize=3G', 'ram_mb': 3072})
        default_rows = launch.default_jvm_flags_report(5120, custom_jvm_flags=custom)
        self.assertTrue(all(row['source'] == 'dropped' for row in default_rows
                            if row['flag'].startswith(('-Xmx', '-Xms'))))

    def test_explicit_initial_heap_keeps_slider_maximum(self):
        self.profile('pack', ['-Xmx2G', '-Xms2G', '-cp', '${classpath}'])
        argv = self.command('-Xms1G')
        self.assertIn('-Xmx5120M', argv)
        self.assertIn('-Xms1G', argv)
        self.assertNotIn('-Xms2G', argv)
        self.assertNotIn('-Xms512M', argv)

    def test_small_custom_ceiling_does_not_get_larger_default_initial_heap(self):
        self.profile('pack', ['-Xmx2G', '-Xms2G', '-cp', '${classpath}'])
        argv = self.command('-Xmx128M')
        self.assertIn('-Xmx128M', argv)
        self.assertIn('-Xms128M', argv)
        self.assertNotIn('-Xms512M', argv)

    def test_opt_out_preserves_profile_memory_and_custom_overrides(self):
        self.profile('pack', ['-Xmx2G', '-Xms1G', '-cp', '${classpath}'])
        argv = self.command(enabled=False)
        self.assertIn('-Xmx2G', argv)
        self.assertIn('-Xms1G', argv)
        self.assertNotIn('-Xmx5120M', argv)
        argv = self.command('-XX:MaxHeapSize=3G', enabled=False)
        jvm = argv[1:argv.index('game.Main')]
        self.assertNotIn('-Xmx2G', jvm)
        self.assertIn('-XX:MaxHeapSize=3G', jvm)
        self.assertIn('-Xms1G', jvm)
        self.assertEqual(launch.memory_limit_report(5120, default_jvm_flags_enabled=False)['source'],
                         'profile')

    def test_heap_like_classpath_and_module_values_are_preserved(self):
        self.profile('pack', ['-cp', '-Xmx9G', '--patch-module', '-Xms8G', '-Xmx2G'])
        argv = self.command('--add-opens "-Xmx7G"')
        self.assertEqual(argv[argv.index('-cp') + 1], '-Xmx9G')
        self.assertEqual(argv[argv.index('--patch-module') + 1], '-Xms8G')
        self.assertEqual(argv[argv.index('--add-opens') + 1], '-Xmx7G')
        self.assertEqual(launch.memory_limit_report(5120,
                         custom_jvm_flags='--add-opens "-Xmx7G"')['source'], 'slider')

    def test_legacy_profile_gets_selected_ceiling(self):
        path = self.profile('pack', [])
        data = json.loads(path.read_text())
        del data['arguments']
        data['minecraftArguments'] = '--username ${auth_player_name}'
        path.write_text(json.dumps(data))
        argv = self.command()
        self.assertIn('-Xmx5120M', argv)
        self.assertEqual(argv[argv.index('--username') + 1], 'Alex')
        self.assertEqual(argv[argv.index('--width') + 1], '854')
        self.assertEqual(argv[argv.index('--height') + 1], '480')

    def test_collapsed_settings_tracks_limit_and_disabled_defaults(self):
        status = ft.Text('')
        slider = ft.Slider(value=5120)
        custom = ft.TextField(value='')
        panel = _java_defaults_panel(ram_slider=slider, custom_jvm_field=custom,
            memory_status=status, cfg={},
            **{key: getattr(theme, key) for key in
               ('BORDER', 'ACCENT', 'ACCENT_TINT', 'TEXT', 'TEXT_DIM', 'TEXT_FAINT', 'FONT_MONO')})
        toggle, header, rows = panel.content.controls
        self.assertFalse(rows.visible)
        self.assertIn('5 GB', status.value)
        slider.value = 6144
        slider.on_change(None)
        self.assertIn('6 GB', status.value)
        custom.value = '-Xmx2G'
        custom.on_change(None)
        self.assertIn('overrides the RAM slider', status.value)
        self.assertIn('-Xmx2G', status.value)
        custom.value = ''
        custom.on_change(None)
        switch = toggle.content.controls[1]
        switch.value = False
        with patch.object(config, 'save_config'):
            switch.on_change(None)
        self.assertTrue(slider.disabled)
        self.assertIn('profile or Java', status.value)
        switch.value = True
        with patch.object(config, 'save_config', side_effect=OSError('full disk')):
            switch.on_change(None)
        self.assertTrue(slider.disabled)
        self.assertIn('profile or Java', status.value)


if __name__ == '__main__':
    unittest.main()
