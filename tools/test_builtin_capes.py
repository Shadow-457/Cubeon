"""Small offline checks for bundled cape artwork and existing library actions."""
from contextlib import ExitStack
import base64
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from PIL import Image, ImageSequence
from cubeon import capes, paths
from cubeon.ingame_capes import InGameCapes, PAGE_SIZE


class BuiltinCapes(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="cubeon-builtin-capes-test-")))
        self.library = self.folder / "capes"
        self.library.mkdir()
        self.game = self.folder / "running-game"
        self.game.mkdir()
        self.shared = self.folder / "shared-capes"
        for module, attribute, value in (
            (capes, "CAPES_DIR", str(self.library)),
            (capes, "CAPES_META_PATH", str(self.library / "capes.json")),
            (paths, "CAPES_DIR", str(self.library)),
            (paths, "game_dir_for", lambda version, **kwargs: str(self.game)),
            (paths, "instance_csl_path", lambda directory: str(self.shared)),
            (capes, "instance_csl_path", lambda directory: str(self.shared)),
        ):
            self.stack.enter_context(patch.object(module, attribute, value))
        self.save = self.stack.enter_context(patch.object(capes, "save_config"))
        self.cfg = {"username": "CapeTester", "active_cape": None,
                    "manage_skin_mod": True, "csl_enabled": True}
        self.state = {"running_version": "fixture"}
        self.bridge = InGameCapes(self.cfg, self.state, threading.RLock())

    def test_catalogue_and_compact_vanilla_layout(self):
        entries = capes.list_builtin_capes()
        self.assertEqual(len(entries), 8)
        self.assertEqual(sum(entry["animated"] for entry in entries), 4)
        self.assertEqual(len({entry["filename"] for entry in entries}), 8)
        self.assertEqual(capes.list_custom_capes(), [])
        self.assertEqual(capes.list_capes(), entries)
        total_bytes = sum(path.stat().st_size for path in Path(capes.BUILTIN_CAPES_DIR).iterdir())
        self.assertLess(total_bytes, 192 * 1024)
        for entry in entries:
            with self.subTest(cape=entry["name"]):
                path = Path(capes.get_cape_path(entry["filename"]))
                self.assertEqual(path.parent, Path(capes.BUILTIN_CAPES_DIR))
                self.assertTrue(entry["builtin"])
                with Image.open(path) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (128, 64))
                    self.assertEqual(image.getchannel("A").getbbox(), (0, 0, 44, 34))
                    self.assertGreater(len(image.crop((2, 2, 22, 34)).getcolors(maxcolors=640)), 4)

    def test_animation_atlases_gifs_and_previews(self):
        for entry in capes.list_builtin_capes():
            with self.subTest(cape=entry["name"]):
                path = capes.get_cape_path(entry["filename"])
                info = capes.animation_info(entry["filename"])
                preview = self.folder / ("preview.gif" if entry["animated"] else "preview.png")
                capes.render_cape_preview(entry["filename"], str(preview), scale=4)
                with Image.open(preview) as image:
                    self.assertEqual(image.size, (40, 64))
                    self.assertEqual(getattr(image, "n_frames", 1), 16 if entry["animated"] else 1)
                if not entry["animated"]:
                    self.assertIsNone(info)
                    continue
                self.assertEqual((info["width"], info["height"], info["count"]), (128, 64, 16))
                self.assertEqual(info["durations"], [100] * 16)
                self.assertEqual(info["loop"], 0)
                with Image.open(path + ".frames.png") as atlas:
                    self.assertEqual(atlas.size, (128, 1024))
                    frames = [atlas.crop((0, index * 64, 128, (index + 1) * 64)).tobytes()
                              for index in range(16)]
                    self.assertGreater(len(set(frames)), 8)
                    with Image.open(path) as still:
                        self.assertEqual(frames[0], still.tobytes())
                with Image.open(path + ".gif") as image:
                    self.assertEqual(image.n_frames, 16)
                    self.assertEqual(image.info["loop"], 0)
                    for frame in ImageSequence.Iterator(image):
                        self.assertEqual(frame.info["duration"], 100)
                        self.assertEqual(frame.convert("RGBA").getpixel((127, 63))[3], 0)

    def test_bridge_preview_apply_and_first_frame_mirrors(self):
        initial = self.bridge.snapshot()
        self.assertEqual(initial["total"], 8)
        self.assertTrue(all(item["builtin"] for item in initial["items"]))
        self.assertIsNone(self.cfg["active_cape"])
        self.assertEqual(initial["active"], "")
        for entry in capes.list_builtin_capes():
            with self.subTest(cape=entry["name"]):
                filename = entry["filename"]
                item = next(item for item in initial["items"] if item["id"] == filename)
                self.assertTrue(item["builtin"])
                with Image.open(io.BytesIO(base64.b64decode(item["png"]))) as image:
                    self.assertEqual(image.size, (64, 32))
                response = self.bridge.action({"action": "apply", "id": filename, "game_dir": str(self.game)})
                self.assertEqual(response["active"], filename)
                live = self.bridge.live_state(str(self.game))
                self.assertTrue(live["enabled"])
                self.assertEqual("animation" in live["applied"], entry["animated"])
                source = Path(capes.get_cape_path(filename)).read_bytes()
                self.assertEqual((self.shared / "CapeTester.png").read_bytes(), source)
                mirror = self.game / "CustomSkinLoader/LocalSkin/capes/CapeTester.png"
                self.assertEqual(mirror.read_bytes(), source)
        self.assertEqual(self.save.call_count, 8)

    def test_builtins_cannot_be_deleted_and_session_guards_remain(self):
        filename = capes.list_builtin_capes()[0]["filename"]
        path = Path(capes.get_cape_path(filename))
        original = path.read_bytes()
        for operation in (lambda: capes.delete_custom_cape(filename),
                          lambda: self.bridge.action({"action": "delete", "id": filename})):
            with self.assertRaisesRegex(ValueError, "Built-in"):
                operation()
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(self.bridge.live_state(str(self.folder / "wrong-game"))["enabled"])
        with self.assertRaisesRegex(ValueError, "session"):
            self.bridge.action({"action": "apply", "id": filename, "game_dir": str(self.folder / "wrong-game")})
        self.cfg["csl_enabled"] = False
        with self.assertRaisesRegex(ValueError, "CustomSkinLoader"):
            self.bridge.action({"action": "apply", "id": filename, "game_dir": str(self.game)})
        self.assertIsNone(self.cfg["active_cape"])
        self.assertFalse(self.bridge.live_state(str(self.game))["enabled"])
        self.save.assert_not_called()
        for invalid in ("../builtin_verdant_crest.png", "/tmp/evil.png", "builtin_ender_rift.png.frames.png/evil.png"):
            with self.assertRaises(ValueError):
                capes.get_cape_path(invalid)

    def test_uploaded_capes_follow_builtins_across_pages(self):
        source = self.folder / "upload.png"
        Image.new("RGBA", (20, 32), "teal").save(source)
        uploads = [capes.add_custom_cape(str(source), f"Upload {index}") for index in range(7)]
        self.assertEqual(len(capes.list_custom_capes()), 7)
        first = self.bridge.snapshot()
        second = self.bridge.snapshot(PAGE_SIZE)
        self.assertEqual(first["total"], 15)
        ids = [entry["id"] for entry in first["items"][2:] + second["items"][2:]]
        self.assertEqual(ids, [entry["filename"] for entry in capes.list_builtin_capes() + uploads])
        capes.delete_custom_cape(uploads[-1]["filename"])
        self.assertEqual(len(capes.list_capes()), 14)


if __name__ == "__main__":
    unittest.main()
