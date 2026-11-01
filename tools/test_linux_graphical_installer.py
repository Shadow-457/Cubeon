"""Offline graphical setup installs the same payload and preserves launch mode."""
import asyncio
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import installer_ui, thread_safe_ui

spec = importlib.util.spec_from_file_location('linux_builders', ROOT / 'packaging/build_linux_installers.py')
builders = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builders)


class GraphicalInstaller(unittest.TestCase):
    def test_offline_install_and_launch_with_quoted_path_keeps_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'setup.AppImage'
            source.write_text('#!/bin/sh\nprintf "%s\\n" "$CUBEON_LAUNCH_INSTALLED" > "$CUBEON_TEST_MARKER"\n')
            target = folder / 'Games $cash "quotes" %sign'
            marker = folder / 'started'
            with patch.dict(os.environ, {'XDG_DATA_HOME': str(folder / 'data'), 'CUBEON_TEST_MARKER': str(marker)}):
                launcher = installer_ui.install(source, target, root=ROOT)
                subprocess.run([str(launcher)], check=True, timeout=5)
                self.assertEqual(marker.read_text(), '1\n')
                (target / 'worlds.keep').write_text('user data')
                (target / 'Cubeon.AppImage').write_bytes(b'old image')
                installer_ui.install(source, target, root=ROOT)
                self.assertEqual((target / 'Cubeon.AppImage.cubeon-previous').read_bytes(), b'old image')
                self.assertEqual((target / 'worlds.keep').read_text(), 'user data')
                self.assertEqual((target / 'Cubeon.AppImage').read_bytes(), source.read_bytes())
                self.assertTrue((folder / 'data/applications/cubeon.desktop').is_file())

    def test_bad_paths_incomplete_setup_and_low_space_leave_install_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'setup.AppImage'
            source.write_bytes(b'setup')
            for destination in ['relative/path', str(folder / 'bad\npath')]:
                with self.assertRaisesRegex(ValueError, 'full folder'):
                    installer_ui.install(source, destination, root=ROOT)
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                installer_ui.install(source, folder / 'install', root=folder)
            with patch('cubeon.installer_ui.shutil.disk_usage', return_value=types.SimpleNamespace(free=0)):
                with self.assertRaisesRegex(ValueError, 'Free at least'):
                    installer_ui.install(source, folder / 'install', root=ROOT)
            self.assertFalse((folder / 'install').exists())

    def test_install_work_does_not_hold_ui_lock_and_close_is_blocked(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        page = Mock()
        setup = installer_ui.LinuxSetup(page, '/tmp/setup.AppImage')
        setup.open_after.value = False
        def install(*args, **kwargs):
            entered.set()
            release.wait(3)
            return Path('/tmp/cubeon')
        def worker():
            setup._install('/tmp/install')
            finished.set()
        with patch.object(installer_ui, 'install', side_effect=install), \
                patch.object(thread_safe_ui, 'refresh'):
            setup.busy = True
            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(entered.wait(2))
            try:
                self.assertTrue(thread_safe_ui.TREE_LOCK.acquire(timeout=0.5))
                thread_safe_ui.TREE_LOCK.release()
                setup.finish()
                page.run_task.assert_not_called()
            finally:
                release.set()
                thread.join(3)
            self.assertTrue(finished.is_set())
            self.assertFalse(setup.busy)
            self.assertEqual(setup.primary.content, 'Open Cubeon')

    def test_graphical_image_build_preserves_appdir_and_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            appdir = folder / 'AppDir'
            (appdir / 'usr/bin').mkdir(parents=True)
            original = '#!/bin/sh\necho original\n'
            (appdir / 'AppRun').write_text(original)
            (appdir / 'cubeon.desktop').write_text('original desktop')
            program = appdir / 'usr/bin/Cubeon'
            program.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$CUBEON_TEST_MARKER"\n')
            program.chmod(0o755)
            tool = folder / 'appimagetool'
            # Inspect the exact staged tree through a real executable tool.
            tool.write_text('#!/bin/sh\ncp -a "$1" "$2"\n')
            tool.chmod(0o755)
            stage = folder / 'Setup.AppDir'
            builders.build_graphical_setup(appdir, tool, stage)
            self.assertEqual((appdir / 'AppRun').read_text(), original)
            self.assertEqual((appdir / 'cubeon.desktop').read_text(), 'original desktop')
            marker = folder / 'mode'
            env = dict(os.environ, CUBEON_TEST_MARKER=str(marker))
            env.pop('CUBEON_LAUNCH_INSTALLED', None)
            subprocess.run([str(stage / 'AppRun')], env=env, check=True, timeout=5)
            self.assertEqual(marker.read_text(), '--cubeon-installer\n')
            env['CUBEON_LAUNCH_INSTALLED'] = '1'
            subprocess.run([str(stage / 'AppRun'), 'argument'], env=env, check=True, timeout=5)
            self.assertEqual(marker.read_text(), 'argument\n')

    def test_done_destroys_native_window_once_after_install_gate(self):
        page = Mock()
        page.window.destroy = AsyncMock()
        page.window.prevent_close = True
        setup = installer_ui.LinuxSetup(page, '/tmp/setup.AppImage')
        asyncio.run(setup._close())
        asyncio.run(setup._close())
        page.window.destroy.assert_awaited_once()
        self.assertTrue(setup.closing)

    def test_open_installed_launcher_resets_bundled_runtime_environment(self):
        with patch.dict(os.environ, {'APPIMAGE': '/mounted/setup', 'APPDIR': '/tmp/mount',
                                     'CUBEON_APPIMAGE_PATH': '/setup'}), \
                patch.object(installer_ui.subprocess, 'Popen') as launch:
            installer_ui.open_launcher(Path('/installed/cubeon'))
        env = launch.call_args.kwargs['env']
        self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertFalse({'APPIMAGE', 'APPDIR', 'CUBEON_APPIMAGE_PATH'} & set(env))


if __name__ == '__main__':
    unittest.main()
