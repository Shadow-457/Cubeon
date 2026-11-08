"""Offline checks for server-time plugin delivery and lean packaging."""
import importlib.util
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
import _sandbox_home

_sandbox_home.isolate()
from cubeon import minekube, net, server

spec = importlib.util.spec_from_file_location("runtime_assets", ROOT / "packaging/runtime_assets.py")
runtime_assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_assets)


def jar(entries, size):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        archive.writestr("payload.bin", b"a" * size)
    return stream.getvalue()


class ServerPluginDeliveryTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="cubeon-server-delivery-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.plugin = jar({"plugin.yml": "name: connect\nmain: example.Connect\n"},
                          minekube.MIN_PLUGIN_BYTES)
        self.paper = self.root / "paper.jar"
        self.paper.write_bytes(jar({"META-INF/MANIFEST.MF": "Main-Class: io.papermc.paperclip.Main\n",
                                   "io/papermc/paperclip/Main.class": b"class"}, server.MIN_SERVER_BYTES))
        self.downloads = []
        self.discovery = minekube.find_local_plugin
        for target, attribute, value in (
                (server, "SERVERS_DIR", str(self.root / "servers")),
                (minekube, "SERVERS_DIR", str(self.root / "servers")),
                (minekube, "CACHE_DIR", str(self.root / "cache"))):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (
                patch("cubeon.paths.ensure_disk_space"),
                patch.object(minekube, "find_local_plugin", side_effect=lambda: self.discovery(
                    [str(Path(minekube.plugin_cache_path()).parent)])),
                patch.object(net, "download_to", side_effect=self.download)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def download(self, destination, url, **kwargs):
        self.downloads.append(url)
        Path(destination).write_bytes(self.plugin)
        callback = kwargs.get("progress_cb")
        if callback:
            callback(len(self.plugin), len(self.plugin))
        return len(self.plugin)

    def test_server_install_downloads_plugin_and_reports_progress(self):
        statuses, progress, maximum = [], [], []
        server.install_server("1.21.1", local_jar_path=str(self.paper),
                              status_cb=statuses.append, progress_cb=progress.append,
                              max_cb=maximum.append)
        self.assertEqual(self.downloads, [minekube.PLUGIN_URL])
        self.assertTrue(minekube.is_plugin_installed("1.21.1"))
        self.assertEqual(Path(minekube.plugin_cache_path()).read_bytes(), self.plugin)
        self.assertIn("Preparing server-sharing plugin", statuses)
        self.assertEqual(statuses[-1], "Server ready")
        self.assertEqual(progress[-1], len(self.plugin))
        self.assertEqual(maximum[-1], len(self.plugin))
        self.assertFalse(server.eula_accepted("1.21.1"))

    def test_second_server_reuses_cache_without_network(self):
        server.install_server("1.21.1", local_jar_path=str(self.paper))
        with patch.object(net, "download_to", side_effect=AssertionError("network not needed")):
            server.install_server("1.20.1", local_jar_path=str(self.paper))
            server.install_server("1.20.1", local_jar_path=str(self.paper))
        self.assertTrue(minekube.is_plugin_installed("1.20.1"))
        self.assertEqual(self.downloads, [minekube.PLUGIN_URL])
        self.assertEqual(self.discovery(), minekube.plugin_cache_path())

    def test_broken_cache_is_replaced_by_a_valid_download(self):
        cached = Path(minekube.plugin_cache_path())
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"incomplete")
        server.install_server("1.21.1", local_jar_path=str(self.paper))
        self.assertEqual(cached.read_bytes(), self.plugin)
        self.assertTrue(minekube.is_plugin_installed("1.21.1"))
        self.assertFalse(list(cached.parent.glob(".connect-*")))

    def test_failed_plugin_download_keeps_server_usable_and_retryable(self):
        statuses = []
        with patch.object(net, "download_to", side_effect=net.DownloadError("offline")), \
                self.assertLogs("cubeon.server", level="WARNING"):
            server.install_server("1.21.1", local_jar_path=str(self.paper), status_cb=statuses.append)
        self.assertTrue(server.is_server_installed("1.21.1"))
        self.assertFalse(minekube.is_plugin_installed("1.21.1"))
        self.assertIn("startup will retry", statuses[-1])
        self.assertFalse(Path(minekube.plugin_cache_path()).exists())
        minekube.install_plugin("1.21.1")
        self.assertTrue(minekube.is_plugin_installed("1.21.1"))

    def test_invalid_download_is_not_installed_or_cached(self):
        with patch.object(net, "download_to", side_effect=lambda destination, *args, **kwargs:
                          Path(destination).write_bytes(b"<html>not a plugin</html>")), \
                self.assertLogs("cubeon.server", level="WARNING"):
            server.install_server("1.21.1", local_jar_path=str(self.paper))
        self.assertTrue(server.is_server_installed("1.21.1"))
        self.assertFalse(minekube.is_plugin_installed("1.21.1"))
        self.assertFalse(Path(minekube.plugin_cache_path()).exists())
        self.assertFalse(list(Path(server.get_plugins_dir("1.21.1")).glob(".connect-*")))

    def test_packaging_omits_only_connect_and_keeps_source_assets(self):
        assets = self.root / "assets"
        (assets / "jars").mkdir(parents=True)
        (assets / "jars/connect-spigot.jar").write_bytes(self.plugin)
        (assets / "jars/cubeon-client-test.jar").write_bytes(b"client")
        (assets / "icon.png").write_bytes(b"icon")
        staged = runtime_assets.make_runtime_assets(self.root)
        self.addCleanup(shutil.rmtree, staged)
        self.assertFalse((staged / "jars/connect-spigot.jar").exists())
        self.assertEqual((staged / "jars/cubeon-client-test.jar").read_bytes(), b"client")
        self.assertEqual((staged / "icon.png").read_bytes(), b"icon")
        self.assertTrue((assets / "jars/connect-spigot.jar").exists())
        for name in ("build_appimage.sh", "build_macos.sh"):
            recipe = (ROOT / "packaging" / name).read_text()
            self.assertIn("python packaging/runtime_assets.py", recipe)
            self.assertIn('"$RUNTIME_ASSETS:assets"', recipe)
        recipe = (ROOT / "packaging/build_windows.py").read_text()
        self.assertIn("make_runtime_assets(ROOT)", recipe)
        self.assertIn('f"--add-data={assets}{SEP}assets"', recipe)


if __name__ == "__main__":
    unittest.main()
