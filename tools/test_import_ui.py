"""Settings has one inline instance importer, with no individual-file workflow."""
import inspect
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
import _sandbox_home
home = _sandbox_home.isolate()
os.environ["CUBEON_GAME_DIR"] = str(Path(home) / "game")
import app_driver
from _fuzz_common import walk


class SettingsImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(threading.Thread, "start"):
            cls.driver = app_driver.build_headless()
            cls.driver.open_tab("settings")
        switch = inspect.getclosurevars(cls.driver.tabs()["settings"].on_click).nonlocals["switch_tab"]
        cls.settings = inspect.getclosurevars(switch).nonlocals["tabs"]["settings"]
        cls.settings.select_section("import")
        cls.pane = next(c for c in walk(cls.settings) if getattr(c, "data", "") == "settings-pane-import")
        cls.view = next(c for c in walk(cls.pane) if getattr(c, "data", "") == "fastclient-import-section")

    def test_import_has_its_own_settings_section(self):
        self.assertTrue(self.pane.visible)
        self.assertIn("Import", [getattr(c, "value", "") for c in walk(self.settings)])

    def test_no_individual_file_import_controls(self):
        texts = [str(getattr(c, "value", "") or getattr(c, "content", "")) for c in walk(self.pane)]
        self.assertFalse(any("Import individual" in text or "Scan a folder" in text or "Import to..." in text for text in texts))

    def test_inline_importer_is_idle_until_requested(self):
        model = self.view.import_model
        self.assertFalse(hasattr(model, "dialog"))
        self.assertEqual(model.phase, "choose")
        self.assertEqual(model.rows.controls, [])
        self.assertFalse(model.scan.disabled)


if __name__ == "__main__":
    unittest.main()
