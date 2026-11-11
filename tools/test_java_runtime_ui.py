"""Exercise explicit Java setup callbacks without network or native windows."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import server, storage, thread_safe_ui, watchdog
from ui import java_runtime


class QueuedThread:
    jobs = []
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.jobs.append(self.target)


class JavaRuntimeUi(unittest.TestCase):
    def setUp(self):
        QueuedThread.jobs.clear()
        self.real_busy = storage.application_busy
        self.real_ensure = java_runtime.jre.ensure_java_for_version
        contexts = {
            "thread": patch.object(java_runtime.threading, "Thread", QueuedThread),
            "repaint": patch.object(thread_safe_ui, "refresh"),
            "busy": patch.object(storage, "application_busy", return_value=False),
            "describe": patch.object(java_runtime.instances, "describe", return_value={"loader": "fabric"}),
            "resolve": patch.object(java_runtime.versions, "resolve_mc_version", return_value="1.21.11"),
            "ensure": patch.object(java_runtime.jre, "ensure_java_for_version", return_value="/verified/bin/java"),
            "log": patch.object(java_runtime, "log"),
        }
        for name, context in contexts.items():
            setattr(self, name, context.start())
            self.addCleanup(context.stop)
        self.selected = "Survival 2.0"
        self.path = "  /custom/bin/java  "
        self.state = {}
        self.cfg = {"java_path": "/saved/bin/java"}
        self.ready_paths, self.claim_changes = [], []
        def ready(path):
            self.assertTrue(thread_safe_ui.TREE_LOCK._is_owned())
            self.ready_paths.append(path)
        def busy_changed():
            self.assertTrue(thread_safe_ui.TREE_LOCK._is_owned())
            self.claim_changes.append(self.state["java_runtime_busy"])
        self.page = SimpleNamespace(update=Mock())
        self.view = java_runtime.build_java_runtime_pane(
            self.page, cfg=self.cfg, launcher_state=self.state,
            get_version=lambda: self.selected, get_java_path=lambda: self.path,
            on_ready=ready, on_busy_change=busy_changed)
        self.model = self.view.java_runtime_model

    def click(self):
        self.model.check.on_click(None)

    def run_worker(self):
        QueuedThread.jobs.pop(0)()

    def test_build_is_passive_and_draws_native_controls(self):
        for service in (self.busy, self.describe, self.resolve, self.ensure):
            service.assert_not_called()
        self.assertEqual(QueuedThread.jobs, [])
        self.assertEqual(self.state, {})
        self.assertFalse(self.model.check.disabled)
        self.assertFalse(self.model.progress.visible)
        self.page.update.assert_not_called()

    def test_captured_instance_and_custom_path_singleflight_and_scoped_updates(self):
        self.describe.return_value = {"loader": "forge"}
        self.resolve.return_value = "1.8.9"
        self.click()
        self.selected, self.path = "26.3-fabric", "/different/java"
        self.click()
        self.assertEqual(len(QueuedThread.jobs), 1)
        self.assertTrue(self.state["java_runtime_busy"])
        self.assertTrue(self.model.check.disabled)
        self.assertEqual(self.model.check.content, "Checking Java…")
        self.run_worker()
        self.describe.assert_called_once_with("Survival 2.0", with_mods=False)
        self.resolve.assert_called_once_with("Survival 2.0")
        self.assertEqual(self.ensure.call_args.args, ("1.8.9-forge", "/custom/bin/java"))
        self.assertEqual(self.ready_paths, ["/verified/bin/java"])
        self.assertEqual(self.claim_changes, [True, False])
        self.assertFalse(self.state["java_runtime_busy"])
        self.assertEqual(self.model.check.content, "Check & repair Java")
        self.assertIn("verified and ready for 1.8.9", self.model.status.value)
        self.assertEqual(self.cfg, {"java_path": "/saved/bin/java"})
        self.assertTrue(all(call.args == (self.view,) for call in self.repaint.call_args_list))
        self.page.update.assert_not_called()

    def test_progress_and_cancellation_hold_claim_until_worker_acknowledges(self):
        def ensure(*args, status_cb, progress_cb, cancel_check):
            status_cb("Choosing Java 21")
            progress_cb(25, 100)
            self.assertEqual(self.model.progress.value, .25)
            self.model.cancel.on_click(None)
            self.click()
            self.assertTrue(self.state["java_runtime_busy"])
            self.assertTrue(self.model.check.disabled)
            self.assertTrue(self.model.cancel.disabled)
            self.assertEqual(self.model.check.content, "Cancelling…")
            self.assertEqual(QueuedThread.jobs, [])
            cancel_check()
        self.ensure.side_effect = ensure
        self.click()
        self.run_worker()
        self.assertFalse(self.state["java_runtime_busy"])
        self.assertFalse(self.model.check.disabled)
        self.assertFalse(self.model.cancel.visible)
        self.assertIn("cancelled", self.model.status.value)
        self.assertEqual(self.ready_paths, [])
        self.ensure.side_effect = None
        self.click()
        self.run_worker()
        self.assertEqual(self.ready_paths, ["/verified/bin/java"])

    def test_cancel_before_worker_avoids_java_work(self):
        self.click()
        self.model.cancel.on_click(None)
        self.assertTrue(self.state["java_runtime_busy"])
        self.run_worker()
        self.ensure.assert_not_called()
        self.assertFalse(self.state["java_runtime_busy"])
        self.assertIn("cancelled", self.model.status.value)

    def test_verified_runtime_uses_real_setup_without_downloading(self):
        self.ensure.side_effect = self.real_ensure
        with patch.object(java_runtime.jre, "java_status", return_value={
                "ok": True, "found": 21, "path": "/healthy/bin/java"}) as report, \
                patch.object(java_runtime.jre, "install_jre") as install:
            self.click()
            self.run_worker()
            report.assert_called_once()
            self.assertTrue(report.call_args.kwargs["force_probe"])
            install.assert_not_called()
            self.assertEqual(self.ready_paths, ["/healthy/bin/java"])

    def test_unusable_runtime_uses_real_setup_to_install_managed_java(self):
        self.ensure.side_effect = self.real_ensure
        with patch.object(java_runtime.jre, "java_status", return_value={
                "ok": False, "required": 21, "found": None}) as report, \
                patch.object(java_runtime.jre, "install_jre", return_value="/repaired/bin/java") as install:
            self.click()
            self.run_worker()
            self.assertTrue(report.call_args.kwargs["force_probe"])
            install.assert_called_once()
            self.assertEqual(install.call_args.args, (21,))
            self.assertEqual(self.ready_paths, ["/repaired/bin/java"])
            self.assertFalse(self.state["java_runtime_busy"])
            self.assertIn("verified and ready", self.model.status.value)

    def test_repaint_failure_does_not_strand_claim_before_worker_starts(self):
        self.repaint.side_effect = RuntimeError("detached view")
        self.click()
        self.assertEqual(len(QueuedThread.jobs), 1)
        self.assertTrue(self.state["java_runtime_busy"])
        self.run_worker()
        self.ensure.assert_called_once()
        self.assertFalse(self.state["java_runtime_busy"])
        self.assertFalse(self.model.check.disabled)
        self.assertEqual(self.model.check.content, "Check & repair Java")
        self.assertEqual(self.ready_paths, ["/verified/bin/java"])
        self.log.exception.assert_called()

    def test_failure_retry_and_thread_start_failure_release_claim(self):
        self.ensure.side_effect = java_runtime.jre.JreError("Download unavailable")
        self.click()
        self.run_worker()
        self.assertFalse(self.model.check.disabled)
        self.assertIn("Download unavailable", self.model.status.value)
        self.assertIn("Try again", self.model.status.value)
        self.ensure.side_effect = None
        self.click()
        self.run_worker()
        self.assertEqual(self.ready_paths, ["/verified/bin/java"])
        with patch.object(QueuedThread, "start", side_effect=RuntimeError("no thread")):
            self.click()
        self.assertFalse(self.state["java_runtime_busy"])
        self.assertFalse(self.model.check.disabled)
        self.assertIn("Couldn't start", self.model.status.value)

    def test_missing_selection_rust_and_optional_callback_failures(self):
        self.selected = None
        self.click()
        self.assertEqual(QueuedThread.jobs, [])
        self.selected = "cubeon-rust-26.3"
        self.describe.return_value = {"engine": "rust", "loader": "rust"}
        self.click()
        self.run_worker()
        self.ensure.assert_not_called()
        self.assertIn("does not use Java", self.model.status.value)
        self.describe.return_value = {"loader": "fabric"}
        self.model.on_ready = Mock(side_effect=RuntimeError("label detached"))
        self.model.on_busy_change = Mock(side_effect=RuntimeError("button detached"))
        self.click()
        self.run_worker()
        self.assertFalse(self.state["java_runtime_busy"])
        self.assertFalse(self.model.check.disabled)
        self.assertIn("verified and ready", self.model.status.value)

    def test_live_game_server_and_storage_gates_use_real_busy_check(self):
        self.busy.side_effect = self.real_busy
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(storage, "blocked", return_value=False) as blocked, \
                patch.object(watchdog, "stale_session", return_value=None) as session, \
                patch.object(server, "SERVERS_DIR", tmp), \
                patch.object(server, "is_server_running", return_value=False) as running:
            for key in ("running_version", "installing_version", "launching_version", "ending_session"):
                self.state[key] = "active"
                self.click()
                self.assertEqual(QueuedThread.jobs, [])
                self.state.pop(key)
            blocked.return_value = True
            self.click()
            blocked.return_value = False
            session.return_value = {"session_id": "recovered"}
            self.click()
            session.return_value = None
            (Path(tmp) / "1.21.11").mkdir()
            running.return_value = True
            self.click()
            self.assertEqual(QueuedThread.jobs, [])
            self.ensure.assert_not_called()
            self.assertNotIn("java_runtime_busy", self.state)
            running.return_value = False
            self.click()
            self.assertEqual(len(QueuedThread.jobs), 1)
            self.run_worker()
            self.assertEqual(self.ready_paths, ["/verified/bin/java"])


if __name__ == "__main__":
    unittest.main()
