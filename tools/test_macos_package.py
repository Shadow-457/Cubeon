"""Verify native macOS release bundles. The ordinary CI pass checks the recipe."""
import argparse
import json
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
            # proc_pidpath and argv[0] can differ for Finder-launched bundles.
            # Match only argv[0], never open's later .app argument.
            for executable in (process.info["exe"], command[0] if command else ""):
                if not executable:
                    continue
                path = Path(executable).resolve()
                if path == binary:
                    launcher.append(process)
                    break
                if path.parent.name != "MacOS":
                    continue
                info = plistlib.loads((path.parent.parent / "Info.plist").read_bytes())
                if path.name != info["CFBundleExecutable"]:
                    continue
                if path.is_relative_to(client_root):
                    clients.append(process)
                    break
                # LaunchServices can run an App Translocation copy. Its signed
                # bundle identity/version must match the verified source bundle.
                source_info = plistlib.loads((binary.parent.parent / "Info.plist").read_bytes())
                if (info.get("CFBundleIdentifier") == source_info["CFBundleIdentifier"]
                        and info.get("CFBundleShortVersionString") == source_info["CFBundleShortVersionString"]):
                    launcher.append(process)
                    break
        except (psutil.Error, OSError, ValueError, KeyError):
            continue
    return launcher, clients


