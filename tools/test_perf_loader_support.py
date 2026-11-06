"""FPS Boost across loaders, native port selection, opt-outs and legacy graphics."""
import ast
from contextlib import ExitStack
import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import atomicio, game_options, mods, net, perf_mods as perf


class LoaderBoost(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.calls = []
        self.downloads = []
        self.missing = set()
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        for obj, name, value in ((mods, 'PROFILES_DIR', str(self.root / 'profiles')),
                                 (mods, 'read_instance_meta', lambda vid: {'profile': vid} if vid else None),
                                 (perf, 'get_mod_download', self.lookup), (perf, 'download_mod', self.download)):
            self.context.enter_context(patch.object(obj, name, value))

    def lookup(self, slug, **kwargs):
        self.calls.append((slug, kwargs))
        if slug in self.missing:
            return None
        return {'url': 'https://cdn.modrinth.com/test.jar', 'filename': slug + '.jar',
                'hashes': {'sha256': 'fixture'}}

    def jar(self, directory, name, identity, loader):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        with zipfile.ZipFile(path, 'w') as archive:
            if loader in ('fabric', 'quilt'):
                archive.writestr('fabric.mod.json', json.dumps({'id': identity, 'version': '1.0'}))
            else:
                archive.writestr('META-INF/neoforge.mods.toml' if loader == 'neoforge' else 'META-INF/mods.toml',
                                f'modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="{identity}"\nversion="1.0"\n')
        return path

    def download(self, url, filename, **kwargs):
        self.downloads.append(kwargs)
        profile = Path(mods.get_profile_dir(kwargs['mc_version'], kwargs['loader'], kwargs['version_id']))
        self.jar(profile, filename, kwargs['slug'], kwargs['loader'])
        mods._write_meta(str(profile), filename, kwargs['slug'], project_id=kwargs['project_id'])

    def install(self, loader, instance=None):
        return perf.ensure_installed('1.20.1', loader, version_id=instance or loader,
                                     repair_dependencies=False)

    def test_all_loaders_receive_compatible_suite_and_quilt_uses_fabric_catalogue(self):
        for loader in ('fabric', 'quilt', 'forge', 'neoforge'):
            with self.subTest(loader=loader):
                self.calls.clear(); self.downloads.clear()
                result = self.install(loader)
                expected = ['embeddium', 'canary', *perf.PERF_MOD_SLUGS[2:]] if loader == 'forge' else list(perf.PERF_MOD_SLUGS)
                self.assertEqual(result['installed'], expected)
                self.assertEqual(result['failed'], [])
                self.assertTrue(all(call[1]['loader'] == ('fabric' if loader == 'quilt' else loader) for call in self.calls))
                self.assertTrue(all(call['loader'] == loader and call['version_id'] == loader
                                    and call['hashes'] == {'sha256': 'fixture'} for call in self.downloads))
                self.assertTrue(perf.is_installed('1.20.1', loader, loader))
                self.calls.clear()
                self.assertEqual(self.install(loader)['installed'], [])
                self.assertEqual(self.calls, [])

    def test_missing_native_builds_use_only_ports_for_that_loader(self):
        self.missing = {'sodium', 'lithium'}
        self.assertEqual(self.install('neoforge')['installed'][:2], ['embeddium', 'radium'])
        self.assertTrue(all(call[1]['loader'] == 'neoforge' for call in self.calls))
        self.calls.clear(); self.missing = {'canary'}
        self.assertEqual(self.install('forge')['installed'][:2], ['embeddium', 'radium'])
        self.assertTrue(all(call[1]['loader'] == 'forge' for call in self.calls))

    def test_requested_additions_and_optional_mods_obey_individual_selection(self):
        result = self.install('fabric')
        self.assertTrue({'modernfix', 'badoptimizations'} <= set(result['installed']))
        self.assertFalse({'moreculling', 'ebe', 'exordium'} & set(result['installed']))
        self.calls.clear()
        result = perf.ensure_installed('1.20.1', 'fabric', version_id='fabric',
                                      repair_dependencies=False, optional_mods=['ebe', 'untrusted-project'])
        self.assertEqual(result['installed'], ['ebe'])
        self.assertEqual([slug for slug, _ in self.calls], ['ebe'])
        self.assertEqual(perf.prune_retired_perf_mods('1.20.1', 'fabric', 'fabric'), [])
        self.assertIn('badoptimizations', perf._present('1.20.1', 'fabric', 'fabric'))

    def test_optional_removals_and_disabled_jars_are_never_undone(self):
        profile = Path(mods.get_profile_dir('1.20.1', 'fabric', 'fabric'))
        self.jar(profile, 'custom-name.jar', 'ebe', 'fabric')
        mods.delete_mod('1.20.1', 'fabric', 'custom-name.jar', version_id='fabric')
        self.jar(profile, 'exordium.jar.disabled', 'exordium', 'fabric')
        result = perf.ensure_installed('1.20.1', 'fabric', version_id='fabric',
                                      repair_dependencies=False, optional_mods=['ebe', 'exordium'])
        self.assertIn('ebe', result['skipped'])
        self.assertIn('exordium', result['kept'])
        self.assertFalse({'ebe', 'exordium'} & {slug for slug, _ in self.calls})

    def test_unavailable_is_distinct_from_a_failed_download(self):
        self.missing = {'modernfix', 'ebe', 'exordium'}
        result = perf.ensure_installed('26.3', 'fabric', version_id='fabric',
                                      repair_dependencies=False, optional_mods=['ebe', 'exordium'])
        self.assertEqual(set(result['unavailable']), self.missing)
        self.assertEqual(result['failed'], [])
        self.assertIn('no compatible build', result['detail'])

    def test_manual_or_disabled_renderer_and_logic_ports_prevent_competing_downloads(self):
        for renderer in ('embeddium', 'rubidium', 'optifine'):
            instance = renderer
            profile = Path(mods.get_profile_dir('1.20.1', 'neoforge', instance))
            self.jar(profile, 'renamed-renderer.jar.disabled', renderer, 'neoforge')
            self.jar(profile, 'renamed-logic.jar', 'radium', 'neoforge')
            result = self.install('neoforge', instance)
            self.assertIn(renderer, result['kept'])
            self.assertIn('radium', result['kept'])
            self.assertEqual(result['installed'], list(perf.PERF_MOD_SLUGS[2:]))

    def test_renderer_removal_does_not_install_a_different_port(self):
        profile = Path(mods.get_profile_dir('1.20.1', 'neoforge', 'neoforge'))
        self.jar(profile, 'embeddium.jar', 'embeddium', 'neoforge')
        mods.delete_mod('1.20.1', 'neoforge', 'embeddium.jar', version_id='neoforge')
        result = self.install('neoforge')
        self.assertIn('embeddium', result['skipped'])
        self.assertFalse(any(slug in ('sodium', 'embeddium') for slug, _ in self.calls))

    def test_legacy_optifine_archive_prevents_competing_renderer(self):
        profile = Path(mods.get_profile_dir('1.20.1', 'forge', 'forge'))
        with zipfile.ZipFile(profile / 'OptiFine_1.20.1_HD_U_I6.jar', 'w') as archive:
            archive.writestr('optifine/OptiFineTweaker.class', b'fixture')
        result = self.install('forge')
        self.assertIn('optifine', result['kept'])
        self.assertNotIn('embeddium', result['installed'])

    def test_connection_failure_stops_remaining_jobs_and_fallbacks(self):
        with patch.object(perf, 'get_mod_download', side_effect=net.DownloadError('offline')) as fetch:
            result = self.install('neoforge')
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(result['failed']), len(perf.PERF_MODS))
        self.assertEqual(self.downloads, [])

    def launch_boost(self, loader, cfg):
        # Execute the actual launch preparation block with real files/ports;
        # omit Java spawning, skin services and unrelated prelaunch repairs.
        source = Path(perf.__file__).with_name('launch.py').read_text()
        function = next(node for node in ast.parse(source).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'launch_game')
        block = next(node for node in function.body if isinstance(node, ast.If)
                     and 'sync_fps_boost' in ast.unparse(node))
        game = self.root / ('game-' + loader)
        game.mkdir(exist_ok=True)
        options = game / 'options.txt'
        if not options.exists():
            options.write_text('graphicsMode:1\nparticles:0\nao:true\nrenderDistance:18\nmaxFps:144\nenableVsync:true\n')
        with patch.object(perf, 'prune_retired_perf_mods', return_value=[]):
            exec(compile(ast.Module(body=[block], type_ignores=[]), 'launch.py', 'exec'),
                 {'__package__': 'cubeon', 'cfg': cfg, 'mc_version': '1.20.1',
                  'loader': loader, 'version_id': loader, 'game_dir': str(game),
                  'status_cb': None, 'logging': logging, '__name__': 'cubeon.launch'})
        return options

    def test_actual_launch_applies_boost_even_with_client_disabled_for_all_loaders(self):
        for loader in ('fabric', 'quilt', 'forge', 'neoforge'):
            with self.subTest(loader=loader):
                options = self.launch_boost(loader, {'client_mod_enabled': False, 'fps_boost_enabled': True})
                text = options.read_text()
                self.assertIn('graphicsMode:0', text)
                self.assertIn('particles:2', text)
                self.assertIn('renderDistance:18', text)
                self.assertIn('enableVsync:true', text)
                self.assertIn('maxFps:144', text)
                renderer = 'embeddium' if loader == 'forge' else 'sodium'
                config = json.loads((options.parent / 'config' / (renderer + '-options.json')).read_text())
                self.assertEqual(config, {'performance': {'chunk_builder_threads': 2}})
                self.calls.clear()
                self.launch_boost(loader, {'client_mod_enabled': False, 'fps_boost_enabled': False})
                self.assertIn('graphicsMode:1', options.read_text())
                self.assertEqual(self.calls, [])

    def test_unavailable_ports_or_disabled_downloads_do_not_block_graphics(self):
        self.missing = {entry[0] for entry in perf._KNOWN_PERF_MODS}
        for loader in ('forge', 'neoforge'):
            options = self.launch_boost(loader, {'client_mod_enabled': False, 'fps_boost_enabled': True})
            self.assertIn('graphicsMode:0', options.read_text())
        self.calls.clear()
        options = self.launch_boost('quilt', {'client_mod_enabled': False, 'fps_boost_enabled': True,
                                              'perf_mods_enabled': False})
        self.assertIn('graphicsMode:0', options.read_text())
        self.assertEqual(self.calls, [])

    def test_actual_launch_syncs_even_without_mod_downloads(self):
        cfg = {'fps_boost_enabled': True, 'fps_boost_sync_settings': True, 'perf_mods_enabled': False}
        options = self.launch_boost('fabric', cfg)
        self.assertIn('renderDistance:4', options.read_text())
        self.assertIn('enableVsync:false', options.read_text())
        options.write_text(options.read_text().replace('maxFps:260', 'maxFps:60'))
        self.launch_boost('fabric', cfg)
        self.assertIn('maxFps:260', options.read_text())
        self.assertEqual(self.calls, [])

    def test_launch_syncs_and_restores_existing_renderer_with_downloads_disabled(self):
        profile = Path(mods.get_profile_dir('1.20.1', 'fabric', 'fabric'))
        self.jar(profile, 'sodium.jar', 'sodium', 'fabric')
        cfg = {'fps_boost_enabled': True, 'fps_boost_sync_settings': True, 'perf_mods_enabled': False}
        options = self.launch_boost('fabric', cfg)
        renderer = options.parent / 'config/sodium-options.json'
        self.assertEqual(json.loads(renderer.read_text())['performance']['chunk_builder_threads'], 2)
        renderer.write_text(json.dumps({'performance': {'chunk_builder_threads': 2, 'use_fog_occlusion': False}}))
        self.launch_boost('fabric', cfg)
        self.assertTrue(json.loads(renderer.read_text())['performance']['use_fog_occlusion'])
        self.launch_boost('fabric', dict(cfg, fps_boost_enabled=False))
        self.assertFalse(json.loads(renderer.read_text())['performance']['use_fog_occlusion'])
        self.assertEqual(self.calls, [])

    def test_legacy_graphics_encoding_and_prior_backup_upgrade_preserve_user_edits(self):
        path = self.root / 'legacy-options.txt'
        original = 'fancyGraphics:true\nao:2\nrenderClouds:true\nparticles:0\nrenderDistance:18\n'
        path.write_text(original)
        self.assertTrue(game_options.sync_fps_boost(True, str(path))['changed'])
        self.assertIn('fancyGraphics:false', path.read_text())
        self.assertIn('ao:0', path.read_text())
        self.assertIn('renderClouds:fast', path.read_text())
        self.assertEqual(game_options.sync_fps_boost(True, str(path))['changed'], [])
        game_options.sync_fps_boost(False, str(path))
        self.assertEqual(path.read_text(), original)
        path.write_text('graphicsMode:1\nparticles:0\nrenderDistance:22\n')
        atomicio.write_json(str(path) + '.cubeon-boost.json', {'schema': 1, 'enabled': True,
                             'before': {'particles': '1'}, 'applied': {'particles': '2'}})
        self.assertEqual(game_options.sync_fps_boost(True, str(path))['changed'], ['graphicsMode'])
        self.assertIn('particles:0', path.read_text())
        game_options.sync_fps_boost(False, str(path))
        self.assertIn('graphicsMode:1', path.read_text())
        self.assertIn('particles:0', path.read_text())


if __name__ == '__main__':
    unittest.main()
