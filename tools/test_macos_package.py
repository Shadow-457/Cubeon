"""Verify native macOS release bundles. The ordinary CI pass checks the recipe."""
import argparse
import os
from pathlib import Path
import plistlib
import runpy
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
metadata = runpy.run_path(str(ROOT / "cubeon/updater.py"))
APP_VERSION, release_asset_name = metadata["APP_VERSION"], metadata["release_asset_name"]


def smoke_processes(psutil, binary, before):
    """Find native processes, excluding LaunchServices' short-lived open helper."""
    launcher, clients = [], []
    binary = binary.resolve()
    client_root = (Path.home() / ".flet/client").resolve()
    for process in psutil.process_iter(["pid", "exe", "cmdline", "status"]):
        if process.pid in before or process.info["status"] == psutil.STATUS_ZOMBIE:
            continue
        try:
            command = process.info["cmdline"] or []
            executable = process.info["exe"] or (command[0] if command else "")
            if not executable:
                continue
            path = Path(executable).resolve()
            if path == binary:
                launcher.append(process)
            elif path.is_relative_to(client_root) and path.parent.name == "MacOS":
                info = plistlib.loads((path.parent.parent / "Info.plist").read_bytes())
                if path.name == info["CFBundleExecutable"]:
                    clients.append(process)
        except (psutil.Error, OSError, ValueError, KeyError):
            continue
    return launcher, clients


def wait_for_smoke(marker, discover, alive, diagnostics, route, *,
                   startup_timeout=120, hold_seconds=15):
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        launcher, clients = discover()
        if marker.exists() and launcher and clients:
            break
        time.sleep(0.25)
    else:
        raise AssertionError(f"{route} did not reach first paint with live Cubeon/Flet processes: {diagnostics()}")
    # Monitor the exact first-painted processes, so a crash/restart cannot pass.
    deadline = time.monotonic() + hold_seconds
    while True:
        assert all(alive(process) for process in launcher + clients), (
            f"{route} Cubeon or Flet exited after first paint: {diagnostics()}")
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)


def dmg(arch, version=None):
    assert sys.platform == "darwin", "DMG checks require macOS"
    image = ROOT / "dist" / release_asset_name(f"macos-{arch}", version)
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
    archive = ROOT / "dist" / release_asset_name(f"macos-{arch}-zip")
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
    # A fresh CI runner has no user state. Exercise both executable startup
    # and Finder's LaunchServices route, using the existing first-paint marker.
    marker = Path.home() / ".cubeon_launcher/ui_painted_ok"
    for route, arguments in (("executable", [str(binary)]),
                             ("Finder", ["open", "-n", "-W", str(bundle)])):
        marker.unlink(missing_ok=True)
        before = set(psutil.pids())
        with tempfile.TemporaryDirectory(prefix="cubeon-macos-smoke-") as directory:
            env = dict(os.environ, CUBEON_GAME_DIR=str(Path(directory) / "game"))
            output = Path(directory) / "startup.log"
            def diagnostics():
                launcher_log = Path.home() / ".cubeon_launcher/cubeon.log"
                return (output.read_text(errors="replace") +
                        (launcher_log.read_text(errors="replace") if launcher_log.exists() else ""))[-6000:]
            with output.open("wb") as log:
                process = subprocess.Popen(arguments, cwd=directory, env=env,
                                           stdout=log, stderr=subprocess.STDOUT)
                try:
                    def alive(child):
                        try:
                            return child.is_running() and child.status() != psutil.STATUS_ZOMBIE
                        except psutil.Error:
                            return False
                    wait_for_smoke(marker, lambda: smoke_processes(psutil, binary, before),
                                   alive, diagnostics, route)
                    print(f"macOS {arch}: {route} launch reached first paint and stayed open for 15 seconds")
                finally:
                    # Both the launcher and Flet can detach through LaunchServices.
                    launcher, clients = smoke_processes(psutil, binary, before)
                    for child in launcher + clients:
                        try:
                            child.terminate()
                        except psutil.Error:
                            pass
                    _, live = psutil.wait_procs(launcher + clients, timeout=10)
                    for child in live:
                        try:
                            child.kill()
                        except psutil.Error:
                            pass
                    # Reap the direct process/helper as well before the next route.
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def smoke_regressions():
    from types import SimpleNamespace
    from unittest.mock import patch
    import psutil
    with tempfile.TemporaryDirectory(prefix="cubeon-smoke-regression-") as directory:
        home = Path(directory)
        binary = home / "Cubeon.app/Contents/MacOS/Cubeon"
        client = home / ".flet/client/flet-desktop-full-0.86.5/Flet.app/Contents/MacOS/flet"
        client.parent.mkdir(parents=True)
        (client.parent.parent / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "flet"}))
        def process(pid, executable, command=None, status="running"):
            return SimpleNamespace(pid=pid, info=dict(exe=str(executable), cmdline=command or [], status=status))
        launcher, flet = process(10, binary), process(11, client)
        helper = process(12, "/usr/bin/open", ["open", "-n", "-W", str(binary.parent.parent.parent)])
        old = process(9, binary)
        zombie = process(13, binary, status=psutil.STATUS_ZOMBIE)
        with patch.object(Path, "home", return_value=home), patch.object(psutil, "process_iter", return_value=[old, helper, launcher, flet, zombie]):
            assert smoke_processes(psutil, binary, {9}) == ([launcher], [flet])
        marker = home / "painted"
        marker.touch()
        # An exited open helper is irrelevant once the actual apps are alive.
        wait_for_smoke(marker, lambda: ([launcher], [flet]), lambda p: True,
                       lambda: "diagnostics", "Finder", hold_seconds=0)
        for dead in (launcher, flet):
            try:
                wait_for_smoke(marker, lambda: ([launcher], [flet]), lambda p: p is not dead,
                               lambda: "diagnostics", "Finder", hold_seconds=0)
            except AssertionError as error:
                assert "exited after first paint" in str(error)
            else:
                raise AssertionError("An exited native process passed the smoke check")
        try:
            wait_for_smoke(marker, lambda: ([], []), lambda p: True,
                           lambda: "diagnostics", "Finder", startup_timeout=0)
        except AssertionError as error:
            assert "did not reach first paint" in str(error)
        else:
            raise AssertionError("A stale paint marker passed without native processes")


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
        dmg(args.arch, APP_VERSION)
    elif args.dmg_only:
        assert args.arch
        dmg(args.arch, args.version)
    else:
        smoke_regressions()
        script = (ROOT / "packaging/build_macos.sh").read_text()
        assert '--target-arch "$TARGET_ARCH"' in script
        assert '--keepParent dist/Cubeon.app' in script
        assert "assets/icon_512.png" in script
        assert "get_artifact_filename()" in script
        assert "packaging/build_macos_dmg.sh" in script
        subprocess.run(["bash", "-n", str(ROOT / "packaging/build_macos.sh")], check=True)
        subprocess.run(["bash", "-n", str(ROOT / "packaging/build_macos_dmg.sh")], check=True)
        print("macOS packaging recipe checks passed; native checks run on both CI runners")
