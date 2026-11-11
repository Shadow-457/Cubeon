"""Real Flet sessions with crashing clients and actual interpreter re-execs.

No desktop or remote requests: the fake client dies before connecting. The
fixture is reapplied in each replacement, and all state is sandboxed.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'POSIX signal/exec recovery')
class StartupRecoveryTests(unittest.TestCase):
    def run_scenario(self, scenario, overrides=None, stale_fallback=False, frozen_libraries=False):
        with tempfile.TemporaryDirectory(prefix='cubeon-recovery-') as temp:
            home = Path(temp) / 'home'
            home.mkdir()
            if stale_fallback:
                (home / 'use_software_gl').touch()
            driver = Path(temp) / 'driver.py'
            client = Path(temp) / 'client.py'
            record = Path(temp) / 'attempts.jsonl'
            client.write_text(textwrap.dedent(f'''
                import json, os, signal, sys
                from pathlib import Path
                attempt = int(os.environ.get('CUBEON_GPU_RESTARTS', '0'))
                with open({str(record)!r}, 'a') as out:
                    out.write(json.dumps(dict(pid=os.getppid(), attempt=attempt,
                        interpreter=os.environ['CUBEON_RECOVERY_TEST_INSTANCE'],
                        software=os.environ.get('LIBGL_ALWAYS_SOFTWARE'),
                        driver=os.environ.get('GALLIUM_DRIVER'),
                        backend=os.environ.get('GDK_BACKEND'),
                        library_path=os.environ.get('LD_LIBRARY_PATH'),
                        rendering=os.environ.get('CUBEON_USER_RENDERING'))) + '\\n')
                if {scenario!r} == 'mixed' and attempt == 1:
                    Path({str(home / 'ui_painted_ok')!r}).touch()
                if {scenario!r} == 'clean-after-retry' and attempt == 1:
                    sys.exit(0)
                print('Timed out waiting for OpenGL frame of size 1362x824 (have 1x1)',
                      file=sys.stderr, flush=True)
                os.kill(os.getpid(), signal.SIGTERM)
            '''))
            driver.write_text(textwrap.dedent(f'''
                import os, sys, runpy, uuid
                from pathlib import Path
                sys.path.insert(0, {str(ROOT)!r})
                os.environ['CUBEON_RECOVERY_TEST_INSTANCE'] = uuid.uuid4().hex
                Path.home = classmethod(lambda cls: cls({str(home)!r}))
                real_expanduser = os.path.expanduser
                def expanduser(value):
                    value = os.fsdecode(value)
                    return ({str(home)!r} + value[1:]
                            if value == '~' or value.startswith('~/') else real_expanduser(value))
                os.path.expanduser = expanduser
                sys._MEIPASS = {temp!r}
                os.makedirs(os.path.join(sys._MEIPASS, 'assets'), exist_ok=True)
                import cubeon.paths as paths
                paths.CUBEON_HOME = {str(home)!r}
                paths.CONFIG_PATH = {str(home / 'config.json')!r}
                paths.CACHE_DIR = {str(home / 'cache')!r}
                import flet as ft, flet_desktop as fd
                if {frozen_libraries!r}:
                    sys.frozen = True
                    os.environ['LD_LIBRARY_PATH'] = '/cubeon-test-bundle/_internal'
                    os.environ['LD_LIBRARY_PATH_ORIG'] = '/cubeon-test-host/lib'
                    # The fake locator never unpacks a client, but configure()
                    # must still find the bundled archive before the real run.
                    archive = Path(sys._MEIPASS) / 'assets' / 'flet-linux-ubuntu22.04-x64.tar.gz'
                    archive.touch()
                    fd.get_package_bin_dir = lambda: str(archive.parent)
                    fd.get_artifact_filename = lambda: archive.name
                fd.__locate_and_unpack_flet_view = lambda *args: (
                    [sys.executable, '-u', {str(client)!r}], os.environ.copy(),
                    {str(home / 'client.pid')!r})
                real_run = ft.run
                calls = 0
                def once(*args, **kwargs):
                    global calls
                    calls += 1
                    assert calls == 1, 'ft.run reused in the same process'
                    return real_run(*args, **kwargs)
                ft.run = once
                real_execve = os.execve
                def fixture_execve(executable, argv, env):
                    return real_execve(executable, [executable, {str(driver)!r}], env)
                os.execve = fixture_execve
                sys.argv = ['main.py', '--color=green']
                runpy.run_path({str(ROOT / 'main.py')!r}, run_name='__main__')
            '''))
            env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home),
                   'CUBEON_GAME_DIR': str(Path(temp) / 'game'), 'PYTHONUNBUFFERED': '1'}
            for key in ('CUBEON_GPU_RESTARTS', 'LIBGL_ALWAYS_SOFTWARE',
                        'GALLIUM_DRIVER', 'CUBEON_SOURCE_RUNTIME_REEXEC',
                        'CUBEON_USER_RENDERING', 'GDK_BACKEND', 'GDK_GL',
                        'EGL_PLATFORM', 'LIBGL_DRM_DEVICE', 'MESA_LOADER_DRIVER_OVERRIDE'):
                env.pop(key, None)
            env['XDG_SESSION_TYPE'] = 'x11'
            # Select Flet's desktop path even on a headless runner. The mocked
            # client never connects to X11; a web server would bypass it.
            env['DISPLAY'] = ':cubeon-recovery-fixture'
            env.pop('FLET_FORCE_WEB_SERVER', None)
            env.update(overrides or {})
            proc = subprocess.Popen([sys.executable, str(driver)], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True)
            try:
                output = proc.communicate(timeout=45)[0]
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                output = proc.communicate()[0]
                self.fail('Recovery hung: ' + output[-2500:])
            self.assertEqual(proc.returncode, 0, output[-2500:])
            attempts = [json.loads(line) for line in record.read_text().splitlines()]
            self.assertEqual(len({a['interpreter'] for a in attempts}), len(attempts), output)
            self.assertNotIn('ft.run reused', output)
            if frozen_libraries:
                self.assertTrue(all(a['library_path'] == '/cubeon-test-host/lib' for a in attempts), output)
            if overrides:
                for attempt in attempts:
                    self.assertEqual(attempt['software'], overrides.get('LIBGL_ALWAYS_SOFTWARE'))
                    self.assertEqual(attempt['driver'], overrides.get('GALLIUM_DRIVER'))
                    self.assertEqual(attempt['backend'], overrides.get('GDK_BACKEND'))
                    self.assertEqual(attempt['rendering'], '1')
                self.assertNotIn('retrying with', output)
            else:
                self.assertIsNone(attempts[0]['software'])
                self.assertEqual(attempts[1]['software'], '1')
                self.assertEqual(attempts[1]['driver'], 'llvmpipe')
                if len(attempts) == 3:
                    self.assertEqual(attempts[2]['driver'], 'softpipe')
            self.assertEqual(attempts[-1]['attempt'], len(attempts) - 1)
            if scenario == 'clean-after-retry':
                self.assertEqual(len(attempts), 2, output)
                self.assertFalse((home / 'use_software_gl').exists())
                self.assertNotIn('giving up', output)
                self.assertIn('kind=clean_close', (home / '.cubeon_launcher/cubeon.log').read_text())
            else:
                self.assertEqual(len(attempts), 3, output)
                self.assertIn('giving up', output)
            return output

    def test_pre_paint_crashes_restart_once_per_process_and_stop(self):
        output = self.run_scenario('pre-paint')
        self.assertEqual(output.count('kind=pre_paint_crash'), 3)

    def test_mixed_crashes_share_the_restart_budget(self):
        output = self.run_scenario('mixed')
        self.assertEqual(output.count('kind=pre_paint_crash'), 2)
        self.assertEqual(output.count('kind=mid_session_crash'), 1)

    def test_clean_close_after_recovery_does_not_reopen(self):
        self.assertIn('hardware OpenGL re-enabled', self.run_scenario('clean-after-retry'))

    def test_explicit_x11_survives_stale_marker_and_all_reexecs(self):
        self.run_scenario('pre-paint', {'GDK_BACKEND': 'x11'}, stale_fallback=True)

    def test_explicit_renderer_survives_all_reexecs(self):
        self.run_scenario('pre-paint', {'LIBGL_ALWAYS_SOFTWARE': '0', 'GALLIUM_DRIVER': 'zink'})

    def test_frozen_client_restores_host_libraries_on_every_restart(self):
        self.run_scenario('pre-paint', {'GDK_BACKEND': 'x11'}, frozen_libraries=True)


if __name__ == '__main__':
    unittest.main()
