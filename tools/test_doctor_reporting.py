"""Offline checks for Doctor's user-facing reporting contract.

What this pins down:
  * a fix never hides the error that caused it - every inline row is
    "<what> : <error> -> <what was done>";
  * a check that could not run, or was stopped, never reads as "no problems";
  * the Settings / crash-report background runner reports success and failure
    instead of going silent, and its explicit click counts as approval.
"""
import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402

_sandbox_home.isolate()

from cubeon import config, doctor  # noqa: E402
from cubeon import doctor_ui  # noqa: E402


class ReportingTests(unittest.TestCase):
    def test_format_problem_keeps_error_and_action_together(self):
        fixed = {"item": "Sodium", "detail": "duplicate copies prevent loading",
                 "fixed": True, "fix": "disabled the older copy"}
        self.assertEqual(doctor.format_problem(fixed),
                         "Sodium: duplicate copies prevent loading \u2192 "
                         "disabled the older copy")
        unfixed = {"item": "Iris", "detail": "needs a newer Minecraft",
                   "fixed": False}
        self.assertEqual(doctor.format_problem(unfixed),
                         "Iris: needs a newer Minecraft")
        mods_entry = {"mod": "Fabric API", "detail": "needs fabric",
                      "fixed": True, "fix": "installed it"}
        self.assertEqual(doctor.format_problem(mods_entry),
                         "Fabric API: needs fabric \u2192 installed it")
        no_detail = {"item": "Pack", "fixed": True, "fix": "moved it"}
        self.assertEqual(doctor.format_problem(no_detail), "Pack: moved it")

    def test_report_lines_put_fixes_first_and_cap_with_an_honest_tail(self):
        report = {
            "fixed": [{"item": f"Fixed {i}", "detail": "broken",
                       "fixed": True, "fix": "repaired"} for i in range(3)],
            "unfixed": [{"item": f"Open {i}", "detail": "needs you",
                         "fixed": False} for i in range(3)],
        }
        lines = doctor.report_lines(report, limit=4)
        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[0].startswith("Fixed 0: broken"))
        self.assertTrue(lines[3].startswith("Open 0: needs you"))
        self.assertEqual(lines[-1], "2 more result(s) not shown.")

    def test_failed_check_never_reads_as_no_problems(self):
        report = {"checked": 2, "problems": [], "fixed": [], "unfixed": [],
                  "sections": {"plugins": {"checked": 0, "error": "boom"}},
                  "cancelled": False}
        summary = doctor._summarize(report)
        self.assertIn("could not run", summary)
        self.assertNotIn("no problems", summary.lower())
        self.assertIn("plugins", summary)

    def test_cancelled_check_says_so(self):
        report = {"checked": 4, "problems": [], "fixed": [], "unfixed": [],
                  "sections": {}, "cancelled": True}
        self.assertIn("stopped early", doctor._summarize(report).lower())

    def test_zero_checked_is_not_called_clean(self):
        report = {"checked": 0, "problems": [], "fixed": [], "unfixed": [],
                  "sections": {}, "cancelled": False}
        summary = doctor._summarize(report)
        self.assertIn("nothing was checked", summary.lower())
        self.assertNotIn("no problems", summary.lower())

    def test_a_crashed_section_is_reported_as_a_problem(self):
        with patch.object(doctor, "_plugins_section",
                          side_effect=RuntimeError("plugin scan exploded")):
            report = doctor.run_doctor(include=("plugins",), auto_fix=False,
                                       check_online=False)
        self.assertFalse(report["fixed"])
        self.assertEqual(len(report["unfixed"]), 1)
        entry = report["unfixed"][0]
        self.assertEqual(entry["kind"], "section-failed")
        self.assertIn("plugin scan exploded", entry["detail"])
        self.assertEqual(report["sections"]["plugins"]["error"],
                         "plugin scan exploded")
        self.assertIn("could not run", report["summary"])

    def test_bad_ram_is_explained_and_clamped_to_a_safe_value(self):
        with patch.object(config, "get_system_ram_mb", return_value=8192), \
             patch.object(config, "recommended_max_ram_mb", return_value=4096):
            detail, target = doctor._ram_problem({"ram_mb": "lots"})
            self.assertIn("isn't a whole number", detail)
            self.assertEqual(target, 4096)
            detail, target = doctor._ram_problem({"ram_mb": 512})
            self.assertIn("below the 1 GB minimum", detail)
            detail, target = doctor._ram_problem({"ram_mb": 999999})
            self.assertIn("larger than this machine", detail)
            self.assertLessEqual(target, 6144)
            self.assertIsNone(doctor._ram_problem({"ram_mb": 4096}))

    def test_background_runner_reports_and_treats_the_click_as_approval(self):
        report = {"checked": 1, "problems": [], "fixed": [], "unfixed": [],
                  "sections": {}, "summary": "Checked 1 item(s) - no problems found."}
        done, event = [], threading.Event()
        with patch.object(doctor, "run_doctor", return_value=report) as run:
            thread = doctor_ui.start_doctor_worker(
                mc_version="1.21.11", loader="fabric", version_id="1.21.11",
                include=("mods",), check_online=False,
                on_done=lambda result: (done.append(result), event.set()))
            self.assertIsNotNone(thread)
            thread.join(5)
        self.assertTrue(event.wait(1))
        self.assertEqual(done, [report])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["include"], ("mods",))
        self.assertFalse(kwargs["check_online"])
        self.assertTrue(kwargs["approve_cb"]({"action": "disable"}))
        self.assertTrue(kwargs["auto_fix"])

    def test_read_only_worker_never_passes_an_approver(self):
        done, event = [], threading.Event()
        with patch.object(doctor, "run_doctor", return_value={
                "checked": 0, "problems": [], "fixed": [], "unfixed": [],
                "sections": {}, "summary": "Nothing was checked."}) as run:
            thread = doctor_ui.start_doctor_worker(
                mc_version="1.21.11", loader="fabric",
                on_done=lambda result: (done.append(result), event.set()),
                approve_all=False)
            thread.join(5)
        self.assertTrue(event.wait(1))
        kwargs = run.call_args.kwargs
        self.assertIsNone(kwargs["approve_cb"])
        self.assertFalse(kwargs["auto_fix"])

    def test_crash_report_offers_a_local_check_for_its_instance(self):
        from ui.crash_report import build_crash_dialog

        dialog = build_crash_dialog(
            None, reason="Minecraft crashed", log_text="stack",
            mc_version="1.21.11", loader="fabric", version_id="1.21.11")
        button = dialog.actions[0]
        self.assertEqual(getattr(button, "data", None), "crash-local-doctor")
        self.assertFalse(button.disabled)
        unknown = build_crash_dialog(None, reason="Minecraft crashed",
                                     log_text="stack")
        self.assertTrue(unknown.actions[0].disabled,
                        "an unidentified instance must not offer a blind check")

    def test_background_runner_turns_a_crash_into_a_visible_report(self):
        done, event = [], threading.Event()
        with patch.object(doctor, "run_doctor",
                          side_effect=RuntimeError("doctor exploded")):
            thread = doctor_ui.start_doctor_worker(
                mc_version="1.21.11", loader="fabric",
                on_done=lambda result: (done.append(result), event.set()))
            thread.join(5)
        self.assertTrue(event.wait(1))
        self.assertIn("Could not complete this check", done[0]["summary"])
        self.assertIn("doctor exploded", done[0]["summary"])


if __name__ == "__main__":
    unittest.main()
