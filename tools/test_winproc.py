"""Windows child creation options, including real mll 8 installer paths."""
import contextlib
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import winproc


class StartupInfo:
    def __init__(self):
        self.dwFlags = 0
        self.wShowWindow = 1
        self.hStdOutput = 17


class HiddenChildren(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(winproc, "os", SimpleNamespace(name="nt")))
        for name, value in (("CREATE_NO_WINDOW", 0x08000000),
                            ("CREATE_NEW_CONSOLE", 0x10),
                            ("STARTF_USESHOWWINDOW", 1), ("SW_HIDE", 0),
                            ("STARTUPINFO", StartupInfo)):
            self.stack.enter_context(patch.object(subprocess, name, value, create=True))

    def test_preserves_process_options_and_copies_startup_info(self):
        original = StartupInfo()
        original.dwFlags = 0x100
        options = winproc.hidden(creationflags=0x200, startupinfo=original,
                                 cwd="game", stdin=subprocess.DEVNULL)
        self.assertEqual(options["creationflags"], 0x08000200)
        self.assertEqual(options["startupinfo"].dwFlags, 0x101)
        self.assertEqual(options["startupinfo"].wShowWindow, 0)
        self.assertEqual(options["startupinfo"].hStdOutput, 17)
        self.assertEqual(original.dwFlags, 0x100)
        self.assertEqual(original.wShowWindow, 1)
        self.assertEqual(options["cwd"], "game")
        self.assertEqual(options["stdin"], subprocess.DEVNULL)

    def test_explicit_new_console_cannot_override_hidden_policy(self):
        options = winproc.hidden(creationflags=0x10 | 0x200)
        self.assertEqual(options["creationflags"], 0x08000200)

    def test_all_subprocess_launch_helpers_are_hidden(self):
        for name in ("call", "check_call", "check_output"):
            with self.subTest(helper=name), patch.object(subprocess, name, return_value=b"result") as call:
                result = getattr(winproc._HiddenSubprocess(), name)(
                    ["java", "-version"], cwd="fixture", timeout=5, creationflags=0x10)
                self.assertEqual(result, b"result")
                self.assertEqual(call.call_args.kwargs["creationflags"], 0x08000000)
                self.assertEqual(call.call_args.kwargs["startupinfo"].wShowWindow, 0)
                self.assertEqual(call.call_args.kwargs["cwd"], "fixture")
                self.assertEqual(call.call_args.kwargs["timeout"], 5)

    def test_posix_has_no_windows_options(self):
        with patch.object(winproc, "os", SimpleNamespace(name="posix")):
            self.assertEqual(winproc.hidden(cwd="game"), {"cwd": "game"})

    def test_current_and_legacy_modules_are_hidden_and_idempotent(self):
        import minecraft_launcher_lib
        modules = [module for name, module in tuple(sys.modules.items())
                   if name.startswith("minecraft_launcher_lib.")
                   and getattr(module, "subprocess", None) is subprocess]
        self.assertTrue(modules)
        self.addCleanup(lambda: [setattr(module, "subprocess", subprocess) for module in modules])
        winproc.patch_mll()
        shims = [module.subprocess for module in modules]
        winproc.patch_mll()
        self.assertEqual(shims, [module.subprocess for module in modules])
        with patch.object(subprocess, "run", return_value="result") as run:
            for module in modules:
                self.assertEqual(module.subprocess.run(["java", "-version"], check=True), "result")
                self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)
                self.assertTrue(run.call_args.kwargs["check"])
        self.assertIs(sys.modules["subprocess"], subprocess)

    def test_popen_is_hidden_and_forwards_output(self):
        with patch.object(subprocess, "Popen", return_value="child") as spawn:
            self.assertEqual(winproc._HiddenSubprocess().Popen(
                ["java"], stdout=subprocess.PIPE, creationflags=0x200), "child")
            self.assertEqual(spawn.call_args.kwargs["creationflags"], 0x08000200)
            self.assertEqual(spawn.call_args.kwargs["stdout"], subprocess.PIPE)

    def test_real_current_installer_runs_use_hidden_options(self):
        for name, class_name in (("_fabric", "Fabric"), ("_quilt", "Quilt"),
                                 ("_neoforge", "Neoforge")):
            with self.subTest(loader=name), contextlib.ExitStack() as stack:
                module = importlib.import_module("minecraft_launcher_lib.mod_loader." + name)
                stack.enter_context(patch.object(module, "subprocess", subprocess))
                stack.enter_context(patch.object(module, "download_file"))
                loader = getattr(module, class_name)()
                stack.enter_context(patch.object(loader, "get_installer_url", return_value="unused"))
                if name == "_neoforge":
                    stack.enter_context(patch.object(module, "do_vanilla_launcher_profiles_exists", return_value=True))
                run = stack.enter_context(patch.object(subprocess, "run"))
                winproc.patch_mll()
                loader.install("1.21.11", "fixture-game", {}, "fixture-java", "fixture-loader")
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)
                self.assertEqual(run.call_args.kwargs["startupinfo"].wShowWindow, 0)
                self.assertTrue(run.call_args.kwargs["check"])
                self.assertIn("fixture-java", run.call_args.args[0])

    def test_real_java_information_probe_is_hidden(self):
        module = importlib.import_module("minecraft_launcher_lib.java_utils")
        with tempfile.TemporaryDirectory() as scratch, \
                patch.object(module, "subprocess", subprocess), \
                patch.object(subprocess, "run", return_value=SimpleNamespace(
                    stderr='openjdk version "21.0.1"\nOpenJDK Runtime\nOpenJDK 64-Bit Server VM\n')) as run:
            Path(scratch, "bin").mkdir()
            Path(scratch, "bin", "java").touch()
            winproc.patch_mll()
            self.assertEqual(module.get_java_information(scratch)["version"], "21.0.1")
            self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)


if __name__ == "__main__":
    unittest.main()
