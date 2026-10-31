"""Exercise the shipped Linux setup artifact and compile Windows setup fixtures."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

if "--wine" in sys.argv:
    os.environ["CUBEON_TEST_WINE"] = "1"
    sys.argv.remove("--wine")

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("linux_installers", ROOT / "packaging/build_linux_installers.py")
builders = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builders)


class LauncherInstallers(unittest.TestCase):
    def test_self_contained_setup_install_repair_and_damaged_download(self):
        with tempfile.TemporaryDirectory(prefix="cubeon-installers-") as tmp:
            root = Path(tmp)
            image = root / "source.AppImage"
            image.write_text('#!/bin/sh\nprintf "%s\\n%s\\n" "$CUBEON_APPIMAGE_PATH" "$1" > "$CUBEON_TEST_MARKER"\n')
            setup = root / "Cubeon-Setup.sh"
            builders.build_setup(image, ROOT / "assets/icon_256.png", setup)
            image.unlink()  # Only the downloaded setup file is needed.
            prefix = root / 'My Games "quoted" $cash %percent'
            data = root / "data"
            marker = root / "started"
            env = dict(os.environ, CUBEON_INSTALL_DIR=str(prefix), XDG_DATA_HOME=str(data),
                       CUBEON_TEST_MARKER=str(marker))
            installed = subprocess.run(["bash", str(setup)], env=env, capture_output=True, text=True)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            target = prefix / "Cubeon.AppImage"
            self.assertTrue(os.access(target, os.X_OK))
            desktop = data / "applications/cubeon.desktop"
            if shutil.which("desktop-file-validate"):
                checked = subprocess.run(["desktop-file-validate", str(desktop)], capture_output=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)
            subprocess.run([str(prefix / "cubeon"), "argument with spaces"], env=env, check=True)
            self.assertEqual(marker.read_text().splitlines(), [str(target), "argument with spaces"])
            if shutil.which("gio"):
                marker.unlink()
                launched = subprocess.run(["gio", "launch", str(desktop)], env=env,
                                          capture_output=True, text=True)
                self.assertEqual(launched.returncode, 0, launched.stderr)
                import time
                deadline = time.monotonic() + 2
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(marker.read_text().splitlines()[0], str(target))
            original = target.read_bytes()
            (prefix / "worlds.keep").write_text("worlds")
            target.write_bytes(b"older version")
            target.chmod(0o555)
            subprocess.run(["bash", str(setup)], env=env, check=True, capture_output=True)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(Path(str(target) + ".cubeon-previous").read_bytes(), b"older version")
            self.assertEqual((prefix / "worlds.keep").read_text(), "worlds")
            setup.write_bytes(setup.read_bytes()[:-15])
            damaged = subprocess.run(["bash", str(setup)], env=env, capture_output=True, text=True)
            self.assertNotEqual(damaged.returncode, 0)
            self.assertIn("incomplete or damaged", damaged.stderr)
            self.assertEqual(target.read_bytes(), original)

    def test_windows_installer_compiles(self):
        compiler = shutil.which("makensis")
        cached = Path.home() / ".cache/electron-builder/nsis/nsis-3.0.4.1"
        if not compiler and (cached / "linux/makensis").is_file():
            compiler = str(cached / "linux/makensis")
        if not compiler:
            self.skipTest("NSIS compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="cubeon-nsis-") as tmp:
            root = Path(tmp)
            source = root / "payload"
            source.mkdir()
            (source / "Cubeon.exe").write_bytes(b"fixture executable")
            (source / "_internal").mkdir()
            (source / "_internal/runtime.dll").write_bytes(b"fixture runtime")
            env = dict(os.environ)
            if str(cached) in compiler:
                env["NSISDIR"] = str(cached)
            command = [compiler, "-V2", f"-DSOURCE_DIR={source}", f"-DOUTPUT_DIR={root}",
                       f"-DICON_FILE={ROOT / 'assets/icon.ico'}", "-DDISPLAY_VERSION=2.0.0",
                       "-DAPP_VERSION=2.0.0.0", str(ROOT / "packaging/Cubeon.nsi")]
            compiled = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            self.assertTrue((root / "Cubeon-Windows-x64-Setup.exe").is_file())

    @unittest.skipUnless(os.environ.get("CUBEON_TEST_WINE"), "opt-in Wine installation smoke")
    def test_windows_install_upgrade_custom_directory_and_uninstall(self):
        cached = Path.home() / ".cache/electron-builder/nsis/nsis-3.0.4.1"
        compiler = shutil.which("makensis") or str(cached / "linux/makensis")
        with tempfile.TemporaryDirectory(prefix="cubeon-wine-install-") as tmp:
            root = Path(tmp)
            env = dict(os.environ, WINEPREFIX=str(root / "wine"), WINEDEBUG="-all", NSISDIR=str(cached),
                       WINEDLLOVERRIDES="mscoree,mshtml=")
            source = root / "source"
            (source / "_internal").mkdir(parents=True)
            exe = source / "Cubeon.exe"
            exe.write_bytes(b"old executable")
            (source / "_internal/old.dll").write_bytes(b"old runtime")
            target = root / "Games with spaces" / "Cubeon"
            def wine(*args):
                result = subprocess.run(["wine", *args], env=env, capture_output=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout.decode(errors="replace")
            def build(version):
                subprocess.run([compiler, "-V2", f"-DSOURCE_DIR={source}", f"-DOUTPUT_DIR={root}",
                                f"-DICON_FILE={ROOT / 'assets/icon.ico'}", f"-DDISPLAY_VERSION={version}",
                                f"-DAPP_VERSION={version}.0", str(ROOT / "packaging/Cubeon.nsi")],
                               env=env, check=True, capture_output=True)
            build("2.0.0")
            setup = root / "Cubeon-Windows-x64-Setup.exe"
            win_target = "Z:" + str(target).replace("/", "\\")
            win_setup = "Z:" + str(setup).replace("/", "\\")
            def install(arguments):
                # Match Start-Process's raw argument string: NSIS /D is LAST
                # and unquoted, even when the directory contains spaces.
                wine("cmd", "/c", f'start "" /wait "{win_setup}" {arguments}')
            install("/S /D=" + win_target)
            self.assertTrue((target / "Cubeon.exe").is_file(),
                            f"Installer output: {list(root.rglob('Cubeon.exe'))}")
            self.assertEqual((target / "Cubeon.exe").read_bytes(), b"old executable")
            (target / "user-file.keep").write_text("keep me")
            timestamp = exe.stat().st_mtime
            exe.write_bytes(b"new executable")
            os.utime(exe, (timestamp, timestamp))
            (source / "_internal/old.dll").unlink()
            (source / "_internal/new.dll").write_bytes(b"new runtime")
            build("2.0.1")
            # No /D: the existing custom installation must be rediscovered.
            install("/S")
            self.assertEqual((target / "Cubeon.exe").read_bytes(), b"new executable")
            self.assertFalse((target / "_internal/old.dll").exists())
            self.assertTrue((target / "_internal/new.dll").is_file())
            version = wine("reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Cubeon",
                           "/v", "DisplayVersion")
            self.assertIn("2.0.1", version)
            # An incomplete installer must fail before replacing any program
            # files, leave the old launcher intact, and remove its stage.
            runtime = target / "_internal/new.dll"
            (source / "_internal/new.dll").unlink()
            (source / "_internal").rmdir()
            build("2.0.2")
            blocked = subprocess.run(["wine", "cmd", "/c", f'start "" /wait "{win_setup}" /S'],
                                     env=env, capture_output=True, timeout=30)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual((target / "Cubeon.exe").read_bytes(), b"new executable")
            self.assertEqual(runtime.read_bytes(), b"new runtime")
            self.assertEqual({p.name for p in target.iterdir()},
                             {"Cubeon.exe", "_internal", "Uninstall Cubeon.exe", "user-file.keep"})
            (source / "_internal").mkdir()
            (source / "_internal/new.dll").write_bytes(b"new runtime")
            build("2.0.1")
            # An explicit /D must override a different registry installation.
            second = root / "second Cubeon"
            install("/S /D=Z:" + str(second).replace("/", "\\"))
            self.assertTrue((second / "Cubeon.exe").is_file())
            # Synchronous NSIS uninstall test avoids its detached self-copy.
            wine(str(target / "Uninstall Cubeon.exe"), "/S", "_?=" + win_target)
            self.assertEqual((target / "user-file.keep").read_text(), "keep me")
            self.assertFalse((target / "Cubeon.exe").exists())
            self.assertFalse((target / "_internal").exists())
            self.assertIn("second Cubeon", wine("reg", "query", r"HKCU\Software\Cubeon", "/v", "InstallDir"))


if __name__ == "__main__":
    unittest.main()
