"""Source dependency selection, without importing Flet or the Cubeon package."""
import ast
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import source_runtime as runtime


class SourceRuntimeTests(unittest.TestCase):
    def test_checks_before_package_and_installer_imports(self):
        tree = ast.parse((ROOT / 'main.py').read_text())
        imports = [node for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.module]
        guard = next(n for n in imports if n.module == 'source_runtime')
        self.assertLess(guard.lineno, min(n.lineno for n in imports
                                        if n.module.startswith('cubeon')))
        probe = subprocess.run([sys.executable, '-c',
            'import source_runtime,sys; assert "cubeon" not in sys.modules; '
            'assert "flet" not in sys.modules'], cwd=ROOT,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_matching_release_required(self):
        self.assertTrue(runtime.compatible(['0.86.5', '0.86.5']))
        for versions in (['1.0.3', '1.0.3'], ['0.86.5', '0.86.4'],
                         ['0.86.5', 'missing'], ['0.86.5rc1', '0.86.5rc1'],
                         ['0.85.5', '0.85.5'], ['0.87.0', '0.87.0'],
                         None, [], [None, None]):
            with self.subTest(versions=versions):
                self.assertFalse(runtime.compatible(versions))

    def test_supported_and_frozen_have_no_subprocess(self):
        with patch.object(runtime, 'project_runtime') as find:
            with patch.object(runtime, 'runtime_versions', return_value=['0.86.5'] * 2):
                runtime.ensure_source_runtime(ROOT / 'main.py')
            with patch.object(sys, 'frozen', True, create=True):
                runtime.ensure_source_runtime(ROOT / 'main.py')
            find.assert_not_called()

    def test_selection_is_verified_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            for name in ('.venv', '.venv-build'):
                path = Path(temp) / name / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
                path.parent.mkdir(parents=True)
                path.touch()
            expected = str(path)
            for first in (subprocess.TimeoutExpired('python', 5),
                          subprocess.CompletedProcess([], 0, 'invalid json'),
                          subprocess.CompletedProcess([], 0, '["1.0.3", "1.0.3"]')):
                with self.subTest(first=first), patch.object(subprocess, 'run', side_effect=[
                    first, subprocess.CompletedProcess([], 0, '["0.86.5", "0.86.5"]')]) as run:
                    self.assertEqual(runtime.project_runtime(temp), expected)
                    self.assertEqual(run.call_count, 2)
                    for call in run.call_args_list:
                        self.assertEqual(call.args[0][1:3], ['-I', '-c'])
                        self.assertEqual(call.kwargs['timeout'], 5)
                        self.assertTrue(call.kwargs['check'])

    def test_real_process_replacement_preserves_arguments_and_environment(self):
        with tempfile.TemporaryDirectory(prefix='cubeon-runtime-') as temp:
            entry = Path(temp) / 'entry.py'
            entry.write_text(
                'import os,sys\n'
                f'sys.path.insert(0, {str(ROOT)!r})\n'
                'import source_runtime as r\n'
                'if os.environ.get("CUBEON_SOURCE_RUNTIME_REEXEC"):\n'
                '    r.runtime_versions = lambda: ["0.86.5"] * 2\n'
                'else:\n'
                '    r.runtime_versions = lambda: ["1.0.3"] * 2\n'
                f'    r.project_runtime = lambda root: {sys.executable!r}\n'
                f'    assert "flet" not in sys.modules\n'
                'r.ensure_source_runtime(__file__)\n'
                'assert "CUBEON_SOURCE_RUNTIME_REEXEC" not in os.environ\n'
                'assert os.environ["CUBEON_GPU_RESTARTS"] == "1"\n'
                'assert os.environ["LIBGL_ALWAYS_SOFTWARE"] == "1"\n'
                'assert sys.argv[1:] == ["--color=green", "with spaces"]\n'
                'print("REPLACED_OK", os.getcwd())\n'
            )
            env = {**os.environ, 'CUBEON_GPU_RESTARTS': '1', 'LIBGL_ALWAYS_SOFTWARE': '1'}
            env.pop('CUBEON_SOURCE_RUNTIME_REEXEC', None)
            run = subprocess.run([sys.executable, str(entry), '--color=green', 'with spaces'],
                                 cwd=temp, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('REPLACED_OK ' + temp, run.stdout)

    def test_bad_replacement_cannot_loop(self):
        with patch.dict(os.environ, {runtime._REEXEC: '1'}), \
             patch.object(runtime, 'runtime_versions', return_value=['1.0.3'] * 2), \
             patch.object(runtime, 'project_runtime') as find, \
             contextlib.redirect_stderr(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as ex:
                runtime.ensure_source_runtime(ROOT / 'main.py')
            self.assertEqual(ex.exception.code, 1)
            find.assert_not_called()
            self.assertIn('pip install -r', out.getvalue())

    def test_missing_environment_and_failed_exec_offer_local_setup(self):
        for candidate in (None, '/nonexistent/venv/python'):
            with self.subTest(candidate=candidate), \
                 patch.object(runtime, 'runtime_versions', return_value=['missing'] * 2), \
                 patch.object(runtime, 'project_runtime', return_value=candidate), \
                 patch.object(os, 'execve', side_effect=OSError('unavailable')), \
                 contextlib.redirect_stderr(io.StringIO()) as out:
                with self.assertRaises(SystemExit):
                    runtime.ensure_source_runtime(ROOT / 'main.py')
                self.assertIn('requirements.txt', out.getvalue())
                self.assertNotIn('--user', out.getvalue())


if __name__ == '__main__':
    unittest.main()
