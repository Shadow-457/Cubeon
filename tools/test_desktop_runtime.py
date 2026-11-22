"""Frozen Linux releases must use bundled Flet clients without downloading."""
import sys
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cubeon.desktop_runtime import configure, native_client_command


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


class MacClientCommandTests(unittest.TestCase):
    def test_mac_tracks_native_client_and_preserves_session_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'Flet with spaces.app'
            contents = bundle / 'Contents'
            (contents / 'MacOS').mkdir(parents=True)
            executable = contents / 'MacOS/custom-flet'
            executable.touch()
            (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'custom-flet'}))
            arguments = ['open', str(bundle), '-n', '-W', '--args', '/tmp/page socket', '/tmp/pid', '/assets with spaces']
            original = arguments.copy()
            with patch.object(sys, 'platform', 'darwin'):
                self.assertEqual(native_client_command(arguments), [str(executable), *arguments[5:]])
                executable.unlink()
                with self.assertRaises(FileNotFoundError):
                    native_client_command(arguments)
            self.assertEqual(arguments, original)

    def test_other_platforms_and_existing_native_commands_are_preserved(self):
        for platform, arguments in (('win32', ['flet.exe', 'page', 'pid']),
                                    ('linux', ['flet', 'page', 'pid']),
                                    ('darwin', ['/Flet.app/Contents/MacOS/flet', 'page', 'pid'])):
            with patch.object(sys, 'platform', platform):
                self.assertIs(native_client_command(arguments), arguments)


if __name__ == '__main__':
    unittest.main()
