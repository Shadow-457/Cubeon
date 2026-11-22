"""Native game processes must not inherit frozen Python's library directory."""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
TEST_HOME = Path(_sandbox_home.isolate())
from cubeon import content, content_checks, doctor, launch, milestones, mod_dependencies, rust_engine, storage, watchdog
from cubeon.friends_service import FriendsService

CHILD = "import json,os; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith(('LD_LIBRARY','CUBEON_','HORIZON_','LIBGL_','GALLIUM_','GDK_'))}))"


class GameEnvironmentTests(unittest.TestCase):
    def spawn(self, supplied=None, *, command=None, stage_java=False, raw=False):
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
            if stage_java:
                for owner, name, result in ((doctor, 'run_doctor', {'fixed': []}),
                        (mod_dependencies, 'run_dependency_doctor', {'unfixed': []}),
                        (content_checks, 'consume_run_once', False),
                        (content_checks, 'remember_runtime', None),
                        (content, 'sync_content_to_game', None),
                        (launch, 'sync_mods_to_game', None), (storage, 'game_dir', None)):
                    stack.enter_context(patch.object(owner, name, return_value=result))
            original = list(command) if command else None
            process = launch._spawn_game(command or [sys.executable, '-c', CHILD], str(work),
                'probe', 'Tester', '26.3', 'fabric', stage_java=stage_java, game_env=supplied,
                on_exit=lambda code, lines, session_id=None: (output.extend(lines), done.set()))
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertTrue(done.wait(10), 'Game exit callback did not complete')
            if command:
                self.assertEqual(command, original, 'Spawn must not mutate the verified command')
                self.assertEqual(process.args, launch._game_spawn_command(original, stage_java))
        if raw:
            return output
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


    @unittest.skipUnless(os.name == 'nt', 'Native Windows javaw logging probe')
    def test_windows_javaw_preserves_arguments_stdout_stderr_and_exit_callback(self):
        java = launch.find_java()
        self.assertTrue(java, 'Windows CI must install Java for the native javaw probe')
        self.assertGreaterEqual(launch.java_major_version(java), 11)
        source = TEST_HOME / 'CubeonJavawProbe.java'
        source.write_text('class CubeonJavawProbe { public static void main(String[] args) { '
                          'System.out.println("stdout:" + args[0]); '
                          'System.err.println("stderr:" + args[1]); } }')
        command = [java, str(source), 'argument with spaces', 'second argument']
        selected = launch._game_spawn_command(command)
        self.assertEqual(os.path.basename(selected[0]).lower(), 'javaw.exe')
        self.assertEqual(self.spawn(command=command, stage_java=True, raw=True),
                         ['stdout:argument with spaces', 'stderr:second argument'])


class WindowlessJavaSelectionTests(unittest.TestCase):
    def test_same_runtime_arguments_and_original_command_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            java = os.path.join(directory, 'jdk with spaces', 'bin', 'java.exe')
            javaw = os.path.join(os.path.dirname(java), 'javaw.exe')
            os.makedirs(os.path.dirname(java))
            Path(java).touch()
            Path(javaw).touch()
            command = [java, '-Xmx2048M', '-cp', 'path with spaces', 'Main', '--username', 'Tester']
            with patch.object(os, 'name', 'nt'):
                self.assertEqual(launch._game_spawn_command(command), [javaw, *command[1:]])
                self.assertIs(launch._game_spawn_command(command, stage_java=False), command)
            self.assertEqual(command[0], java)
            with patch.object(os, 'name', 'posix'):
                self.assertIs(launch._game_spawn_command(command), command)
            Path(javaw).unlink()
            with patch.object(os, 'name', 'nt'):
                self.assertIs(launch._game_spawn_command(command), command)

    def test_wrappers_native_programs_and_existing_javaw_are_preserved(self):
        with patch.object(os, 'name', 'nt'):
            for executable in ('custom-java.cmd', 'cubeon-rust.exe', 'javaw.exe'):
                command = [executable, 'argument']
                self.assertIs(launch._game_spawn_command(command), command)
            self.assertEqual(launch._game_spawn_command([]), [])

    def test_java_on_path_uses_the_selected_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            java = os.path.join(directory, 'java.exe')
            javaw = os.path.join(directory, 'javaw.exe')
            Path(java).touch()
            Path(javaw).touch()
            with patch.object(os, 'name', 'nt'), patch.object(launch.shutil, 'which', return_value=java):
                self.assertEqual(launch._game_spawn_command(['java', '-Xmx1024M']), [javaw, '-Xmx1024M'])


if __name__ == '__main__':
    unittest.main()
