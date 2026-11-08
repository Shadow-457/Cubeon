"""Focused offline checks for thumbnail decode sizes and encoded-art retention."""
import base64
from collections import OrderedDict
import io
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from PIL import Image
from cubeon import icons
from ui.image_memory import preview_image


class ImageMemory(unittest.TestCase):
    def encoded(self, color="green"):
        output = io.BytesIO()
        Image.new("RGB", (48, 32), color).save(output, "PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")

    def test_thumbnail_decodes_at_two_times_display_width(self):
        for width, height in ((44, 44), (76, 112), (104, 118), (620, 430)):
            with self.subTest(width=width):
                image = preview_image("art.png", width=width, height=height, fit=ft.BoxFit.CONTAIN)
                self.assertIsInstance(image, ft.Image)
                self.assertEqual((image.width, image.height), (width, height))
                self.assertEqual(image.cache_width, width * 2)
                self.assertIsNone(image.cache_height)
                self.assertEqual(image.fit, ft.BoxFit.CONTAIN)

    def test_sources_options_and_animation_bytes_remain_untouched(self):
        source = b"unchanged encoded artwork"
        fallback = ft.Icon(ft.Icons.IMAGE)
        image = preview_image(source, width=44, height=44, cache_width=256,
                              error_content=fallback, gapless_playback=True,
                              filter_quality=ft.FilterQuality.NONE, data="image-id")
        self.assertIs(image.src, source)
        self.assertIs(image.error_content, fallback)
        self.assertEqual(image.cache_width, 256)
        self.assertTrue(image.gapless_playback)
        self.assertEqual(image.filter_quality, ft.FilterQuality.NONE)
        self.assertEqual(image.data, "image-id")

    def test_encoded_cache_is_bounded_by_bytes_and_keeps_recent_sources(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(icons, "ICON_DIR", folder), \
                patch.object(icons, "_sources", OrderedDict()), patch.object(icons, "_SOURCE_BYTES", 40 * 1024):
            urls = []
            for index in range(8):
                url = f"https://example.test/art-{index}.png"
                urls.append(url)
                pixels = random.Random(index).randbytes(64 * 64 * 3)
                Image.frombytes("RGB", (64, 64), pixels).save(icons._dest(url), "PNG")
                source = icons.src(url)
                self.assertTrue(icons.valid_source(source))
                self.assertLessEqual(sum(len(entry[1]) for entry in icons._sources.values()), icons._SOURCE_BYTES)
            self.assertIsNone(icons.peek_src(urls[0]))
            self.assertEqual(icons.peek_src(urls[-1]), source)
            self.assertEqual(icons.src(urls[0]), self.encoded_file(icons._dest(urls[0])))

    @staticmethod
    def encoded_file(filename):
        return base64.b64encode(Path(filename).read_bytes()).decode("ascii")

    def test_validation_cache_keeps_digests_not_artwork(self):
        with patch.object(icons, "_validated_sources", OrderedDict()), \
                patch.object(Image, "open", wraps=Image.open) as opened:
            source = self.encoded()
            self.assertTrue(icons.valid_source(source))
            self.assertTrue(icons.valid_source(source))
            self.assertEqual(opened.call_count, 1)
            for index in range(icons._VALIDATION_LIMIT + 5):
                icons.valid_source(self.encoded((index, 10, 20)))
            self.assertEqual(len(icons._validated_sources), icons._VALIDATION_LIMIT)
            self.assertTrue(all(isinstance(key, bytes) and len(key) == 32 for key in icons._validated_sources))
            self.assertTrue(all(isinstance(value, bool) for value in icons._validated_sources.values()))

    def test_invalid_artwork_is_still_refused(self):
        for source in (None, b"bytes", "invalid base64", "\ud800", "x" * (4 * 1024 * 1024 + 1)):
            with self.subTest(source_type=type(source).__name__):
                self.assertFalse(icons.valid_source(source))
        output = io.BytesIO()
        Image.new("RGB", (4096, 1025)).save(output, "PNG")
        self.assertFalse(icons.valid_source(base64.b64encode(output.getvalue()).decode("ascii")))
        self.assertFalse(icons.valid_source(base64.b64encode(b"not an image").decode("ascii")))


if __name__ == "__main__":
    unittest.main()