def flet_pid_process(psutil, fresh_log):
    """Resolve this session's actual spawned PID, with Flet PID-file fallback."""
    starts = [line.split("Desktop client started: pid=", 1)[1].split()[0]
              for line in fresh_log.splitlines()
              if "cubeon.desktop_runtime:" in line and "Desktop client started: pid=" in line
              and "kind=helper" not in line]
    lines = [line.split("pid_file: ", 1)[1].strip() for line in fresh_log.splitlines()
             if "flet_desktop:" in line and "pid_file: " in line]
    if not starts and not lines:
        return []
    try:
        pid = int(starts[-1]) if starts else int(Path(lines[-1]).read_text().strip())
        process = psutil.Process(pid)
        return [process] if process.is_running() and process.status() != psutil.STATUS_ZOMBIE else []
    except (OSError, ValueError, psutil.Error):
        return []


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
    reports = Path.home() / "Library/Logs/DiagnosticReports"
    previous_reports = set(reports.glob("*"))
    for route, arguments in (("Finder", ["open", "-n", "-W", str(bundle)]),
                             ("executable", [str(binary)]),
                             ("Finder repeat", ["open", "-n", "-W", str(bundle)])):
        marker.unlink(missing_ok=True)
        before = set(psutil.pids())
        with tempfile.TemporaryDirectory(prefix="cubeon-macos-smoke-") as directory:
            env = dict(os.environ, CUBEON_GAME_DIR=str(Path(directory) / "game"),
                       CUBEON_STARTUP_PROFILE="1")
            output = Path(directory) / "startup.log"
            launcher_log = Path.home() / ".cubeon_launcher/cubeon.log"
            log_start = len(launcher_log.read_text(errors="replace")) if launcher_log.exists() else 0
            def fresh_log():
                return launcher_log.read_text(errors="replace")[log_start:] if launcher_log.exists() else ""
            observed = []
            observed_state = None
            def discover():
                nonlocal observed_state
                launcher, _ = smoke_processes(psutil, binary, before)
                found = launcher, flet_pid_process(psutil, fresh_log())
                pid_paths = [line.split("pid_file: ", 1)[1].strip()
                             for line in fresh_log().splitlines()
                             if "flet_desktop:" in line and "pid_file: " in line]
                try:
                    pid_value = Path(pid_paths[-1]).read_text() if pid_paths else "unannounced"
                except OSError:
                    pid_value = "missing"
                state = (marker.exists(), tuple(p.pid for p in launcher), tuple(p.pid for p in found[1]), pid_value, len(fresh_log()))
                if state != observed_state:
                    observed_state = state
                    observed.append(f"time={time.monotonic()} state={state} recent_log={fresh_log()[-700:]}")
                    for child in psutil.process_iter(["pid", "name", "exe", "cmdline", "status", "ppid"]):
                        if child.pid in before and child.pid not in [p.pid for p in found[1]]:
                            continue
                        if (child.pid not in [p.pid for p in launcher + found[1]]
                                and "flet" not in (child.info["name"] or "").lower()):
                            continue
                        observed.append(str(dict(child.info, cmdline=(child.info["cmdline"] or [])[:1])))
                    observed.append(f"matched launchers={[p.pid for p in found[0]]} clients={[p.pid for p in found[1]]}")
                    del observed[:-60]
                return found
            def diagnostics():
                crash_reports = []
                for path in sorted(set(reports.glob("*")) - previous_reports):
                    if "flet" not in path.name.lower() or not path.is_file():
                        continue
                    try:
                        content = path.read_text(errors="replace")
                        if path.suffix == ".ips":
                            data = json.loads(content.split("\n", 1)[1])
                            thread = data.get("threads", [])[data.get("faultingThread", 0)]
                            frames = thread.get("frames", [])[:20]
                            indices = {frame.get("imageIndex") for frame in frames}
                            crash_reports.append(json.dumps({"report": path.name,
                                "exception": data.get("exception"), "termination": data.get("termination"),
                                "frames": frames, "images": [item for index, item in enumerate(data.get("usedImages", [])) if index in indices]}, indent=2))
                        else:
                            crash_reports.append(content[:6000])
                    except (OSError, ValueError, IndexError, KeyError):
                        continue
                return ((output.read_text(errors="replace") +
                         fresh_log())[-6000:] + "\nFirst-paint processes:\n" + "\n".join(observed)
                        + "\nNative crash reports:\n" + "\n".join(crash_reports))
            with output.open("wb") as log:
                process = subprocess.Popen(arguments, cwd=directory, env=env,
                                           stdout=log, stderr=subprocess.STDOUT)
                failure = None
                try:
                    def alive(child):
                        try:
                            return child.is_running() and child.status() != psutil.STATUS_ZOMBIE
                        except psutil.Error:
                            return False
                    hold_seconds = 45 if route.startswith("Finder") else 15
                    wait_for_smoke(marker, discover,
                                   alive, diagnostics, route, hold_seconds=hold_seconds)
                    print(f"macOS {arch}: {route} launch reached first paint and stayed open for {hold_seconds} seconds")
                except AssertionError as error:
                    failure = error
                finally:
                    # Both the launcher and Flet can detach through LaunchServices.
                    launcher, clients = discover()
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
            if failure is not None:
                geometry = Path.home() / ".cubeon_launcher/window_geometry.json"
                print("Saved Cubeon geometry:", geometry.read_text() if geometry.exists() else "missing", flush=True)
                # Reuse the existing native close probe against the same Flet
                # cache. This distinguishes Cubeon startup from a bare client's
                # repeat-launch failure, while retaining the original failure.
                saved = json.loads(geometry.read_text()) if geometry.exists() else {}
                for label, position in (("default", None),
                                        ("saved size", {key: value for key, value in saved.items() if key not in ("left", "top")}),
                                        ("saved size and position", saved),
                                        ("deferred saved position", saved)):
                    probe_args = [sys.executable, str(ROOT / "tools/test_window_close.py"), "--native-child", "--native-hidden"]
                    if position is not None:
                        probe_args.append("--native-geometry=" + json.dumps(position))
                    if label == "deferred saved position":
                        probe_args.append("--native-defer-position")
                    probe_before = set(psutil.pids())
                    try:
                        probe = subprocess.run(probe_args, cwd=directory, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
                        print(f"Bare hidden Flet repeat-launch probe ({label}):", probe.returncode, probe.stdout[-6000:], flush=True)
                    except subprocess.TimeoutExpired as error:
                        print(f"Bare hidden Flet repeat-launch probe ({label}) timed out:", error.stdout, flush=True)
                    finally:
                        _, leftover = smoke_processes(psutil, binary, probe_before)
                        for child in leftover:
                            try:
                                child.kill()
                            except psutil.Error:
                                pass
                        psutil.wait_procs(leftover, timeout=5)
                raise failure


def smoke_regressions():
    from types import SimpleNamespace
    from unittest.mock import patch
    import psutil
    with tempfile.TemporaryDirectory(prefix="cubeon-smoke-regression-") as directory:
        home = Path(directory)
        binary = home / "Cubeon.app/Contents/MacOS/Cubeon"
        client = home / ".flet/client/flet-desktop-full-0.86.5/Flet.app/Contents/MacOS/flet"
        client.parent.mkdir(parents=True)
        binary.parent.mkdir(parents=True)
        app_identity = {"CFBundleExecutable": "Cubeon", "CFBundleIdentifier": "online.ylet.cubeon",
                        "CFBundleShortVersionString": "1.4.55"}
        (binary.parent.parent / "Info.plist").write_bytes(plistlib.dumps(app_identity))
        (client.parent.parent / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "flet"}))
        def process(pid, executable, command=None, status="running"):
            return SimpleNamespace(pid=pid, info=dict(exe=str(executable), cmdline=command or [], status=status))
        launcher, flet = process(10, binary), process(11, client)
        finder_launcher = process(14, '/usr/bin/other-executable', [str(binary)])
        finder_client = process(15, '/usr/bin/other-executable', [str(client)])
        relocated = home / 'AppTranslocation/Cubeon.app/Contents/MacOS/Cubeon'
        relocated.parent.mkdir(parents=True)
        (relocated.parent.parent / 'Info.plist').write_bytes(plistlib.dumps(app_identity))
        relocated_launcher = process(16, relocated)
        helper = process(12, "/usr/bin/open", ["open", "-n", "-W", str(binary.parent.parent.parent)])
        old = process(9, binary)
        zombie = process(13, binary, status=psutil.STATUS_ZOMBIE)
        with patch.object(Path, "home", return_value=home), patch.object(psutil, "process_iter", return_value=[old, helper, launcher, flet, zombie, finder_launcher, finder_client, relocated_launcher]):
            assert smoke_processes(psutil, binary, {9}) == ([launcher, finder_launcher, relocated_launcher], [flet, finder_client])
            (relocated.parent.parent / 'Info.plist').write_bytes(plistlib.dumps(dict(app_identity, CFBundleShortVersionString='1.0.0')))
            assert relocated_launcher not in smoke_processes(psutil, binary, {9})[0]
        marker = home / "painted"
        marker.touch()
        from unittest.mock import Mock
        pid_file = home / 'random-flet-pid'
        pid_file.write_text('42')
        client_process = Mock(pid=42)
        client_process.is_running.return_value = True
        client_process.status.return_value = 'running'
        fresh = f'INFO flet_desktop: pid_file: {pid_file}'
        with patch.object(psutil, 'Process', return_value=client_process) as resolve:
            assert flet_pid_process(psutil, fresh) == [client_process]
            resolve.assert_called_once_with(42)
            assert flet_pid_process(psutil, 'INFO cubeon.desktop_runtime: Desktop client started: pid=42 executable=flet pid_file=unused') == [client_process]
            helper_start = 'INFO cubeon.desktop_runtime: Desktop client started: pid=999 executable=open pid_file=unused kind=helper'
            assert flet_pid_process(psutil, helper_start + '\n' + fresh) == [client_process]
            resolve.assert_called_with(42)
            client_process.status.return_value = psutil.STATUS_ZOMBIE
            assert flet_pid_process(psutil, fresh) == []
        pid_file.unlink()
        assert flet_pid_process(psutil, fresh) == []
        assert flet_pid_process(psutil, '') == []
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
