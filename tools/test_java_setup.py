"""Runnable Java selection, automatic fallback and interrupted runtime repair."""
import os
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import jre, launch


@unittest.skipIf(os.name == "nt", "POSIX executable fixtures")
class JavaSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for context in (
            patch.dict(os.environ, {"PATH": "", "JAVA_HOME": ""}),
            patch.object(launch.mll.java_utils, "find_system_java_versions", return_value=[]),
            patch.object(launch, "_local_java_binaries", return_value=[]),
            patch.object(jre, "installed_runtimes", return_value={}),
        ):
            context.start()
            self.addCleanup(context.stop)

    def java(self, name, major=21, *, code=0, stdout=False, quoted=True):
        binary = self.root / name / "bin" / "java"
        binary.parent.mkdir(parents=True, exist_ok=True)
        version = f'openjdk version "{major}.0.1"' if quoted else f"openjdk {major}.0.1 2026-10-20"
        binary.write_text(f"#!/bin/sh\necho '{version}'{' ' if stdout else ' >&2'}\nexit {code}\n")
        binary.chmod(0o755)
        return str(binary)

    def test_reads_stdout_and_unquoted_modern_versions(self):
        for stdout in (True, False):
            for quoted in (True, False):
                java = self.java(f"java-{stdout}-{quoted}", 25, stdout=stdout, quoted=quoted)
                self.assertEqual(launch.java_major_version(java), 25)

    def test_failed_process_is_rejected_even_if_it_prints_a_version(self):
        java = self.java("broken", code=1)
        self.assertIsNone(launch.java_major_version(java))
        self.assertFalse(jre.java_status("1.21.11", java)["ok"])

    def test_non_java_and_non_executable_files_are_rejected(self):
        self.assertIsNone(launch.java_major_version(sys.executable))
        java = self.java("blocked")
        Path(java).chmod(0o644)
        self.assertIsNone(launch.java_major_version(java))
        self.assertFalse(jre.java_status("1.21.11", java)["ok"])

    def test_quotes_bin_folder_and_mac_bundle_are_normalized(self):
        java = self.java("JDK with spaces")
        home = str(Path(java).parent.parent)
        self.assertEqual(launch._normalize_java_path(' "' + home + '" '), java)
        self.assertEqual(launch._normalize_java_path(str(Path(java).parent)), java)
        self.assertEqual(launch._normalize_java_path(' "' + java + '" '), java)
        mac = self.java("bundle.jdk/Contents/Home")
        self.assertEqual(launch._normalize_java_path(str(self.root / "bundle.jdk")), mac)
        self.assertEqual(launch.find_java_for_version("1.21.11", '"' + home + '"'), java)

    def test_javaw_uses_its_verifiable_console_sibling(self):
        java = self.java("windows-shape")
        javaw = Path(java).with_name("javaw")
        javaw.write_text("#!/bin/sh\nexit 0\n")
        javaw.chmod(0o755)
        self.assertEqual(launch._normalize_java_path(str(javaw)), java)
        self.assertEqual(launch.java_major_version(str(javaw)), 21)

    def test_later_path_entry_works_after_a_broken_java_shim(self):
        broken = self.java("first", code=1)
        good = self.java("second")
        with patch.dict(os.environ, {"PATH": os.pathsep.join((str(Path(broken).parent), str(Path(good).parent)))}):
            self.assertEqual(launch.find_java(), good)
            self.assertEqual(launch.find_java_for_version("1.21.11"), good)

    def test_usable_system_java_wins_over_a_lower_managed_major(self):
        system = self.java("system", 21)
        managed = self.java("managed", 17)
        with patch.object(launch, "find_java", return_value=system), \
                patch.object(jre, "installed_runtimes", return_value={17: managed}) as inventory:
            self.assertEqual(launch.find_java_for_version("1.20.1"), system)
        inventory.assert_not_called()

    def test_usable_explicit_java_wins_over_other_system_versions(self):
        explicit = self.java("explicit", 25)
        system = self.java("system", 21)
        with patch.object(launch, "find_java", return_value=system) as find:
            self.assertEqual(launch.find_java_for_version("1.20.1", explicit), explicit)
        find.assert_not_called()

    def test_managed_directory_with_wrong_major_is_not_selected(self):
        wrong = self.java("managed-21", 17)
        with patch.object(jre, "installed_runtimes", return_value={21: wrong}):
            self.assertFalse(jre.java_status("1.20.1")["ok"])

    def test_cache_rechecks_removed_runtime_dependencies(self):
        java = self.java("dependent")
        modules = Path(java).parent.parent / "lib" / "modules"
        modules.parent.mkdir()
        modules.write_bytes(b"present")
        Path(java).write_text(f"#!/bin/sh\nif [ -f '{modules}' ]; then echo 'openjdk version \"21.0.1\"' >&2; else exit 1; fi\n")
        self.assertEqual(launch.java_major_version(java), 21)
        modules.unlink()
        self.assertIsNone(launch.java_major_version(java))

    def test_successful_existing_java_never_downloads_a_runtime(self):
        java = self.java("system", 25)
        with patch.object(jre, "install_jre") as install:
            self.assertEqual(jre.ensure_java_for_version("26.3", java), java)
        install.assert_not_called()

    def test_cancellation_during_java_detection_does_not_start_a_download(self):
        java = self.java("slow-detection")
        cancelled = False
        def probe(*args, **kwargs):
            nonlocal cancelled
            cancelled = True
            return 21
        def check():
            if cancelled:
                raise InterruptedError("cancelled")
        with patch.object(launch, "java_major_version", side_effect=probe), \
                patch.object(jre, "install_jre") as install, self.assertRaises(InterruptedError):
            jre.ensure_java_for_version("1.21.11", java, cancel_check=check)
        install.assert_not_called()

    def test_missing_blocked_and_old_java_trigger_the_correct_managed_major(self):
        broken = self.java("broken", code=1)
        old = self.java("old", 8)
        for version, required in (("1.16.5", 8), ("1.17.1", 16), ("1.20.1", 17), ("1.21.11", 21), ("26.3", 25)):
            for configured in (str(self.root / "missing"), broken, old if required > 8 else broken):
                with self.subTest(version=version, configured=configured), \
                        patch.object(jre, "install_jre", return_value="managed-java") as install:
                    self.assertEqual(jre.ensure_java_for_version(version, configured), "managed-java")
                    self.assertEqual(install.call_args.args[0], required)

    def test_legacy_forge_prepares_exact_java_8(self):
        newer = self.java("java21", 21)
        with patch.object(jre, "install_jre", return_value="managed-java8") as install:
            self.assertEqual(jre.ensure_java_for_version("1.8.9-forge", newer), "managed-java8")
        self.assertEqual(install.call_args.args[0], 8)


