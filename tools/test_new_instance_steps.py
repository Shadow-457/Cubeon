"""New Instance progresses loader -> version -> icon, committing only at Finish."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
import app_driver
from cubeon import atomicio, thread_safe_ui, instances
from ui.versions import VersionPicker


class NewInstanceTests(unittest.TestCase):
    def picker(self, **kwargs):
        self.committed, self.picked, self.loaded = [], [], []
        entries = [{"id": value, "loader": "vanilla", "installed": False}
                   for value in ("1.20.1", "1.21.1", "26.1.2")]
        picker = VersionPicker(
            app_driver.DriverPage(), get_selected=lambda: "existing-instance",
            label_for=lambda value: value, on_pick=lambda *args: self.picked.append(args),
            on_browse_online=lambda: (self.loaded.append(True),
                                     picker.set_source(entries, online=True, latest="26.1.2")),
            loaders=[("vanilla", "Vanilla"), ("fabric", "Fabric"), ("forge", "Forge")],
            on_create=lambda *args: self.committed.append(args),
            get_supported_versions=lambda loader: ["1.20.1", "1.21.1"], **kwargs)
        return picker

    def test_steps_and_commit(self):
        p = self.picker()
        with patch.object(threading.Thread, "start"):
            p.open()
            p._browse()
            self.assertEqual(p._new_step, 1)
            self.assertTrue(p.loader_row.visible)
            self.assertFalse(p.list.visible)
            self.assertFalse(p.filter_field.visible)
            self.assertEqual(self.loaded, [])
            p._set_install_loader("fabric")
            p._loader_versions["fabric"] = {"1.20.1", "1.21.1"}
            p._next()
            self.assertEqual(p._new_step, 2)
            self.assertFalse(p.loader_row.visible)
            self.assertTrue(p.filter_field.visible)
            self.assertTrue(p.next_button.disabled)
            self.assertFalse(p.latest_chip.visible)  # unsupported latest
            self.assertEqual({e["id"] for e in p._available_entries()}, {"1.20.1", "1.21.1"})
            p._pick("26.1.2")
            self.assertIsNone(p._new_version)
            p._pick("1.20.1")
            self.assertEqual(self.picked, [])
            self.assertEqual(self.committed, [])
            self.assertTrue(p.is_open())
            p._next()
            self.assertEqual(p._new_step, 3)
            self.assertTrue(p.icon_categories.visible)
            self.assertFalse(p.loader_row.visible)
            self.assertFalse(p.filter_field.visible)
            p._change_icon_category("block")
            p._choose_icon("block-tnt")
            self.assertEqual(self.committed, [])
            p._back()
            self.assertEqual(p._new_step, 2)
            self.assertEqual(p._new_version, "1.20.1")
            p._back()
            self.assertEqual(p._new_step, 1)
            self.assertEqual(p._install_loader, "fabric")
            p._next()
            p._next()
            self.assertEqual(p._new_icon, "block-tnt")
            p._next()
            self.assertEqual(self.committed, [("1.20.1", "fabric", "block-tnt")])
            self.assertFalse(p.is_open())

    def test_offline_retry_preserves_step_and_loader(self):
        p = self.picker()
        p.get_supported_versions = None
        p.on_browse_online = p.set_offline
        with patch.object(threading.Thread, "start"):
            p._browse()
            p._set_install_loader("forge")
            p._next()
            self.assertEqual(p._new_step, 2)
            self.assertTrue(p.retry_link.visible)
            self.assertTrue(p.next_button.disabled)
            p.retry_link.on_click(None)
            self.assertEqual(p._new_step, 2)
            self.assertEqual(p._install_loader, "forge")
            p._back()
            self.assertFalse(p.offline_notice.visible)
            p._back()
            self.assertEqual(p._mode, "installed")

    def test_icon_saved_to_resulting_loader_instance(self):
        tree = ast.parse((ROOT / "main.py").read_text())
        names = {"_save_instance_icon", "_save_new_instance_icon"}
        functions = [node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name in names]
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "config.json")
            cfg = {"instance_icons": {"1.20.1": "block-grass"}}
            choice = {"version_id": "1.20.1", "loader": "fabric", "icon": "mob-bee"}
            state = {"installed": {"1.20.1", "fabric-result"}, "pending_instance_icon": choice}
            core = SimpleNamespace(save_config=lambda value: atomicio.write_json(path, value))
            scope = dict(cfg=cfg, state=state, core=core, instance_info=instances, show_snack=lambda text: None)
            exec(compile(ast.Module(body=functions, type_ignores=[]), "<instance icons>", "exec"), scope)
            scope["_save_new_instance_icon"](choice, "fabric", "fabric-result")
            self.assertEqual(json.loads(Path(path).read_text())["instance_icons"],
                             {"1.20.1": "block-grass", "fabric-result": "mob-bee"})
            self.assertIsNone(state["pending_instance_icon"])


if __name__ == "__main__":
    unittest.main()
