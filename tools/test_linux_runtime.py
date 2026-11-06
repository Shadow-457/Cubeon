"""Packaged CPU gate and the side-effect-free runtime diagnostic."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import check_linux_runtime as gate


class LinuxRuntimeTests(unittest.TestCase):
    def test_source_diagnostic_exercises_native_libraries_without_user_data(self):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "CUBEON_GAME_DIR": home + "/game"}
            result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--cubeon-runtime-check"],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "ok")
            self.assertFalse((Path(home) / ".cubeon_launcher").exists())
            self.assertFalse((Path(home) / "game").exists())

    def test_probe_does_not_import_ui_or_game_services(self):
        result = subprocess.run([sys.executable, "-c", "import runtime_probe,sys; runtime_probe.check(); "
                                 "assert 'cubeon' not in sys.modules; assert 'flet' not in sys.modules"],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_release_requires_cpu_emulation(self):
        with patch.object(gate.shutil, "which", return_value=None), patch.object(gate.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "qemu-x86_64 is required"):
                gate.check(sys.executable, require_emulation=True)
            run.assert_not_called()

    def test_cpu_gate_runs_frozen_payload_on_nehalem_and_isolates_environment(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({"status": "ok", "frozen": True, "python": "3.11"}), "")
        with patch.object(gate.shutil, "which", return_value="/usr/bin/qemu-x86_64"), \
             patch.object(gate.subprocess, "run", return_value=result) as run, \
             patch.dict(os.environ, {"_PYI_ARCHIVE_FILE": "old executable", "PYTHONHOME": "/bad"}), \
             contextlib.redirect_stdout(io.StringIO()):
            gate.check(sys.executable, require_emulation=True)
        self.assertEqual(run.call_args.args[0][:3], ["/usr/bin/qemu-x86_64", "-cpu", "Nehalem"])
        self.assertEqual(run.call_args.args[0][-1], "--cubeon-runtime-check")
        env = run.call_args.kwargs["env"]
        self.assertNotIn("_PYI_ARCHIVE_FILE", env)
        self.assertNotIn("PYTHONHOME", env)
        self.assertNotEqual(env["HOME"], os.environ.get("HOME"))

    def test_illegal_instruction_and_nonfrozen_output_fail_gate(self):
        for result in (subprocess.CompletedProcess([], -4, "", "Illegal instruction"),
                       subprocess.CompletedProcess([], 0, '{"status":"ok","frozen":false}', "")):
            with self.subTest(result=result), patch.object(gate.shutil, "which", return_value=None), \
                 patch.object(gate.subprocess, "run", return_value=result):
                with self.assertRaises(RuntimeError):
                    gate.check(sys.executable)

    def test_linux_release_is_pinned_and_checks_before_packing(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        job = workflow.split("  build-linux-appimage:", 1)[1].split("\n  build-windows", 1)[0]
        self.assertIn("runs-on: ubuntu-22.04", job)
        self.assertIn('CUBEON_REQUIRE_CPU_CHECK: "1"', job)
        self.assertIn("qemu-user", job)
        builder = (ROOT / "packaging/build_appimage.sh").read_text()
        self.assertLess(builder.index("python tools/check_linux_runtime.py"),
                        builder.index("APPIMAGE_EXTRACT_AND_RUN=1 dist/appimagetool"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
