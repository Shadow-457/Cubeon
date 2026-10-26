"""Offline checks that Doctor cannot change existing mods without approval."""
import asyncio
import json
import os
import sys
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import doctor, mods
from cubeon.doctor_ui import make_mod_change_approver


class DoctorConsentTests(unittest.TestCase):
    def setUp(self):
        self.version = "1.21.11"
        self.loader = "fabric"
        self.profile = mods.get_profile_dir(self.version, self.loader)
        for filename in os.listdir(self.profile):
            os.remove(os.path.join(self.profile, filename))
        self.network = patch.object(mods, "get_mod_versions", return_value=[])
        self.network.start()
        self.addCleanup(self.network.stop)

    def jar(self, filename, identity="demo", version="1.0", breaks=None):
        path = os.path.join(self.profile, filename)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("fabric.mod.json", json.dumps({
                "id": identity, "name": identity, "version": version,
                "breaks": breaks or {},
            }))
        return path

    def run_doctor(self, **kwargs):
        return mods.mod_doctor(self.version, self.loader, check_online=False, **kwargs)

    def duplicates(self):
        self.jar("demo-1.0.jar", version="1.0")
        self.jar("demo-2.0.jar", version="2.0")

    def test_duplicate_cleanup_defaults_to_report_only(self):
        self.duplicates()
        with patch.object(mods, "toggle_mod") as toggle, patch.object(mods, "delete_mod") as delete:
            result = self.run_doctor()
        toggle.assert_not_called()
        delete.assert_not_called()
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "demo-1.0.jar")))
        self.assertFalse(result["fixed"])
        self.assertFalse(result["changes"][0]["approved"])

    def test_confirmed_duplicate_cleanup_keeps_a_reversible_copy(self):
        self.duplicates()
        requests = []
        def approve(change):
            self.assertTrue(os.path.isfile(os.path.join(self.profile, "demo-1.0.jar")))
            requests.append(change)
            return True
        result = self.run_doctor(approve_cb=approve)
        self.assertTrue(result["fixed"])
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "demo-1.0.jar.disabled")))
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "demo-2.0.jar")))
        self.assertEqual(requests[0]["mods"][0]["filename"], "demo-1.0.jar")
        self.assertEqual(requests[0]["mc_version"], self.version)
        self.assertIn("Nothing will be deleted", requests[0]["reason"])
        self.assertFalse(self.run_doctor()["changes"])

    def test_cancel_and_callback_failure_never_disable_mods(self):
        self.duplicates()
        def broken(change):
            raise RuntimeError("dialog unavailable")
        for approve in (lambda change: False, lambda change: "yes", broken):
            result = self.run_doctor(approve_cb=approve)
            self.assertFalse(result["fixed"])
            self.assertTrue(os.path.isfile(os.path.join(self.profile, "demo-1.0.jar")))

    def test_changed_files_invalidate_an_earlier_approval(self):
        self.duplicates()
        def approve(change):
            with open(os.path.join(self.profile, "demo-1.0.jar"), "ab") as output:
                output.write(b"changed")
            return True
        result = self.run_doctor(approve_cb=approve)
        self.assertFalse(result["fixed"])
        self.assertFalse(result["changes"][0]["approved"])
        self.assertIn("files changed", result["changes"][0]["reason"])

    def test_repair_cannot_overwrite_an_existing_disabled_backup(self):
        self.duplicates()
        backup = self.jar("demo-1.0.jar.disabled", version="backup")
        with open(backup, "rb") as source:
            before = source.read()
        result = self.run_doctor(approve_cb=lambda change: True)
        self.assertFalse(result["fixed"])
        with open(backup, "rb") as source:
            self.assertEqual(source.read(), before)

    def test_missing_online_listing_cannot_disprove_an_installed_mod(self):
        self.jar("demo-1.0.jar")
        mods.record_mod_source(self.profile, "demo-1.0.jar", project_id="demo")
        with patch.object(mods, "get_mod_download", return_value=None):
            result = mods.mod_doctor(self.version, self.loader, approve_cb=lambda change: False)
        self.assertFalse(result["fixed"])
        self.assertFalse(result["changes"])
        self.assertTrue(result["unfixed"])
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "demo-1.0.jar")))

    def test_conflict_cancel_preserves_both_mods(self):
        self.jar("first-1.0.jar", "first", breaks={"second": "*"})
        self.jar("second-1.0.jar", "second")
        result = self.run_doctor(approve_cb=lambda change: False)
        self.assertFalse(result["fixed"])
        self.assertEqual(result["changes"][0]["mods"][0]["filename"], "second-1.0.jar")
        self.assertIn("first", result["changes"][0]["reason"])
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "second-1.0.jar")))

    def test_confirmed_conflict_disables_only_the_named_mod(self):
        self.jar("first-1.0.jar", "first", breaks={"second": "*"})
        self.jar("second-1.0.jar", "second")
        result = self.run_doctor(approve_cb=lambda change: True)
        self.assertTrue(result["fixed"])
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "first-1.0.jar")))
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "second-1.0.jar.disabled")))

    def test_replacement_cancel_prevents_download_and_cleanup(self):
        self.jar("demo-1.0.jar")
        mods.record_mod_source(self.profile, "demo-1.0.jar", project_id="demo")
        with patch.object(mods, "download_mod") as download:
            fixed = mods._doctor_download({"url": "offline", "filename": "demo-2.0.jar"},
                                         mc_version=self.version, loader=self.loader, project_id="demo")
        self.assertFalse(fixed)
        download.assert_not_called()

    def test_confirmed_replacement_preserves_the_old_jar(self):
        self.jar("demo-1.0.jar")
        mods.record_mod_source(self.profile, "demo-1.0.jar", project_id="demo")
        def download(url, filename, **kwargs):
            self.assertTrue(kwargs["preserve_existing"])
            return self.jar(filename, version="2.0")
        with patch.object(mods, "download_mod", side_effect=download):
            fixed = mods._doctor_download({"url": "offline", "filename": "demo-2.0.jar"},
                                         mc_version=self.version, loader=self.loader, project_id="demo",
                                         approve_cb=lambda change: True)
        self.assertTrue(fixed)
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "demo-1.0.jar.disabled")))
        self.assertTrue(os.path.isfile(os.path.join(self.profile, "demo-2.0.jar")))

    def test_new_dependencies_do_not_require_destructive_change_approval(self):
        with patch.object(mods, "download_mod") as download:
            fixed = mods._doctor_download({"url": "offline", "filename": "dependency.jar"},
                                         mc_version=self.version, loader=self.loader)
        self.assertTrue(fixed)
        self.assertTrue(download.call_args.kwargs["preserve_existing"])

    def test_shared_doctor_forwards_and_reports_approval(self):
        self.duplicates()
        report = doctor.run_doctor(self.version, self.loader, check_online=False, include=["mods"])
        self.assertFalse(report["changes"][0]["approved"])
        report = doctor.run_doctor(self.version, self.loader, check_online=False, include=["mods"],
                                   approve_cb=lambda change: True)
        self.assertTrue(report["changes"][0]["approved"])
        self.assertTrue(report["fixed"])


