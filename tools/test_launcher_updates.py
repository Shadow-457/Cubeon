"""Offline tests for consent, release checks, downloads and update handoff."""
import hashlib
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import types
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import config, updater, update_install
from ui.update_prompt import UpdatePrompt


def release(payload=b"new app", channel="stable", version="2.0.0", kind="linux"):
    return {"version": version, "url": updater.DOWNLOAD_URL, "channel": channel,
            "assets": {kind: {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                               "url": f"{updater.UPDATE_SERVICE}/updates/{channel}/{kind}?version={version}"}}}


class Response:
    status_code = 200
    def __init__(self, chunks):
        self.chunks = chunks
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def raise_for_status(self):
        pass
    def iter_content(self, **kwargs):
        yield from self.chunks


class FakePage:
    def __init__(self):
        self.shown = []
        self._dialogs = Mock(controls=[])
    def show_dialog(self, dialog):
        self.shown.append(dialog)
        self._dialogs.controls.append(dialog)
    def pop_dialog(self):
        self._dialogs.controls.pop()
    def update(self):
        pass


class LauncherUpdates(unittest.TestCase):
    def main_function(self, name, namespace):
        tree = ast.parse((Path(__file__).resolve().parents[1]/"main.py").read_text())
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
        return namespace[name]

    def test_stable_default_and_public_feed_credentials(self):
        self.assertEqual(config.DEFAULT_CONFIG["update_channel"], "stable")
        response = Mock()
        response.json.return_value = {"tag_name": "v2.0.0", "assets": {}}
        with patch.object(updater.requests, "get", return_value=response) as get:
            info = updater.check_for_updates(token="secret")
        self.assertEqual(info["channel"], "stable")
        self.assertEqual(get.call_args.args[0], updater.DEFAULT_FEED)
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])

    def test_stable_beta_filtering_and_numeric_versions(self):
        data = [{"tag_name": "v2.0.0"}, {"tag_name": "v2.0.9", "prerelease": True},
                {"tag_name": "v2.0.10", "prerelease": True}, {"tag_name": "v9.0.0", "draft": True}]
        response = Mock()
        response.json.return_value = data
        with patch.object(updater.requests, "get", return_value=response) as get:
            self.assertEqual(updater.check_for_updates()["version"], "2.0.0")
            self.assertEqual(updater.check_for_updates(channel="beta")["version"], "2.0.10")
            self.assertEqual(get.call_args.args[0], updater.DEFAULT_BETA_FEED)
            response.json.return_value = {"tag_name": "v2.0.1", "prerelease": True}
            self.assertIsNone(updater.check_for_updates())

    def test_no_update_or_network_error_calls_no_ui(self):
        callback = Mock()
        for result in (None, OSError("offline")):
            with patch.object(updater, "check_for_updates", side_effect=result if isinstance(result, Exception) else None,
                              return_value=None):
                thread = updater.check_in_background(callback)
                thread.join(2)
                self.assertFalse(thread.is_alive())
        callback.assert_not_called()

    def test_actual_announcer_prompts_despite_saved_notice_and_ignores_closed_page(self):
        page = FakePage()
        active = threading.Event()
        active.set()
        holder = {"value": None}
        from cubeon import thread_safe_ui
        namespace = {"_update_active": active, "_update_prompt": holder, "page": page,
                     "cfg": {"update_channel": "stable", updater.NOTICE_SEEN_KEY: "2.0.0"},
                     "updater": updater, "thread_safe_ui": thread_safe_ui,
                     "core": Mock(), "logging": __import__("logging"),
                     "_update_busy": lambda: False, "_install_app_update": Mock()}
        announce = self.main_function("_announce_update", namespace)
        with patch.object(update_install, "download_update") as download:
            announce(release())
            self.assertEqual(len(page.shown), 1)
            self.assertIsNotNone(holder["value"])
            holder["value"].skip.on_click(None)
            active.clear()
            announce(release())
            self.assertEqual(len(page.shown), 1)
            download.assert_not_called()
        namespace["core"].save_config.assert_not_called()

    def test_exit_handoff_starts_one_helper_even_if_exit_paths_race(self):
        namespace = {"_pending_app_update": {"job": {"fixture": True}},
                     "_app_update_lock": threading.Lock(), "logging": __import__("logging")}
        handoff = self.main_function("_handoff_app_update", namespace)
        with patch.object(update_install, "launch_install") as launch:
            threads = [threading.Thread(target=handoff) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)
            launch.assert_called_once_with({"fixture": True})
            self.assertFalse(handoff())

    def test_open_and_skip_never_download_or_install(self):
        page, install = FakePage(), Mock()
        with patch.object(update_install, "download_update") as download:
            prompt = UpdatePrompt(page, release(), busy=lambda: False, install=install,
                                  target=update_install.InstallTarget("linux", Path("/tmp/app"))).open()
            self.assertEqual(len(page.shown), 1)
            self.assertEqual(prompt.skip.content, "Skip")
            self.assertEqual(prompt.update.content, "Update")
            prompt.skip.on_click(None)
            self.assertEqual(prompt.phase, "skipped")
            download.assert_not_called()
            install.assert_not_called()
            # A later startup can offer the SAME version; saved OS notice is irrelevant.
            UpdatePrompt(FakePage(), release(), busy=lambda: False, install=install).open()

    def test_one_update_click_installs_and_failed_close_is_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Cubeon.AppImage"
            path.write_bytes(b"new app")
            page, install = FakePage(), Mock()
            prompt = UpdatePrompt(page, release(), busy=lambda: False, install=install,
                                  target=update_install.InstallTarget("linux", Path(tmp)/"installed")).open()
            with patch.object(update_install, "download_update", return_value=path) as download, \
                    patch("ui.update_prompt.threading.Thread") as thread, \
                    patch.object(update_install, "prepare_install", return_value={"job": "fixture"}), \
                    patch("ui.update_prompt.thread_safe_ui.refresh"):
                thread.side_effect = lambda *, target, **kw: Mock(start=target)
                prompt.update.on_click(None)
                download.assert_called_once()
                self.assertEqual(prompt.phase, "closing")
                self.assertEqual(prompt.update.content, "Restart")
                self.assertEqual(prompt.progress.value, 1)
                prompt.update.on_click(None)
                install.assert_called_once()
                self.assertEqual(prompt.phase, "closing")
                install.call_args.args[1]("close failed")
                self.assertEqual(prompt.phase, "ready")
                self.assertFalse(prompt.update.disabled)

    def test_busy_and_manual_builds_never_download(self):
        for target in (update_install.InstallTarget("linux", Path("/tmp/app")),
                       update_install.InstallTarget("linux")):
            prompt = UpdatePrompt(FakePage(), release(), busy=lambda: True, install=Mock(), target=target)
            with patch.object(update_install, "download_update") as download, \
                    patch("ui.update_prompt.thread_safe_ui.refresh"), \
                    patch("ui.update_prompt.webbrowser.open") as browser:
                prompt.update.on_click(None)
                download.assert_not_called()
                browser.assert_not_called()
                self.assertEqual(prompt.phase, "offered")
                if not target.can_install:
                    prompt.manual.on_click(None)
                    browser.assert_called_once_with(release()["assets"]["linux"]["url"])

    def test_verified_download_and_partial_cleanup(self):
        target = update_install.InstallTarget("linux", Path("/tmp/app"))
        with tempfile.TemporaryDirectory() as tmp:
            progress = Mock()
            with patch.object(updater.requests, "get", return_value=Response([b"new ", b"app"])) as get:
                path = update_install.download_update(release(), target, threading.Event(), progress, tmp)
                self.assertEqual(path.read_bytes(), b"new app")
                self.assertEqual(progress.call_args.args, (7, 7))
                self.assertNotIn("headers", get.call_args.kwargs)
            for payload in ([b"bad app"], [b"new"], [b"new app extra"]):
                before = set(Path(tmp).iterdir())
                with patch.object(updater.requests, "get", return_value=Response(payload)):
                    with self.assertRaises(ValueError):
                        update_install.download_update(release(), target, threading.Event(), directory=tmp)
                self.assertEqual(set(Path(tmp).iterdir()), before)

    def test_cancel_during_download_cleans_partial_file(self):
        cancel = threading.Event()
        target = update_install.InstallTarget("linux", Path("/tmp/app"))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(updater.requests, "get", return_value=Response([b"new ", b"app"])):
            with self.assertRaises(update_install.UpdateCancelled):
                update_install.download_update(release(), target, cancel,
                                               lambda *args: cancel.set(), tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_untrusted_or_unverifiable_assets_never_download(self):
        target = update_install.InstallTarget("linux", Path("/tmp/app"))
        for field, value in (("url", "https://attacker.test/file"), ("sha256", None),
                             ("size", 0), ("size", 2**40)):
            info = release()
            info["assets"]["linux"][field] = value
            with patch.object(updater.requests, "get") as get:
                with self.assertRaises(ValueError):
                    update_install.download_update(info, target, threading.Event())
                get.assert_not_called()
        info = release(channel="beta")
        self.assertIsNotNone(update_install.release_asset(info, target))
        info["assets"]["linux"]["url"] = release()["assets"]["linux"]["url"]
        self.assertIsNone(update_install.release_asset(info, target))

    def test_missing_checksum_stays_inline_without_browser_or_download(self):
        info = release()
        info["assets"]["linux"]["sha256"] = None
        target = update_install.InstallTarget("linux", Path("/tmp/app"))
        prompt = UpdatePrompt(FakePage(), info, busy=lambda: False, install=Mock(), target=target)
        with patch("ui.update_prompt.webbrowser.open") as browser, \
                patch.object(update_install, "download_update") as download:
            prompt.update.on_click(None)
            browser.assert_not_called()
            download.assert_not_called()
            self.assertEqual(prompt.phase, "offered")
            self.assertIn("missing a verified update", prompt.status.value)

    def test_readonly_appimage_in_writable_directory_updates_inside_launcher(self):
        if sys.platform != "linux":
            self.skipTest("AppImage detection")
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp)/"Cubeon.AppImage"
            image.write_bytes(b"old app")
            image.chmod(0o555)
            with patch.dict(os.environ, {"APPIMAGE":str(image)}), \
                    patch.object(sys, "frozen", True, create=True), \
                    patch("cubeon.update_install.platform.machine", return_value="x86_64"):
                target = update_install.installation_target()
                self.assertEqual(target.path, image)
                self.assertTrue(target.can_install)
                prompt = UpdatePrompt(FakePage(),release(),busy=lambda:False,install=Mock(),target=target)
                with patch.object(update_install,"download_update",return_value=Path(tmp)/"download") as download, \
                        patch("ui.update_prompt.threading.Thread") as thread, \
                        patch("ui.update_prompt.webbrowser.open") as browser:
                    thread.side_effect=lambda *,target,**kw: Mock(start=target)
                    prompt.update.on_click(None)
                    download.assert_called_once()
                    browser.assert_not_called()
                    self.assertEqual(prompt.update.content,"Restart")
                with patch.dict(os.environ,{"APPIMAGE":"","CUBEON_APPIMAGE_PATH":str(image)}):
                    self.assertEqual(update_install.installation_target().path,image)

    def test_busy_checks_actual_game_and_server_ownership(self):
        from cubeon import watchdog, server
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, "SERVERS_DIR", tmp), \
                patch.object(watchdog, "stale_session", return_value=None), \
                patch.object(server, "is_server_running", return_value=False) as running:
            self.assertFalse(update_install.application_busy({}))
            self.assertTrue(update_install.application_busy({"launching_version": "1.21"}))
            (Path(tmp)/"server-only-version").mkdir()
            running.return_value = True
            self.assertTrue(update_install.application_busy({}))
        with patch.object(watchdog, "stale_session", return_value={"pid": 123}):
            self.assertTrue(update_install.application_busy({}))

    def test_appimage_helper_replaces_atomically_and_keeps_backup(self):
        if sys.platform != "linux":
            self.skipTest("Linux helper")
        with tempfile.TemporaryDirectory(prefix="cubeon update '") as tmp:
            root = Path(tmp)
            app, downloaded = root/"Cubeon.AppImage", root/"download"
            app.write_bytes(b"old app")
            app.chmod(0o555)
            previous=Path(str(app)+".cubeon-previous")
            previous.write_bytes(b"older app")
            previous.chmod(0o555)
            downloaded.write_bytes(b"new app")
            target = update_install.InstallTarget("linux", app)
            job = update_install.prepare_install(release(), target, downloaded, reopen=False)
            self.assertEqual(app.read_bytes(), b"old app")  # preparation does nothing
            # A short-lived parent stands in for Cubeon; the helper must wait.
            parent = subprocess.Popen(["sleep", "0.15"])
            job["command"][2] = str(parent.pid)
            helper = subprocess.Popen(job["command"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(app.read_bytes(), b"old app")
            parent.wait()
            stdout, stderr = helper.communicate(timeout=5)
            self.assertEqual(helper.returncode, 0, (stdout, stderr))
            self.assertEqual(app.read_bytes(), b"new app")
            self.assertEqual(Path(str(app)+".cubeon-previous").read_bytes(), b"old app")
            self.assertTrue(os.access(app, os.X_OK))

    def test_appimage_helper_reopens_new_version_with_fresh_environment(self):
        if sys.platform != "linux":
            self.skipTest("Linux helper")
        with tempfile.TemporaryDirectory() as tmp:
            app, downloaded, marker = Path(tmp)/"app", Path(tmp)/"download", Path(tmp)/"reopened"
            app.write_bytes(b"old app")
            app.chmod(0o555)
            payload=b'#!/bin/sh\nprintf "%s:%s:%s:%s" "$PYINSTALLER_RESET_ENVIRONMENT" "${APPIMAGE:-}" "${APPDIR:-}" "${CUBEON_APPIMAGE_PATH:-}" > "$CUBEON_UPDATE_TEST_MARKER"\n'
            downloaded.write_bytes(payload)
            job=update_install.prepare_install(release(payload),update_install.InstallTarget("linux",app),downloaded)
            job["command"][2]="2147483647"
            env=dict(os.environ,APPIMAGE="old-image",APPDIR="old-mount",CUBEON_APPIMAGE_PATH="old-image",CUBEON_UPDATE_TEST_MARKER=str(marker))
            result=subprocess.run(job["command"],env=env,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            deadline=time.monotonic()+2
            while not marker.is_file() and time.monotonic()<deadline:
                time.sleep(0.01)
            self.assertEqual(marker.read_text(),"1:::")
            self.assertEqual(app.read_bytes(),payload)

    def test_helper_rechecks_checksum_after_preparation(self):
        if sys.platform != "linux":
            self.skipTest("Linux helper")
        with tempfile.TemporaryDirectory() as tmp:
            app, downloaded = Path(tmp)/"app", Path(tmp)/"download"
            app.write_bytes(b"old app")
            downloaded.write_bytes(b"new app")
            job = update_install.prepare_install(release(), update_install.InstallTarget("linux", app),
                                                 downloaded, reopen=False)
            downloaded.write_bytes(b"corrupt")
            job["command"][2] = "2147483647"  # no such parent
            result = subprocess.run(job["command"], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(app.read_bytes(), b"old app")

    def test_windows_helper_preserves_spaces_without_inserting_script_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            download = Path(tmp)/"setup.exe"
            download.write_bytes(b"new app")
            info = release(kind="windows")
            target = update_install.InstallTarget("windows", Path("C:/My Games/Cubeon"))
            job = update_install.prepare_install(info, target, download)
            self.assertEqual(job["command"][0], "powershell.exe")
            data = json.loads((Path(tmp)/"install.json").read_text())
            self.assertEqual(data["target"], str(target.path))
            self.assertNotIn(str(target.path), (Path(tmp)/"install.ps1").read_text())

    def test_windows_detection_requires_this_registered_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            exe = folder / "Cubeon.exe"
            exe.write_bytes(b"exe")
            (folder / "_internal").mkdir()
            (folder/"Uninstall Cubeon.exe").write_bytes(b"uninstaller")
            registry = types.SimpleNamespace(HKEY_CURRENT_USER=1, OpenKey=Mock(), QueryValueEx=Mock())
            registry.OpenKey.return_value.__enter__ = Mock(return_value=1)
            registry.OpenKey.return_value.__exit__ = Mock()
            with patch.object(sys, "platform", "win32"), patch.object(sys, "executable", str(exe)), \
                    patch.object(sys, "frozen", True, create=True), patch.dict(sys.modules, {"winreg": registry}):
                registry.QueryValueEx.return_value = (str(folder), 1)
                self.assertTrue(update_install.installation_target().can_install)
                registry.QueryValueEx.return_value = (str(folder / "another copy"), 1)
                self.assertFalse(update_install.installation_target().can_install)

    def test_game_start_during_download_defers_install_until_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "download"
            path.write_bytes(b"new app")
            busy, install = Mock(return_value=False), Mock()
            prompt = UpdatePrompt(FakePage(), release(), busy=busy, install=install,
                                  target=update_install.InstallTarget("linux", Path(tmp) / "app"))
            def download(*args):
                busy.return_value = True
                return path
            with patch.object(update_install, "download_update", side_effect=download), \
                    patch("ui.update_prompt.threading.Thread") as thread:
                thread.side_effect = lambda *, target, **kw: Mock(start=target)
                prompt._update()
            self.assertEqual(prompt.phase, "ready")
            install.assert_not_called()
            busy.return_value = False
            with patch.object(update_install, "prepare_install", return_value={"job": "fixture"}):
                prompt._update()
            install.assert_called_once()

    def test_prepare_error_is_visible_and_retryable(self):
        prompt = UpdatePrompt(FakePage(), release(), busy=lambda: False, install=Mock(),
                              target=update_install.InstallTarget("linux", Path("/tmp/app")))
        prompt.phase = "ready"
        prompt.download = Path("/tmp/download")
        with patch.object(update_install, "prepare_install", side_effect=OSError("Disk is full")):
            prompt._update()
        self.assertEqual(prompt.phase, "ready")
        self.assertEqual(prompt.status.value, "Disk is full")
        self.assertFalse(prompt.update.disabled)

    def test_helper_failure_is_reported_once_on_next_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "install-result.txt"
            result.write_text("\ufefffailed\nInstallation failed", encoding="utf-8")
            self.assertEqual(update_install.take_install_failure(tmp), "Installation failed")
            self.assertIsNone(update_install.take_install_failure(tmp))

    def test_debian_detection_requires_package_ownership_and_authorizer(self):
        with patch.object(sys, "platform", "linux"), \
                patch.object(sys, "executable", "/opt/cubeon/Cubeon"), \
                patch.object(sys, "frozen", True, create=True), \
                patch.dict(os.environ, {"APPIMAGE": "", "CUBEON_APPIMAGE_PATH": ""}), \
                patch("cubeon.update_install.shutil.which", side_effect=lambda name: "/usr/bin/" + name), \
                patch("cubeon.update_install.subprocess.run", return_value=Mock(returncode=0, stdout="cubeon: /opt/cubeon/Cubeon\n")) as query:
            self.assertEqual(update_install.installation_target().asset, "linux-deb")
            self.assertTrue(update_install.installation_target().can_install)
            query.return_value.stdout = "someone-else: /opt/cubeon/Cubeon\n"
            self.assertFalse(update_install.installation_target().can_install)

    def test_debian_helper_waits_verifies_and_invokes_package_manager(self):
        with tempfile.TemporaryDirectory(prefix="cubeon deb '") as tmp:
            root = Path(tmp)
            download = root / "Cubeon.deb"
            download.write_bytes(b"new app")
            marker = root / "apt-arguments"
            authorize, apt = root / "authorize", root / "apt"
            authorize.write_text('#!/bin/sh\nexec "$@"\n')
            apt.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CUBEON_TEST_APT_ARGS"\n')
            authorize.chmod(0o755)
            apt.chmod(0o755)
            with patch("cubeon.update_install.shutil.which", side_effect=lambda name: str(authorize if name == "pkexec" else apt)):
                job = update_install.prepare_install(release(kind="linux-deb"),
                    update_install.InstallTarget("linux-deb", Path("/opt/cubeon/Cubeon")), download, reopen=False)
            job["command"][2] = "2147483647"
            env = dict(os.environ, CUBEON_TEST_APT_ARGS=str(marker))
            installed = subprocess.run(job["command"], env=env, capture_output=True, timeout=5)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(marker.read_text().splitlines(), ["install", "--assume-yes", "--", str(download)])
            self.assertFalse(download.exists())
            self.assertEqual(Path(job["result"]).read_text().strip(), "success")
            marker.unlink()
            download.write_bytes(b"tampered")
            failed = subprocess.run(job["command"], env=env, capture_output=True, timeout=5)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(marker.exists())
            self.assertTrue(Path(job["result"]).read_text().startswith("failed"))

    def test_changed_release_refreshes_offer_and_completes_original_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "download"
            path.write_bytes(b"new app")
            install = Mock()
            prompt = UpdatePrompt(FakePage(), release(), busy=lambda: False, install=install,
                                  target=update_install.InstallTarget("linux", Path(tmp) / "app"))
            prompt.phase = "downloading"
            newer = release(version="2.0.1")
            with patch.object(update_install, "download_update", side_effect=[update_install.UpdateReleaseChanged(), path]) as download, \
                    patch.object(updater, "check_for_updates", return_value=newer), \
                    patch.object(update_install, "prepare_install", return_value={"fixture": True}):
                prompt._download()
            self.assertEqual(download.call_count, 2)
            self.assertEqual(prompt.info["version"], "2.0.1")
            self.assertEqual(prompt.phase, "closing")
            install.assert_called_once()

    def test_background_check_reports_no_update_and_offline_failure(self):
        complete, failed = Mock(), Mock()
        with patch.object(updater, "check_for_updates", return_value=None):
            updater.check_in_background(Mock(), on_complete=complete, on_error=failed).join(2)
        complete.assert_called_once_with(None)
        with patch.object(updater, "check_for_updates", side_effect=OSError("offline")):
            updater.check_in_background(Mock(), on_complete=complete, on_error=failed).join(2)
        failed.assert_called_once()

    def test_settings_check_deduplicates_and_can_retry_after_offline(self):
        active = threading.Event()
        active.set()
        running = threading.Event()
        status = Mock()
        namespace = {"_update_active": active, "_update_check_running": running,
                     "_update_check_lock": threading.Lock(), "_update_prompt": {"value": None},
                     "_announce_update": Mock(), "set_status": status, "updater": updater,
                     "cfg": {"update_channel": "beta"}}
        check = self.main_function("_check_app_update", namespace)
        with patch.object(updater, "check_in_background") as background:
            check()
            check()
            background.assert_called_once()
            self.assertEqual(background.call_args.kwargs["channel"], "beta")
            background.call_args.kwargs["on_error"](OSError("offline"))
            self.assertFalse(running.is_set())
            check()
            self.assertEqual(background.call_count, 2)
            background.call_args.kwargs["on_complete"](None)
            self.assertIn("up to date", status.call_args.args[0])

    def test_failed_appimage_update_reopens_previous_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app, download, marker = root / "app", root / "download", root / "reopened"
            old = b'#!/bin/sh\nprintf "old:%s" "$PYINSTALLER_RESET_ENVIRONMENT" > "$CUBEON_TEST_RECOVERY"\n'
            app.write_bytes(old)
            app.chmod(0o755)
            download.write_bytes(b"new app")
            job = update_install.prepare_install(release(), update_install.InstallTarget("linux", app), download)
            job["command"][2] = "2147483647"
            download.write_bytes(b"tampered")
            failed = subprocess.run(job["command"], env=dict(os.environ, CUBEON_TEST_RECOVERY=str(marker)),
                                    capture_output=True, timeout=5)
            self.assertNotEqual(failed.returncode, 0)
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(marker.read_text(), "old:1")
            self.assertEqual(app.read_bytes(), old)
            self.assertTrue(Path(job["result"]).read_text().startswith("failed"))


if __name__ == "__main__":
    unittest.main()
