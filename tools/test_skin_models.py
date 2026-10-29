"""Real cube-net arm layout: detect, preserve, repair and publish slim models."""
import os
from pathlib import Path
import sys
import types
import unittest

import _sandbox_home
TEST_HOME = _sandbox_home.isolate()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
fake = types.ModuleType("minecraft_launcher_lib")
fake.utils = types.SimpleNamespace(get_minecraft_directory=lambda: os.path.join(TEST_HOME, ".minecraft"))
sys.modules["minecraft_launcher_lib"] = fake
from PIL import Image
from cubeon import skins

RESERVED = ((54, 20, 56, 32), (50, 16, 52, 20), (46, 52, 48, 64), (42, 48, 44, 52))


def alex_sheet():
    image = Image.new("RGBA", (64, 64), (90, 140, 200, 255))
    for x0, y0, x1, y1 in RESERVED:
        for y in range(y0, y1):
            for x in range(x0, x1):
                image.putpixel((x, y), (0, 0, 0, 0))
    return image


class SkinModelTests(unittest.TestCase):
    def test_actual_reserved_pixels(self):
        image = alex_sheet()
        self.assertTrue(skins._detect_slim_model(image))
        self.assertEqual(image.getpixel((47, 25))[3], 255)
        self.assertEqual(image.getpixel((39, 55))[3], 255)
        classic = Image.new("RGBA", (64, 64), (90, 140, 200, 255))
        for y in range(20, 32):
            classic.putpixel((47, y), (0, 0, 0, 0))
        for y in range(52, 64):
            classic.putpixel((39, y), (0, 0, 0, 0))
        self.assertFalse(skins._detect_slim_model(classic))
        self.assertFalse(skins._detect_slim_model(Image.new("RGBA", (64, 32))))

    def test_repairs_back_side_and_bottom_without_touching_spares(self):
        image = alex_sheet()
        for point in ((51, 25), (43, 55), (47, 25), (39, 55), (48, 17), (41, 49)):
            image.putpixel(point, (0, 0, 0, 0))
        image.putpixel((51, 40), (0, 0, 0, 0))  # outer right sleeve is allowed clear
        result = skins._repair_transparent_base(image, slim=True)
        for point in ((51, 25), (43, 55), (47, 25), (39, 55), (48, 17), (41, 49)):
            self.assertEqual(result.getpixel(point)[3], 255, point)
        for x0, y0, x1, y1 in RESERVED:
            self.assertEqual(result.crop((x0, y0, x1, y1)).tobytes(), image.crop((x0, y0, x1, y1)).tobytes())
        self.assertEqual(result.getpixel((51, 40))[3], 0)

    def test_old_auto_metadata_migrates_and_explicit_choice_wins(self):
        path = Path(TEST_HOME) / "alex.png"
        alex_sheet().save(path)
        entry = skins.add_custom_skin(str(path), "Correct Alex")
        meta = skins._load_skins_meta()
        next(s for s in meta["skins"] if s["filename"] == entry["filename"])["slim"] = False
        skins._save_skins_meta(meta)
        self.assertTrue(skins._active_skin_is_slim(entry["filename"]))
        self.assertTrue(skins.set_skin_model({}, entry["filename"], "classic"))
        self.assertFalse(skins._active_skin_is_slim(entry["filename"]))
        self.assertTrue(skins.set_skin_model({}, entry["filename"], "slim"))
        self.assertTrue(skins._active_skin_is_slim(entry["filename"]))

    def test_slim_back_face_preview_keeps_both_edges(self):
        sheet = alex_sheet()
        # Outer layers are transparent; distinct back faces span exactly
        # x=51..53 and x=43..45. A classic +8 offset loses the first column.
        for rectangle in ((40, 32, 56, 48), (48, 48, 64, 64)):
            sheet.paste((0, 0, 0, 0), rectangle)
        for y in range(20, 32):
            for x in range(51, 54):
                sheet.putpixel((x, y), (240, 20, 20, 255))
        for y in range(52, 64):
            for x in range(43, 46):
                sheet.putpixel((x, y), (20, 220, 20, 255))
        source = Path(TEST_HOME) / "alex-back.png"
        sheet.save(source)
        entry = skins.add_custom_skin(str(source), "Alex back", model="slim")
        output = Path(TEST_HOME) / "alex-back-preview.png"
        skins.render_local_skin_preview(entry["filename"], str(output), scale=8, view="back")
        with Image.open(output) as preview:
            # The 3px arms occupy x=0..23 and x=88..111 in the 112px canvas.
            for x in (0, 16):
                red, green, blue, alpha = preview.getpixel((x, 80))
                self.assertGreater(red, 200, (x, "right arm back"))
            for x in (88, 104):
                red, green, blue, alpha = preview.getpixel((x, 80))
                self.assertGreater(green, 180, (x, "left arm back"))


if __name__ == "__main__":
    unittest.main()
