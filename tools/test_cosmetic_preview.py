"""Complex store wings: curved geometry, glow, bounded caches and drag cost."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from PIL import Image, ImageChops
from cubeon import cosmetics, cosmetic_preview, skins
from cubeon.appearance import CharacterModel, render_faces
import gen_store_collection as collection
from gen_cosmetics import render_item


class Preview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.item = cls.make_item("crimson-archfiend")

    @classmethod
    def make_item(cls, key):
        folder = Path(cls.temp.name) / key
        folder.mkdir()
        recipe = next(w for w in collection.WINGS if w[0] == key)
        with patch.object(collection, "WINGS", [recipe]):
            original = collection.wings()[0]
        image, boxes = render_item(original)
        image.save(folder / "wing.png")
        collection.glow_texture(image, key).save(folder / "glow.png")
        return dict(id="store_" + "a" * 32, slot="back", texture="wing.png", emissive_texture="glow.png",
                        boxes=boxes, feathers=original["feathers"], separate_feathers=True,
                        wing_flare=True, _store_directory=str(folder))

    def tearDown(self):
        cosmetic_preview.clear_cache()

    def test_real_curved_wing_preview_preserves_art_fit_depth_and_glow(self):
        original_item = copy.deepcopy(self.item)
        full = cosmetics.preview_faces(self.item) + cosmetics.preview_faces(self.item, emissive=True)
        prepared = cosmetics.preview_faces(self.item, simplify=True) + cosmetics.preview_faces(self.item, simplify=True, emissive=True)
        self.assertEqual(self.item, original_item)
        self.assertLess(len(prepared), len(full) / 5)
        skin = skins.default_base_skin()
        original = CharacterModel(skin, cosmetics_faces=full)
        compact = CharacterModel(skin, cosmetics_faces=prepared)
        self.assertAlmostEqual(compact._orbit_radius, original._orbit_radius)
        self.assertAlmostEqual(compact._vertical_extent, original._vertical_extent)
        self.assertTrue(any(f.texture.info.get("cubeon_emissive") for f in compact.faces))
        self.assertTrue(any(abs(f.normal[0]) > .01 and abs(f.normal[2]) > .1 for f in compact.faces))
        for yaw, pitch in ((25, 10), (90, 10), (155, 10), (270, -25)):
            expected = original.render(yaw, pitch)
            actual = compact.render(yaw, pitch)
            difference = ImageChops.difference(actual, expected)
            changes = sum(1 for pixel in zip(*(iter(channel.tobytes()) for channel in difference.split())) if max(pixel) > 32)
            # Only subpixel raster seams may differ; a changed scale, flattened
            # feather plane, misplaced atlas or lost glow changes far more.
            self.assertLess(changes, actual.width * actual.height * .005, (yaw, pitch, changes))
        self.assertLess(len(compact.project(25, 10, detail=False)), 120)
        self.assertGreater(len(compact.project(25, 10)), len(compact.project(25, 10, detail=False)) * 3)
        start = time.perf_counter()
        render_faces(compact.project(25, 10, detail=False))
        compact_time = time.perf_counter() - start
        start = time.perf_counter()
        render_faces(original.project(25, 10, detail=False))
        original_time = time.perf_counter() - start
        print(f"Wing drag: {original_time:.3f}s -> {compact_time:.3f}s")
        self.assertLess(compact_time, original_time / 6)

    def test_revision_cache_reuses_images_and_invalidates_geometry_and_file_changes(self):
        first = cosmetics.preview_faces(self.item, simplify=True)
        with patch.object(cosmetic_preview, "compact_faces", side_effect=AssertionError("rebaked")):
            again = cosmetics.preview_faces(self.item, simplify=True)
        self.assertIs(first[0][2], again[0][2])
        changed = copy.deepcopy(self.item)
        changed["boxes"][0]["origin"][0] += .1
        with patch.object(cosmetic_preview, "compact_faces", wraps=cosmetic_preview.compact_faces) as bake:
            cosmetics.preview_faces(changed, simplify=True)
            self.assertEqual(bake.call_count, 1)
        path = Path(self.item["_store_directory"]) / self.item["texture"]
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        with patch.object(cosmetic_preview, "compact_faces", wraps=cosmetic_preview.compact_faces) as bake:
            cosmetics.preview_faces(self.item, simplify=True)
            self.assertEqual(bake.call_count, 1)
        self.assertLessEqual(sum(entry[1] for entry in cosmetic_preview._CACHE.values()), cosmetic_preview._MAX_BYTES)
        cosmetics.invalidate_cache()
        self.assertFalse(cosmetic_preview._CACHE)

    def test_translucent_planes_retain_individual_depth_blending(self):
        tile = Image.new("RGBA", (4, 4), (255, 20, 0, 128))
        faces = [(((0, 4, 0), (4, 4, 0), (0, 0, 0)), (0, 0, 1), tile),
                 (((2, 4, 0), (6, 4, 0), (2, 0, 0)), (0, 0, 1), tile)]
        self.assertEqual(cosmetic_preview.compact_faces(faces), faces)

    def test_solid_pets_and_footwear_keep_side_surfaces_and_reuse_prepared_faces(self):
        for original in [collection.pets()[1], collection.footwear()[0]]:
            folder = Path(self.temp.name) / original["id"]
            folder.mkdir()
            sheet, boxes = render_item(original)
            sheet.save(folder / "model.png")
            item = dict(id="store_" + "b" * 32, slot=original["slot"], texture="model.png",
                        boxes=boxes, _store_directory=str(folder))
            full = cosmetics.preview_faces(item)
            prepared = cosmetics.preview_faces(item, simplify=True)
            self.assertLess(len(prepared), len(full) / 2)
            self.assertFalse(any(texture.info.get("cubeon_preview_detail") for _, _, texture in prepared))
            with patch.object(cosmetic_preview, "compact_faces", side_effect=AssertionError("rebaked wearable")):
                cosmetics.preview_faces(item, simplify=True)
            reference = CharacterModel(skins.default_base_skin(), cosmetics_faces=full)
            compact = CharacterModel(skins.default_base_skin(), cosmetics_faces=prepared)
            self.assertAlmostEqual(reference._orbit_radius, compact._orbit_radius)
            self.assertAlmostEqual(reference._vertical_extent, compact._vertical_extent)
            for yaw in (25, 90, 155):
                actual = compact.render(yaw, 10)
                difference = ImageChops.difference(actual, reference.render(yaw, 10))
                changed = sum(1 for pixel in zip(*(iter(channel.tobytes()) for channel in difference.split())) if max(pixel) > 32)
                self.assertLess(changed, actual.width * actual.height * .005, (original["id"], yaw, changed))

    def test_layered_feathers_keep_their_art_and_fit_inside_the_cache(self):
        item = self.make_item("ivory-tide")
        full = cosmetics.preview_faces(item) + cosmetics.preview_faces(item, emissive=True)
        compact = cosmetics.preview_faces(item, simplify=True) + cosmetics.preview_faces(item, simplify=True, emissive=True)
        with patch.object(cosmetic_preview, "compact_faces", side_effect=AssertionError("uncacheable feather model")):
            cosmetics.preview_faces(item, simplify=True)
            cosmetics.preview_faces(item, simplify=True, emissive=True)
        original = CharacterModel(skins.default_base_skin(), cosmetics_faces=full)
        prepared = CharacterModel(skins.default_base_skin(), cosmetics_faces=compact)
        self.assertAlmostEqual(original._orbit_radius, prepared._orbit_radius)
        for yaw in (25, 155):
            frame = prepared.render(yaw, 10)
            difference = ImageChops.difference(frame, original.render(yaw, 10))
            changes = sum(1 for pixel in zip(*(iter(channel.tobytes()) for channel in difference.split())) if max(pixel) > 32)
            self.assertLess(changes, frame.width * frame.height * .005)
        self.assertLessEqual(sum(entry[1] for entry in cosmetic_preview._CACHE.values()), cosmetic_preview._MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