class ApprovalPage:
    def __init__(self, decision=None):
        self.decision = decision
        self.dialog = None
        self.shown = 0

    def run_task(self, target):
        asyncio.run(target())

    def show_dialog(self, dialog):
        self.dialog = dialog
        self.shown += 1
        if self.decision == "dismiss":
            dialog.on_dismiss(None)
        elif self.decision is not None:
            dialog.actions[1 if self.decision else 0].on_click(None)

    def close(self, dialog):
        dialog.open = False


class ApprovalDialogTests(unittest.TestCase):
    change = {"action": "disable", "mc_version": "1.21.11", "loader": "fabric",
              "reason": "First conflicts with Second.",
              "mods": [{"name": "Second", "filename": "second.jar"}]}

    def test_dialog_requires_explicit_confirmation(self):
        for decision in (False, True, "dismiss"):
            page = ApprovalPage(decision)
            self.assertEqual(make_mod_change_approver(page)(self.change), decision is True)
            self.assertTrue(page.dialog.modal)
            self.assertEqual(page.shown, 1)

    def test_timeout_and_missing_ui_fail_closed(self):
        page = ApprovalPage()
        self.assertFalse(make_mod_change_approver(page, timeout=0)(self.change))
        page.dialog.actions[1].on_click(None)
        self.assertFalse(make_mod_change_approver(ApprovalPage(), timeout=0)(self.change))

    def test_approval_never_blocks_the_running_ui_loop(self):
        page = ApprovalPage(True)
        async def call():
            return make_mod_change_approver(page)(self.change)
        self.assertFalse(asyncio.run(call()))
        self.assertEqual(page.shown, 0)

    def test_one_page_reuses_one_serialized_approver(self):
        page = ApprovalPage(False)
        self.assertIs(make_mod_change_approver(page), make_mod_change_approver(page))


if __name__ == "__main__":
    unittest.main()