class JavaPlatformAndCancellationTests(unittest.TestCase):
    def test_native_cpu_architecture_is_used(self):
        for system, machine, expected in (("darwin", "arm64", "aarch64"),
                                          ("win32", "ARM64", "aarch64"),
                                          ("linux", "aarch64", "aarch64"),
                                          ("win32", "AMD64", "x64"),
                                          ("win32", "i686", "x86")):
            with self.subTest(system=system, machine=machine), \
                    patch.object(jre.sys, "platform", system), patch.object(jre.platform, "machine", return_value=machine):
                self.assertEqual(jre._platform_params()["architecture"], expected)

    def test_waiting_for_another_runtime_install_is_cancellable(self):
        checks = 0
        def cancelled():
            nonlocal checks
            checks += 1
            if checks > 1:
                raise InterruptedError("cancelled")
        lock = jre._INSTALL_LOCKS[21]
        lock.acquire()
        try:
            with patch.object(jre, "_install_jre") as install, self.assertRaises(InterruptedError):
                jre.install_jre(21, cancel_check=cancelled)
            install.assert_not_called()
        finally:
            lock.release()


@unittest.skipIf(os.name == "nt", "POSIX executable fixtures")
class ManagedJavaRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtimes" / "21"
        self.java = self.runtime / "bin" / "java"
        self.java.parent.mkdir(parents=True)
        self.java.write_text("#!/bin/sh\nexit 1\n")
        self.java.chmod(0o755)
        self.original = self.java.read_bytes()
        context = patch.object(jre, "RUNTIMES_DIR", str(self.runtime.parent))
        context.start()
        self.addCleanup(context.stop)

    def archive(self, major=21):
        archive = self.root / "runtime.tar.gz"
        script = f'#!/bin/sh\necho \'openjdk version "{major}.0.1"\' >&2\n'.encode()
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("jdk/bin/java")
            info.size, info.mode = len(script), 0o755
            tar.addfile(info, io.BytesIO(script))
        return str(archive)

    def test_damaged_installed_runtime_is_repaired_and_reused_without_another_download(self):
        from cubeon import java_downloads
        archive = self.archive()
        with patch.object(java_downloads, "candidates", return_value=[{}]) as discover, \
                patch.object(java_downloads, "download", return_value=archive) as download:
            first = jre.install_jre(21)
            second = jre.install_jre(21)
        self.assertEqual(first, second)
        self.assertEqual(launch.java_major_version(first, force=True), 21)
        discover.assert_called_once()
        download.assert_called_once()
        self.assertFalse(Path(str(self.runtime) + ".old").exists())

    def test_wrong_staged_major_does_not_replace_the_original_runtime(self):
        from cubeon import java_downloads
        archive = self.archive(17)
        with patch.object(java_downloads, "candidates", return_value=[{}]), \
                patch.object(java_downloads, "download", return_value=archive), \
                self.assertRaisesRegex(jre.JreError, "reports Java 17"):
            jre.install_jre(21)
        self.assertEqual(self.java.read_bytes(), self.original)
        self.assertFalse(Path(str(self.runtime) + ".part").exists())

    def test_final_verification_failure_restores_the_original_runtime(self):
        from cubeon import java_downloads
        archive = self.archive()
        with patch.object(java_downloads, "candidates", return_value=[{}]), \
                patch.object(java_downloads, "download", return_value=archive), \
                patch.object(jre, "_probe_version", side_effect=(None, 21, None)), \
                self.assertRaisesRegex(jre.JreError, "verification failed"):
            jre.install_jre(21)
        self.assertEqual(self.java.read_bytes(), self.original)
        self.assertFalse(Path(str(self.runtime) + ".old").exists())

    def test_download_checks_cancellation_without_a_progress_callback(self):
        from cubeon import java_downloads
        cancelled = False
        def check():
            if cancelled:
                raise InterruptedError("cancelled")
        def transfer(assets, directory, major, progress, status, **kwargs):
            nonlocal cancelled
            cancelled = True
            progress(100, 1000)
            raise AssertionError("download ignored cancellation")
        with patch.object(java_downloads, "candidates", return_value=[{}]), \
                patch.object(java_downloads, "download", side_effect=transfer), \
                self.assertRaises(InterruptedError):
            jre.install_jre(21, cancel_check=check)
        self.assertEqual(self.java.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
