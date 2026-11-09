"""Hermetic update failure tests and executed native helper transactions.

Linux tests launch only throwaway ELF fixtures, never Cubeon or a real installer.
--native-windows adds PowerShell/NSIS transactions on a disposable Windows host.
Release fixtures pass a fixed current version, independent of APP_VERSION stamps.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import auto_update as update, storage
from cubeon._update_helpers import LINUX_HELPER, WINDOWS_HELPER

NATIVE_WINDOWS = "--native-windows" in sys.argv
if NATIVE_WINDOWS:
    sys.argv.remove("--native-windows")


def metadata(payload=None, kind="linux", version="1.4.11"):
    payload = payload or b"x" * 2048
    name = update.ASSETS[kind]
    tag = "v" + version
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": [{
        "name": name, "state": "uploaded", "size": len(payload),
        "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "browser_download_url": f"https://github.com/{update.REPOSITORY}/releases/download/{tag}/{name}",
    }]}


def elf_fixture(suffix=b""):
    binary = bytearray(Path(shutil.which("sh")).read_bytes())
    binary[8:11] = b"AI\x02"
    return bytes(binary) + suffix


class Response:
    def __init__(self, data, *, headers=None, status=200, error=None):
        self.data = data
        self.headers = headers or {}
        self.status_code = status
        self.error = error
        self.closed = False

    def iter_content(self, _size):
        yield self.data
        if self.error:
            raise self.error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP failure")


class ReleaseTests(unittest.TestCase):
    def test_numeric_order_and_stable_only(self):
        self.assertEqual(update.parse_release(metadata(), "linux", "1.4.9").version, "1.4.11")
        for version in ("1.4.11", "1.4.12", "2.0.0"):
            self.assertIsNone(update.parse_release(metadata(), "linux", version))
        for flag in ("draft", "prerelease"):
            data = metadata()
            data[flag] = True
            self.assertIsNone(update.parse_release(data, "linux", "1.4.9"))
            del data[flag]
            self.assertIsNone(update.parse_release(data, "linux", "1.4.9"))

    def test_invalid_versions_do_not_install(self):
        for value in (None, "", "1.4", "01.4.11", "1.4.11-beta", "1.4.11+build", "v1.4.11/evil", "1.4.1000000"):
            with self.subTest(value=value), self.assertRaises(update.UpdateError):
                update.version_tuple(value)

    def test_exact_asset_for_each_platform(self):
        data = metadata()
        data["assets"].append(metadata(kind="windows")["assets"][0])
        data["assets"].append({"name": "Cubeon-Linux-x86_64-Setup.AppImage"})
        for kind in ("windows", "linux"):
            self.assertEqual(update.parse_release(data, kind, "1.4.9").name, update.ASSETS[kind])
        with self.assertRaises(update.UpdateError):
            update.parse_release(data, "darwin", "1.4.9")

    def test_ambiguous_incomplete_or_untrusted_assets_rejected(self):
        cases = [("digest", None), ("digest", "sha1:" + "0" * 64), ("digest", "sha256:" + "g" * 64),
                 ("digest", "sha256:" + "0" * 63), ("size", True), ("size", 0),
                 ("size", update.MAX_ASSET + 1), ("state", "new"),
                 ("browser_download_url", "https://evil.example/installer.exe")]
        for key, value in cases:
            data = metadata()
            data["assets"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(update.UpdateError):
                update.parse_release(data, "linux", "1.4.9")
        data = metadata()
        data["assets"] *= 2
        with self.assertRaises(update.UpdateError):
            update.parse_release(data, "linux", "1.4.9")

    def test_redirect_validation_and_tls(self):
        for url in ("http://github.com/Shadow-457/Cubeon/releases/download/v1.4.11/x", "https://github.com.evil/x",
                    "https://user@github.com/Shadow-457/Cubeon/releases/download/x", "https://github.com:444/x",
                    "https://github.com/Other/Repo/releases/download/x", "https://objects.githubusercontent.com/x#fragment",
                    "https://objects.githubusercontent.com\\@evil/x", "https://objects.githubusercontent.com/\nx"):
            with self.subTest(url=url):
                self.assertFalse(update.trusted_url(url))
        self.assertTrue(update.trusted_url(metadata()["assets"][0]["browser_download_url"]))
        self.assertTrue(update.trusted_url("https://release-assets.githubusercontent.com/x?signature=abc"))
        self.assertTrue(update.trusted_url(update.LATEST_URL, metadata=True))
        self.assertFalse(update.trusted_url(update.LATEST_URL + "?token=x", metadata=True))

    def test_untrusted_redirect_is_never_opened(self):
        from cubeon import net
        response = Response(b"", status=302, headers={"Location": "https://evil.example/payload"})
        with mock.patch.object(net, "_do_get", return_value=response) as get:
            with self.assertRaises(net.DownloadError):
                update._get(metadata()["assets"][0]["browser_download_url"], threading.Event())
        self.assertEqual(get.call_count, 1)
        self.assertTrue(response.closed)

    def test_metadata_size_bound_and_cancellation(self):
        with mock.patch.object(update, "_get", return_value=Response(b"x" * (update.MAX_METADATA + 1))):
            with self.assertRaises(update.UpdateError):
                update.fetch_release("linux")
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(update, "_get") as get, self.assertRaises(update.Cancelled):
            update.fetch_release("linux", cancel=cancel)
        get.assert_not_called()


@unittest.skipIf(os.name == "nt", "ELF fixture tests")
class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cubeon-download-test-")
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name)
        self.payload = elf_fixture(b"verified new release")
        self.release = update.parse_release(metadata(self.payload), "linux", "1.4.9")
        self.target = update.Target("linux", self.cache / "installed.AppImage")

    def test_verified_bytes_are_published_and_reused_without_network(self):
        response = Response(self.payload, headers={"Content-Length": str(len(self.payload))})
        with mock.patch.object(update, "_get", return_value=response) as get:
            path = update.download_release(self.release, self.target, self.cache)
            self.assertEqual(path.read_bytes(), self.payload)
            self.assertEqual(update.download_release(self.release, self.target, self.cache), path)
        self.assertEqual(get.call_count, 1)
        self.assertTrue(response.closed)
        self.assertFalse(list(self.cache.glob("*.part")))

    def test_wrong_hash_truncation_oversize_and_compression_leave_no_final(self):
        for response in (Response(self.payload[:-1]), Response(self.payload + b"extra"),
                         Response(self.payload[:-1] + b"X"), Response(self.payload, headers={"Content-Length": "1"}),
                         Response(self.payload, headers={"Content-Encoding": "gzip"})):
            with self.subTest(response=response), mock.patch.object(update, "_get", return_value=response):
                with self.assertRaises(update.UpdateError):
                    update.download_release(self.release, self.target, self.cache)
                self.assertEqual(list(self.cache.iterdir()), [])

    def test_valid_hash_does_not_make_html_an_installer(self):
        payload = b"<html>not an AppImage</html>" * 100
        release = update.parse_release(metadata(payload), "linux", "1.4.9")
        with mock.patch.object(update, "_get", return_value=Response(payload)), self.assertRaises(update.UpdateError):
            update.download_release(release, self.target, self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_network_retry_discards_partial_bytes(self):
        cancel = threading.Event()
        with mock.patch.object(cancel, "wait", return_value=False), mock.patch.object(update, "_get", side_effect=[
                Response(self.payload[:1234], error=OSError("connection dropped")), Response(self.payload)]) as get:
            path = update.download_release(self.release, self.target, self.cache, cancel=cancel)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertFalse(list(self.cache.glob("*.part")))

    def test_corrupt_cache_replaced_but_redirected_cache_refused(self):
        path = self.cache / f"{self.release.sha256}-{self.release.name}"
        path.write_bytes(b"broken cached file")
        with mock.patch.object(update, "_get", return_value=Response(self.payload)):
            update.download_release(self.release, self.target, self.cache)
        path.unlink()
        elsewhere = self.cache / "keep"
        elsewhere.write_bytes(b"leave this alone")
        path.symlink_to(elsewhere)
        with mock.patch.object(update, "_get") as get, self.assertRaises(update.UpdateError):
            update.download_release(self.release, self.target, self.cache)
        self.assertEqual(elsewhere.read_bytes(), b"leave this alone")
        get.assert_not_called()

    def test_disk_full_and_cancel_never_publish(self):
        with mock.patch.object(update.shutil, "disk_usage", return_value=mock.Mock(free=1)), self.assertRaises(update.UpdateError):
            update.download_release(self.release, self.target, self.cache)
        cancel = threading.Event()
        def progress(_done, _total):
            cancel.set()
        with mock.patch.object(update, "_get", return_value=Response(self.payload)), self.assertRaises(update.Cancelled):
            update.download_release(self.release, self.target, self.cache, cancel=cancel, progress=progress)
        self.assertEqual(list(self.cache.iterdir()), [])


class UpdateGateTests(unittest.TestCase):
    def tearDown(self):
        storage.release_launcher_update()

    def test_active_and_queued_operations_cannot_race_shutdown(self):
        active = threading.Event()
        finish = threading.Event()
        def worker():
            with storage.update_operation():
                active.set()
                finish.wait(3)
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(active.wait(1))
        self.assertFalse(storage.claim_launcher_update())
        finish.set()
        thread.join(1)
        self.assertTrue(storage.claim_launcher_update())
        self.assertTrue(storage.blocked())
        with self.assertRaises(RuntimeError), storage.update_operation():
            self.fail("Queued work started during update")
        with self.assertRaises(RuntimeError):
            storage.assert_writable()
        storage.release_launcher_update()
        with storage.update_operation():
            pass

    def test_operation_failure_releases_claim_and_migration_defers(self):
        with self.assertRaises(ValueError), storage.update_operation():
            raise ValueError("failed job")
        self.assertTrue(storage.claim_launcher_update())
        storage.release_launcher_update()
        with storage._migration_mutex:
            self.assertFalse(storage.claim_launcher_update())
        self.assertTrue(storage.claim_launcher_update())

    def test_server_pack_and_backup_entry_points_respect_gate(self):
        from cubeon import backup, content, modpacks, server
        self.assertTrue(storage.claim_launcher_update())
        for callback in (lambda: server.start_server("1.21", 1024), lambda: server.install_server("1.21"),
                         lambda: modpacks.install_modpack_from_file("missing.zip"),
                         lambda: content.install_local_content("shader", "missing.zip", "1.21", "fabric")):
            with self.assertRaises(RuntimeError):
                callback()
        self.assertFalse(backup.create_backup().ok)
        self.assertFalse(backup.restore_backup("missing.zip").ok)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cubeon-controller-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = update.Target("linux", self.root / "Cubeon.AppImage")
        self.target.path.write_bytes(b"old launcher")
        self.release = update.parse_release(metadata(), "linux", "1.4.9")
        self.prepare = mock.Mock(return_value=True)
        self.close = mock.Mock(return_value=True)
        self.resume = mock.Mock()
        self.notice = mock.Mock()
        self.controller = update.AutoUpdater(prepare=self.prepare, request_exit=self.close,
                                             resume=self.resume, notice=self.notice)
        self.handoff = mock.Mock()
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        for name, kwargs in {
            "detect_target": {"return_value": self.target}, "cache_root": {"return_value": self.root / "updates/v1"},
            "fetch_release": {"return_value": self.release}, "other_launcher_running": {"return_value": False},
            "download_release": {"return_value": self.root / "cached.AppImage"},
            "spawn_helper": {"return_value": self.handoff}, "wait_ready": {"return_value": None},
            "create_job": {"return_value": (self.root / "fake-job", {})},
        }.items():
            self.patches.enter_context(mock.patch.object(update, name, **kwargs))

    def test_busy_retains_download_and_does_not_close(self):
        self.prepare.return_value = False
        self.controller.run()
        update.download_release.assert_called_once()
        update.spawn_helper.assert_not_called()
        self.close.assert_not_called()
        self.resume.assert_not_called()
        self.notice.assert_any_call("deferred", self.release)

    def test_readiness_failure_or_rejected_close_cancels_and_restores(self):
        for failure in ("ready", "close"):
            with self.subTest(failure=failure):
                self.prepare.reset_mock(); self.close.reset_mock(); self.resume.reset_mock(); self.handoff.reset_mock()
                update.wait_ready.side_effect = update.UpdateError("helper failed") if failure == "ready" else None
                self.close.return_value = False
                with self.assertLogs(update.log, level="WARNING"):
                    self.controller.run()
                self.handoff.cancel.assert_called_once()
                self.resume.assert_called_once()
                if failure == "ready":
                    self.close.assert_not_called()

    def test_successful_handoff_survives_session_cleanup(self):
        self.controller.run()
        self.close.assert_called_once_with(self.handoff, self.release)
        self.controller.stop()
        self.handoff.cancel.assert_not_called()
        self.resume.assert_not_called()

    def test_other_launcher_and_failed_version_cooldown_do_not_close(self):
        update.other_launcher_running.return_value = True
        self.controller.run()
        self.prepare.assert_not_called()
        cache = self.root / "updates/v1" / self.target.key
        (cache / f"failed-{self.release.sha256}").write_text("rolled-back")
        update.download_release.reset_mock()
        self.controller.run()
        update.download_release.assert_not_called()
        self.close.assert_not_called()

    def test_source_and_cancelled_start_never_check_network(self):
        update.detect_target.return_value = None
        self.controller.run()
        update.fetch_release.assert_not_called()
        self.controller.stop()
        self.controller.start()
        self.assertIsNone(self.controller._thread)


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("flock"), "native Linux helper")
class LinuxHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cubeon-linux-helper-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir(mode=0o700)
        self.target = update.Target("linux", self.root / 'Cubeon $cash $(touch NEVER) "quoted" %\n.AppImage')
        self.old = elf_fixture(b"old")
        self.new = elf_fixture(b"new")
        self.target.path.write_bytes(self.old)
        self.target.path.chmod(0o555)
        self.download = self.cache / "download.AppImage"
        self.download.write_bytes(self.new)
        self.release = update.parse_release(metadata(self.new), "linux", "1.4.9")
        self.parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(self.end_parent)
        self.helpers = []
        self.addCleanup(self.end_helpers)

    def end_parent(self):
        if self.parent.poll() is None:
            self.parent.terminate()
        self.parent.wait(timeout=3)

    def end_helpers(self):
        for handoff in self.helpers:
            if handoff.process.poll() is None:
                handoff.cancel()
                try:
                    handoff.process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    handoff.process.terminate()
                    handoff.process.wait(timeout=3)
            identity = handoff.directory / "launch.identity"
            if identity.exists():
                pid, ticks = identity.read_text().split(":")
                proc_stat = Path(f"/proc/{pid}/stat")
                if ticks and proc_stat.exists() and proc_stat.read_text().rsplit(")", 1)[1].split()[19] == ticks:
                    try:
                        os.killpg(int(pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass

    def helper(self, args=None, parent_wait=5, health_wait=3):
        if args is None:
            args = ["-c", 'printf "%s" "$CUBEON_UPDATE_TOKEN" > "${CUBEON_UPDATE_JOB%/*}/health.ok"']
        directory, job = update.create_job(self.target, self.release, self.download, self.cache, args=args,
                                           parent_pid=self.parent.pid, parent_wait=parent_wait, health_wait=health_wait)
        handoff = update.spawn_helper(directory, job)
        self.helpers.append(handoff)
        return handoff

    def result(self, handoff, expected_code=0):
        self.assertEqual(handoff.process.wait(timeout=10), expected_code,
                         (handoff.directory / "helper.log").read_text())
        return (handoff.directory / "result").read_text().strip()

    def test_install_waits_for_exit_preserves_old_bytes_and_releases_lock(self):
        handoff = self.helper()
        update.wait_ready(handoff, threading.Event(), timeout=5)
        self.assertEqual(self.target.path.read_bytes(), self.old)
        handoff.commit()
        time.sleep(.3)
        self.assertEqual(self.target.path.read_bytes(), self.old)
        self.end_parent()
        self.assertEqual(self.result(handoff), "installed")
        self.assertEqual(self.target.path.read_bytes(), self.new)
        self.assertEqual(Path(str(self.target.path) + ".cubeon-previous").read_bytes(), self.old)
        self.assertEqual(self.target.path.stat().st_mode & 0o777, 0o555)
        self.assertFalse((self.root / "NEVER").exists())
        with update.TargetLock(self.cache / "update.lock"):
            pass

    def test_cancel_after_commit_never_replaces(self):
        handoff = self.helper()
        update.wait_ready(handoff, threading.Event(), timeout=5)
        handoff.commit()
        handoff.cancel()
        self.end_parent()
        self.assertEqual(self.result(handoff), "cancelled")
        self.assertEqual(self.target.path.read_bytes(), self.old)
        self.assertFalse(list(self.root.glob("*.cubeon-update-*")))

    def test_failed_startup_rolls_back_and_sets_cooldown(self):
        handoff = self.helper(args=["-c", "exit 9"])
        update.wait_ready(handoff, threading.Event(), timeout=5)
        handoff.commit(); self.end_parent()
        self.assertEqual(self.result(handoff, expected_code=1), "rolled-back")
        self.assertEqual(self.target.path.read_bytes(), self.old)
        self.assertEqual((self.cache / f"failed-{self.release.sha256}").read_text().strip(), "rolled-back")

    def test_missing_health_ack_rolls_back_only_its_own_launch(self):
        handoff = self.helper(args=["-c", "sleep 30"], health_wait=1)
        update.wait_ready(handoff, threading.Event(), timeout=5)
        handoff.commit(); self.end_parent()
        self.assertEqual(self.result(handoff, expected_code=1), "rolled-back")
        self.assertEqual(self.target.path.read_bytes(), self.old)

    def test_checksum_tamper_before_prepare_and_after_ready_cannot_install(self):
        self.download.write_bytes(self.new[:-1] + b"X")
        handoff = self.helper()
        self.assertEqual(self.result(handoff, expected_code=1), "failed")
        self.assertFalse((handoff.directory / "ready").exists())
        self.download.write_bytes(self.new)
        handoff = self.helper()
        update.wait_ready(handoff, threading.Event(), timeout=5)
        stage = Path(str(self.target.path) + f".cubeon-update-{handoff.token}.new")
        stage.chmod(0o755)
        stage.write_bytes(self.new[:-1] + b"X")
        handoff.commit(); self.end_parent()
        self.assertEqual(self.result(handoff, expected_code=1), "failed")
        self.assertEqual(self.target.path.read_bytes(), self.old)

    def test_target_changed_during_handoff_is_preserved(self):
        handoff = self.helper()
        update.wait_ready(handoff, threading.Event(), timeout=5)
        self.target.path.chmod(0o755)
        self.target.path.write_bytes(b"manual replacement")
        handoff.commit(); self.end_parent()
        self.assertEqual(self.result(handoff, expected_code=1), "failed")
        self.assertEqual(self.target.path.read_bytes(), b"manual replacement")

    def test_other_helper_cannot_get_ready_for_same_target(self):
        first = self.helper()
        update.wait_ready(first, threading.Event(), timeout=5)
        second = self.helper()
        self.assertEqual(second.process.wait(timeout=5), 75)
        self.assertFalse((second.directory / "ready").exists())
        first.cancel()
        self.assertEqual(self.result(first), "cancelled")

    def test_parent_timeout_and_uncommitted_exit_leave_target_intact(self):
        handoff = self.helper(parent_wait=1)
        update.wait_ready(handoff, threading.Event(), timeout=5)
        handoff.commit()
        self.assertEqual(self.result(handoff, expected_code=1), "failed")
        self.assertEqual(self.target.path.read_bytes(), self.old)
        handoff = self.helper()
        update.wait_ready(handoff, threading.Event(), timeout=5)
        self.end_parent()
        self.assertEqual(self.result(handoff), "cancelled")
        self.assertEqual(self.target.path.read_bytes(), self.old)

    def test_symlink_backup_does_not_overwrite_unrelated_file(self):
        keep = self.root / "unrelated"
        keep.write_bytes(b"keep")
        Path(str(self.target.path) + ".cubeon-previous").symlink_to(keep)
        handoff = self.helper()
        self.assertEqual(self.result(handoff, expected_code=1), "failed")
        self.assertEqual(keep.read_bytes(), b"keep")
        self.assertEqual(self.target.path.read_bytes(), self.old)

    def test_shell_syntax_and_arguments_are_data(self):
        checked = subprocess.run(["/bin/bash", "-n"], input=LINUX_HELPER, text=True, capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        directory, job = update.create_job(self.target, self.release, self.download, self.cache, args=[], parent_pid=self.parent.pid)
        self.assertEqual((directory / "job.bin").read_bytes().split(b"\0")[15:], [b""])
        args = ["", 'quotes " and $dollars', "line\nbreak"]
        directory, _ = update.create_job(self.target, self.release, self.download, self.cache, args=args, parent_pid=self.parent.pid)
        self.assertEqual((directory / "job.bin").read_bytes().split(b"\0")[15:-1], [arg.encode() for arg in args])


@unittest.skipUnless(os.name == "nt", "Windows PowerShell parser")
class WindowsScriptTests(unittest.TestCase):
    def test_powershell_51_parses_helper(self):
        with tempfile.TemporaryDirectory(prefix="cubeon-powershell-parse-") as tmp:
            path = Path(tmp) / "helper.ps1"
            path.write_text(WINDOWS_HELPER, encoding="utf-8-sig")
            # The script is parsed, never executed.
            check = 'param([string]$Source)\n$e=$null; $t=$null; [Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e) > $null; if($e.Count){$e | Out-String | Write-Error; exit 1}'
            wrapper = Path(tmp) / "parse.ps1"
            wrapper.write_text(check, encoding="utf-8-sig")
            checked = subprocess.run([update.powershell_path(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper), "-Source", str(path)],
                                     capture_output=True, text=True, timeout=20)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


@unittest.skipUnless(os.name == "nt" and NATIVE_WINDOWS, "opt-in disposable Windows updater transactions")
class WindowsHelperTests(unittest.TestCase):
    def test_silent_nsis_runs_only_after_exit_and_cancellation_preserves_install(self):
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Cubeon")
        except FileNotFoundError:
            key = None
        if key is not None:
            key.Close()
            self.skipTest("Disposable test requires no registered Cubeon installation")
        compiler = shutil.which("makensis")
        self.assertIsNotNone(compiler, "NSIS is required for the native updater gate")
        with tempfile.TemporaryDirectory(prefix="cubeon-native-update-") as tmp:
            root = Path(tmp)
            installed = root / "Games Ω $cash % with spaces"
            installed.mkdir()
            (installed / "_internal").mkdir()
            shutil.copy2(sys.executable, installed / "Cubeon.exe")
            (installed / "Uninstall Cubeon.exe").write_bytes(b"uninstall fixture")
            cache = root / "cache"
            cache.mkdir()
            script = root / "fixture.nsi"
            script.write_text('Unicode True\nRequestExecutionLevel user\nName "Update fixture"\nOutFile "' + str(root / "setup.exe") + '"\n'
                              'Section\nIfSilent +3\nSetErrorLevel 9\nQuit\nFileOpen $0 "$INSTDIR\\updated.marker" "w"\n'
                              'FileWrite $0 "installed silently"\nFileClose $0\nSectionEnd\n', encoding="utf-8-sig")
            subprocess.run([compiler, "/V2", str(script)], check=True, capture_output=True)
            download = root / "setup.exe"
            release = update.parse_release(metadata(download.read_bytes(), kind="windows"), "windows", "1.4.9")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Cubeon") as key:
                winreg.SetValueEx(key, "InstallDir", 0, winreg.REG_SZ, str(installed))
            try:
                for commit in (False, True):
                    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                    handoff = None
                    try:
                        target = update.Target("windows", installed / "Cubeon.exe")
                        directory, job = update.create_job(target, release, download, cache, parent_pid=parent.pid, args=[])
                        handoff = update.spawn_helper(directory, job)
                        update.wait_ready(handoff, threading.Event(), timeout=30)
                        with self.assertRaises(update.UpdateError), update.TargetLock(cache / "update.lock"):
                            pass
                        self.assertFalse((installed / "updated.marker").exists())
                        if commit:
                            handoff.commit()
                            time.sleep(.3)
                            self.assertFalse((installed / "updated.marker").exists())
                        else:
                            handoff.cancel()
                        parent.terminate(); parent.wait(timeout=3)
                        self.assertEqual(handoff.process.wait(timeout=30), 0, (directory / "helper.log").read_text())
                        self.assertEqual((directory / "result").read_text().strip(), "installed" if commit else "cancelled")
                    finally:
                        if parent.poll() is None:
                            parent.terminate(); parent.wait(timeout=3)
                        if handoff is not None and handoff.process.poll() is None:
                            handoff.cancel(); handoff.process.wait(timeout=5)
                self.assertEqual((installed / "updated.marker").read_text(), "installed silently")
            finally:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Cubeon")


if __name__ == "__main__":
    unittest.main()
