"""Bundled Linux selection and macOS helper/native process lifetime checks."""
import ast
import asyncio
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cubeon.desktop_runtime import configure, wait_macos_client, wait_window_ready

ROOT = Path(__file__).resolve().parents[1]


class DesktopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.requested = 'flet-linux-ubuntu24.04-light-amd64.tar.gz'
        self.client = SimpleNamespace(get_artifact_filename=lambda: self.requested,
                                      get_package_bin_dir=lambda: str(self.folder))
        for context in (patch.object(sys, 'frozen', True, create=True),
                        patch.object(sys, 'platform', 'linux'),
                        patch.dict(sys.modules, {'flet_desktop': self.client})):
            context.start()
            self.addCleanup(context.stop)

    def bundle(self, distro='ubuntu22.04', flavor='-light', arch='amd64'):
        name = f'flet-linux-{distro}{flavor}-{arch}.tar.gz'
        (self.folder / name).touch()
        return name

    def test_newer_host_uses_shipped_jammy_archive(self):
        shipped = self.bundle()
        configure()
        self.assertEqual(self.client.get_artifact_filename(), shipped)
        configure()
        self.assertEqual(self.client.get_artifact_filename(), shipped)

    def test_matching_archive_keeps_original_selector(self):
        self.bundle('ubuntu24.04')
        original = self.client.get_artifact_filename
        configure()
        self.assertIs(self.client.get_artifact_filename, original)

    def test_selects_newest_compatible_bundled_archive(self):
        self.bundle('debian10')
        expected = self.bundle('debian12')
        configure()
        self.assertEqual(self.client.get_artifact_filename(), expected)

    def test_never_selects_wrong_arch_flavor_or_newer_glibc(self):
        self.requested = 'flet-linux-debian10-light-amd64.tar.gz'
        self.bundle()
        self.bundle('debian10', arch='arm64')
        self.bundle('debian10', flavor='')
        with self.assertRaisesRegex(RuntimeError, 'missing or incompatible'):
            configure()

    def test_missing_bundle_fails_locally(self):
        with self.assertRaisesRegex(RuntimeError, 'missing or incompatible'):
            configure()

    def test_source_and_windows_keep_flet_selection(self):
        original = self.client.get_artifact_filename
        with patch.object(sys, 'frozen', False):
            configure()
        with patch.object(sys, 'platform', 'win32'):
            configure()
        self.assertIs(self.client.get_artifact_filename, original)


class MacClientLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mac_reveal_does_not_invoke_the_reproduced_native_shutdown(self):
        window = SimpleNamespace(wait_until_ready_to_show=AsyncMock(side_effect=AssertionError("Mac client exits")))
        await wait_window_ready(window, platform="darwin")
        window.wait_until_ready_to_show.assert_not_awaited()

    async def test_windows_and_linux_keep_the_existing_bounded_readiness_call(self):
        for platform in ("win32", "linux"):
            window = SimpleNamespace(wait_until_ready_to_show=AsyncMock())
            await wait_window_ready(window, platform=platform)
            window.wait_until_ready_to_show.assert_awaited_once_with()
        # AsyncMock must actually await a blocking operation for the timeout.
        async def blocked():
            await asyncio.sleep(60)
        window.wait_until_ready_to_show = blocked
        with self.assertRaises(asyncio.TimeoutError):
            await wait_window_ready(window, platform="win32", timeout=0.01)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.pid_file = self.folder / "client.pid"
        # Load just the existing hook, without importing the launcher/UI.
        node = next(item for item in ast.parse((ROOT / "main.py").read_text()).body
                    if isinstance(item, ast.FunctionDef)
                    and item.name == "_capture_flet_client_exit")
        namespace = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
        self.capture = namespace[node.name]

    async def proxy(self, helper, slot):
        original = AsyncMock(return_value=(helper, str(self.pid_file)))
        original._cubeon_exit_capture = False
        desktop = SimpleNamespace(open_flet_view_async=original)
        with patch.dict(sys.modules, {"flet_desktop": desktop}):
            self.capture(slot)
            wrapped = desktop.open_flet_view_async
            self.capture(slot)
            self.assertIs(desktop.open_flet_view_async, wrapped)
            proxy, pid_file = await wrapped("page", "assets", True)
            self.assertEqual(pid_file, str(self.pid_file))
            original.assert_awaited_once_with("page", "assets", True)
            return proxy

    async def test_early_helper_exit_keeps_real_client_alive_until_native_close(self):
        release = self.folder / "close"
        launched_at = time.time()
        client = subprocess.Popen([sys.executable, "-c",
            "import os,sys,time; from pathlib import Path; "
            "Path(sys.argv[1]).write_text(str(os.getpid())); "
            "exec('while not Path(sys.argv[2]).exists(): time.sleep(0.02)'); "
            "sys.exit(7)", str(self.pid_file), str(release)])
        self.addCleanup(lambda: client.kill() if client.poll() is None else None)
        helper = SimpleNamespace(wait=AsyncMock(return_value=0), returncode=0,
                                 _cubeon_macos_helper=True, _cubeon_launched_at=launched_at)
        slot = {"code": None}
        proxy = await self.proxy(helper, slot)
        wait = asyncio.create_task(proxy.wait())
        try:
            await asyncio.sleep(0.15)
            self.assertFalse(wait.done(), "The helper's exit closed the live native client")
            self.assertIsNone(client.poll())
            self.assertIsNone(slot["code"])
            release.touch()
            self.assertEqual(await asyncio.wait_for(wait, timeout=5), 7)
            self.assertEqual(slot["code"], 7)
        finally:
            release.touch()
            await asyncio.wait_for(asyncio.shield(wait), timeout=5)
            client.wait(timeout=5)

    async def test_native_and_failed_helper_exit_codes_are_preserved(self):
        for native, code in ((True, -15), (False, 1)):
            slot = {}
            helper = SimpleNamespace(wait=AsyncMock(return_value=code), returncode=code,
                                     _cubeon_macos_helper=not native)
            with patch("cubeon.desktop_runtime.wait_macos_client", new_callable=AsyncMock) as follow:
                proxy = await self.proxy(helper, slot)
                self.assertEqual(await proxy.wait(), code)
                self.assertEqual(slot["code"], code)
                follow.assert_not_awaited()

    async def test_non_child_unknown_exit_does_not_inherit_helper_zero(self):
        helper = SimpleNamespace(wait=AsyncMock(return_value=0), returncode=0,
                                 _cubeon_macos_helper=True, _cubeon_launched_at=time.time())
        slot = {}
        with patch("cubeon.desktop_runtime.wait_macos_client", new_callable=AsyncMock,
                   return_value=None) as follow:
            proxy = await self.proxy(helper, slot)
            self.assertIsNone(await proxy.wait())
            self.assertIsNone(slot["code"])
            follow.assert_awaited_once()

    async def test_pid_file_startup_race_and_normal_close(self):
        import psutil
        launched_at = time.time()
        client = Mock(pid=4321)
        client.create_time.return_value = launched_at
        client.is_running.return_value = True
        client.status.return_value = psutil.STATUS_RUNNING
        client.wait.return_value = None  # LaunchServices-owned, not our child
        self.pid_file.touch()  # Dart creates it before writing its PID.
        async def write_pid():
            await asyncio.sleep(0.08)
            self.pid_file.write_text("4321")
        writer = asyncio.create_task(write_pid())
        with patch.object(psutil, "Process", return_value=client):
            self.assertIsNone(await wait_macos_client(self.pid_file, launched_at))
            client.wait.assert_called_once_with()
        await writer

    async def test_missing_invalid_dead_and_stale_pid_files_finish_bounded(self):
        import psutil
        launched_at = time.time()
        self.assertIsNone(await wait_macos_client(self.pid_file, launched_at, startup_grace=0))
        for value in ("", "invalid", "0", "-1", str(os.getpid())):
            self.pid_file.write_text(value)
            self.assertIsNone(await wait_macos_client(self.pid_file, launched_at, startup_grace=0))
        self.pid_file.write_text("4321")
        with patch.object(psutil, "Process", side_effect=psutil.NoSuchProcess(4321)):
            self.assertIsNone(await wait_macos_client(self.pid_file, launched_at))
        client = Mock(pid=4321)
        client.create_time.return_value = launched_at - 100
        with patch.object(psutil, "Process", return_value=client):
            self.assertIsNone(await wait_macos_client(self.pid_file, launched_at))
            client.wait.assert_not_called()
        client.create_time.return_value = launched_at
        client.status.return_value = psutil.STATUS_ZOMBIE
        with patch.object(psutil, "Process", return_value=client):
            self.assertIsNone(await wait_macos_client(self.pid_file, launched_at))
            client.wait.assert_not_called()

    async def test_cancelled_wait_propagates_without_claiming_a_clean_exit(self):
        helper = SimpleNamespace(wait=AsyncMock(side_effect=asyncio.CancelledError), returncode=0)
        slot = {"code": 0}
        proxy = await self.proxy(helper, slot)
        with self.assertRaises(asyncio.CancelledError):
            await proxy.wait()
        self.assertIsNone(slot["code"])


if __name__ == '__main__':
    unittest.main()
