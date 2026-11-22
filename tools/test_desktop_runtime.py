"""Frozen Linux releases must use bundled Flet clients without downloading."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cubeon.desktop_runtime import configure


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


if __name__ == '__main__':
    unittest.main()
