"""Hosted players sharing an IP can register independently from first boot."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import server


class HostedAuth(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.path = self.root / "1.21.11/plugins/AuthMe/config.yml"
        self.patcher = patch.object(server, "SERVERS_DIR", str(self.root))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def write(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    def test_first_start_creates_tunnel_settings(self):
        self.assertTrue(server._tune_authme_config("1.21.11"))
        text = self.path.read_text()
        for setting in ("maxRegPerIp: 0", "maxLoginPerIp: 0", "maxJoinPerIp: 0",
                        "enabled: false", "loginTimeout: 300", "registerTimeout: 300"):
            self.assertIn(setting, text)
        self.assertEqual(server._tune_authme_config("1.21.11"), [])

    def test_modern_config_preserves_passwords_and_other_settings(self):
        self.write("settings:\n    sessions:\n        enabled: true\n        timeout: 2\n"
                   "    restrictions:\n        maxRegPerIp: 1\n        maxLoginPerIp: 1\n"
                   "        maxJoinPerIp: 1\n        loginTimeout: 30\n        registerTimeout: 30\n"
                   "    security:\n        passwordHash: BCRYPT\n        timeout: 77\n"
                   "DataSource:\n    backend: SQLITE\n    mySQLPassword: keep-this\n")
        database = self.path.parent / "authme.db"
        database.write_bytes(b"existing account records")
        self.assertEqual(len(server._tune_authme_config("1.21.11")), 7)
        text = self.path.read_text()
        self.assertIn("enabled: false", text)
        self.assertIn("maxRegPerIp: 0", text)
        self.assertIn("passwordHash: BCRYPT", text)
        self.assertIn("timeout: 77", text)
        self.assertIn("mySQLPassword: keep-this", text)
        self.assertEqual(database.read_bytes(), b"existing account records")
        before = self.path.stat().st_mtime_ns
        self.assertEqual(server._tune_authme_config("1.21.11"), [])
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_legacy_indentation_and_timeout(self):
        self.write("settings:\n  sessions:\n    enabled: true\n    timeout: 2\n"
                   "  restrictions:\n    timeout: 60\n    maxRegPerIp: 1\n")
        server._tune_authme_config("1.21.11")
        self.assertIn("    timeout: 300", self.path.read_text())
        self.assertIn("    maxRegPerIp: 0", self.path.read_text())

    def test_unreadable_text_is_not_overwritten(self):
        self.write("settings:\n")
        self.path.write_bytes(b"\xff\xfe")
        self.assertEqual(server._tune_authme_config("1.21.11"), [])
        self.assertEqual(self.path.read_bytes(), b"\xff\xfe")

    def test_failed_replace_keeps_original_and_cleans_temp(self):
        self.write("settings:\n  restrictions:\n    maxRegPerIp: 1\n")
        original = self.path.read_bytes()
        with patch.object(server.os, "replace", side_effect=OSError("disk full")):
            self.assertEqual(server._tune_authme_config("1.21.11"), [])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.path.parent.glob(".authme-*")))

    def test_backend_applies_config_before_spawning_server(self):
        def spawn(*args, **kwargs):
            self.assertIn("maxRegPerIp: 0", self.path.read_text())
            self.assertIn("enabled: false", self.path.read_text())
            return SimpleNamespace(pid=123456)
        with patch.object(server, "is_server_running", return_value=False), \
                patch.object(server, "is_server_installed", return_value=True), \
                patch.object(server, "eula_accepted", return_value=True), \
                patch.object(server, "find_java_for_version", return_value="java"), \
                patch.object(server, "java_major_version", return_value=25), \
                patch.object(server.subprocess, "Popen", side_effect=spawn):
            try:
                self.assertEqual(server.start_server("1.21.11", 2048).pid, 123456)
            finally:
                server._server_processes.pop("1.21.11", None)


if __name__ == "__main__":
    unittest.main()
