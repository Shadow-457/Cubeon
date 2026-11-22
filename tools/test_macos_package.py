"""Verify native macOS release bundles. The ordinary CI pass checks the recipe."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def dmg(arch, version=None):
    assert sys.platform == "darwin", "DMG checks require macOS"
    image = ROOT / f"dist/Cubeon-macOS-{arch}.dmg"
    subprocess.run(["hdiutil", "verify", str(image)], check=True)
    with tempfile.TemporaryDirectory(prefix="cubeon-dmg-check-") as directory:
        mount = Path(directory) / "volume"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(image)], check=True)
        try:
            bundle = mount / "Cubeon.app"
            info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
            if version:
                assert info["CFBundleShortVersionString"] == version, info
            assert (mount / "Applications").is_symlink()
            assert os.readlink(mount / "Applications") == "/Applications"
            binary = bundle / "Contents/MacOS" / info["CFBundleExecutable"]
            subprocess.run(["lipo", str(binary), "-verify_arch", "arm64" if arch == "arm64" else "x86_64"], check=True)
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
            print(f"macOS {arch}: DMG contains the signed app and Applications shortcut")
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True)


def native(arch):
    import psutil
    assert sys.platform == "darwin", "Native checks require a Mac runner"
    bundle = ROOT / "dist/Cubeon.app"
    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    binary = bundle / "Contents/MacOS" / info["CFBundleExecutable"]
    machine = "arm64" if arch == "arm64" else "x86_64"
    subprocess.run(["lipo", str(binary), "-verify_arch", machine], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
    archive = ROOT / f"dist/Cubeon-macOS-{arch}.zip"
    with zipfile.ZipFile(archive) as package:
        assert "Cubeon.app/Contents/Info.plist" in package.namelist()
        assert any(name.endswith("assets/jars/cubeon-client-1.0.0+mc26.3.jar")
                   for name in package.namelist()), "Companion JAR is missing"
        clients = [name for name in package.namelist() if name.endswith("flet-macos.tar.gz")]
        assert clients, "Offline Flet client is missing"
        # The Flet client is universal; verify the native slice without launching Rosetta.
        with tempfile.TemporaryDirectory(prefix="cubeon-flet-arch-") as directory:
            client = Path(directory) / "client.tar.gz"
            client.write_bytes(package.read(clients[0]))
            with tarfile.open(client) as runtime:
                app_info = next(member for member in runtime.getmembers()
                                if member.name.endswith(".app/Contents/Info.plist"))
                data = plistlib.loads(runtime.extractfile(app_info).read())
                path = app_info.name.removesuffix("Info.plist") + "MacOS/" + data["CFBundleExecutable"]
                executable = Path(directory) / "flet"
                executable.write_bytes(runtime.extractfile(path).read())
                subprocess.run(["lipo", str(executable), "-verify_arch", machine], check=True)
    # A fresh CI runner has no user state. Exercise the actual packaged launcher
    # and its bundled native client, using the existing first-paint marker.
    marker = Path.home() / ".cubeon_launcher/ui_painted_ok"
    marker.unlink(missing_ok=True)
    before = set(psutil.pids())
    with tempfile.TemporaryDirectory(prefix="cubeon-macos-smoke-") as directory:
        env = dict(os.environ, CUBEON_GAME_DIR=str(Path(directory) / "game"))
        output = Path(directory) / "startup.log"
        with output.open("wb") as log:
            process = subprocess.Popen([str(binary)], cwd=directory, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline and not marker.exists():
                    if process.poll() is not None:
                        break
                    time.sleep(0.25)
                assert marker.exists(), output.read_text(errors="replace")[-6000:]
                time.sleep(3)
                assert process.poll() is None, "Packaged launcher exited after first paint"
                print(f"macOS {arch}: native launcher and bundled Flet client reached first paint")
            finally:
                # Flet uses LaunchServices, so its process can be detached from Python.
                for child in psutil.process_iter(["pid", "name", "cmdline"]):
                    if child.pid in before:
                        continue
                    command = " ".join(child.info["cmdline"] or [])
                    if child.pid == process.pid or ("flet" in child.info["name"].lower()
                                                   and ".flet/client/" in command):
                        try:
                            child.terminate()
                        except psutil.Error:
                            pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--dmg-only", action="store_true")
    parser.add_argument("--arch", choices=("arm64", "x64"))
    parser.add_argument("--version")
    args = parser.parse_args()
    if args.native:
        assert args.arch
        native(args.arch)
        dmg(args.arch)
    elif args.dmg_only:
        assert args.arch
        dmg(args.arch, args.version)
    else:
        script = (ROOT / "packaging/build_macos.sh").read_text()
        assert '--target-arch "$TARGET_ARCH"' in script
        assert '--keepParent dist/Cubeon.app' in script
        assert "assets/icon_512.png" in script
        assert "get_artifact_filename()" in script
        assert "packaging/build_macos_dmg.sh" in script
        subprocess.run(["bash", "-n", str(ROOT / "packaging/build_macos.sh")], check=True)
        subprocess.run(["bash", "-n", str(ROOT / "packaging/build_macos_dmg.sh")], check=True)
        print("macOS packaging recipe checks passed; native checks run on both CI runners")
