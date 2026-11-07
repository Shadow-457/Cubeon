"""Native game processes must not inherit frozen Python's library directory."""
import contextlib
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
TEST_HOME = Path(_sandbox_home.isolate())
from cubeon import launch, milestones, rust_engine, watchdog
from cubeon.friends_service import FriendsService

CHILD = "import json,os; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith(('LD_LIBRARY','CUBEON_','HORIZON_','LIBGL_','GALLIUM_','GDK_'))}))"


class GameEnvironmentTests(unittest.TestCase):
    def spawn(self, supplied=None):
        done = threading.Event()
        output = []
        work = TEST_HOME / 'game'
        work.mkdir(exist_ok=True)
        with contextlib.ExitStack() as stack:
            for owner, name in ((watchdog, 'register'), (watchdog, 'clear'),
                                (milestones, 'begin_play_session'), (milestones, 'end_play_session'),
                                (FriendsService, 'reconcile_username_active')):
                stack.enter_context(patch.object(owner, name, return_value=None))
            stack.enter_context(patch.object(watchdog, 'stale_session', return_value=None))
            process = launch._spawn_game([sys.executable, '-c', CHILD], str(work),
                'probe', 'Tester', '26.3', 'fabric', stage_java=False, game_env=supplied,
                on_exit=lambda code, lines, session_id=None: (output.extend(lines), done.set()))
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertTrue(done.wait(10), 'Game exit callback did not complete')
        self.assertEqual(len(output), 1, output)
        return json.loads(output[0])

    def test_frozen_linux_java_restores_original_and_keeps_parent_unchanged(self):
        chosen = {'LD_LIBRARY_PATH': '/bundle/_internal:/user/lib',
                  'LD_LIBRARY_PATH_ORIG': '/user/lib', 'GDK_BACKEND': 'x11',
                  'LIBGL_ALWAYS_SOFTWARE': '1', 'GALLIUM_DRIVER': 'llvmpipe',
                  'CUBEON_GPU_RESTARTS': '2', 'CUBEON_USER_RENDERING': '0'}
        with patch.dict(os.environ, chosen), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'linux'):
            env = self.spawn()
            self.assertEqual(env['LD_LIBRARY_PATH'], '/user/lib')
            self.assertEqual(env['GDK_BACKEND'], 'x11')
            for key in ('LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', 'CUBEON_GPU_RESTARTS', 'CUBEON_USER_RENDERING'):
                self.assertNotIn(key, env)
            self.assertEqual(os.environ['LD_LIBRARY_PATH'], chosen['LD_LIBRARY_PATH'])

    def test_frozen_linux_removes_path_without_original(self):
        with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/bundle/_internal'}), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'linux'):
            os.environ.pop('LD_LIBRARY_PATH_ORIG', None)
            self.assertNotIn('LD_LIBRARY_PATH', self.spawn())

    def test_explicit_native_game_environment_is_isolated_without_mutation(self):
        supplied = {**os.environ, 'LD_LIBRARY_PATH': '/bundle/_internal',
                    'LD_LIBRARY_PATH_ORIG': '', 'CUBEON_RUST_PLAYER_NAME': 'Tester'}
        before = supplied.copy()
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'linux'):
            env = self.spawn(supplied)
        self.assertEqual(env['LD_LIBRARY_PATH'], '')
        self.assertEqual(env['CUBEON_RUST_PLAYER_NAME'], 'Tester')
        self.assertEqual(supplied, before)

    def test_source_keeps_user_library_path(self):
        with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/user/lib'}), patch.object(sys, 'frozen', False, create=True), patch.object(sys, 'platform', 'linux'):
            self.assertEqual(self.spawn()['LD_LIBRARY_PATH'], '/user/lib')

    def test_non_linux_frozen_keeps_library_path(self):
        with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/user/lib'}), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'win32'):
            self.assertEqual(self.spawn()['LD_LIBRARY_PATH'], '/user/lib')

    def test_rust_preparer_restores_path_and_strips_internal_flags(self):
        chosen = {'LD_LIBRARY_PATH': '/bundle/_internal', 'LD_LIBRARY_PATH_ORIG': '/user/lib',
                  'HORIZON_SESSION': 'fixture', 'CUBEON_USER_RENDERING': '0',
                  'LIBGL_ALWAYS_SOFTWARE': '1'}
        with patch.dict(os.environ, chosen), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'linux'):
            env = rust_engine.child_environment()
            self.assertEqual(env['LD_LIBRARY_PATH'], '/user/lib')
            for key in ('HORIZON_SESSION', 'CUBEON_USER_RENDERING', 'LIBGL_ALWAYS_SOFTWARE'):
                self.assertNotIn(key, env)
            self.assertEqual(os.environ['LD_LIBRARY_PATH'], '/bundle/_internal')


if __name__ == '__main__':
    unittest.main()
