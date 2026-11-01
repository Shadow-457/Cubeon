"""Verify responsive seasonal artwork, motion gates and the idle ticker."""
import dataclasses
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()

from PIL import Image
from cubeon import motion, seasonal
from ui.play_seasons import PlaySeasonOverlay, TREE_SIZES
from ui.seasonal_ui import SeasonalAnimator

ROOT = Path(__file__).resolve().parents[1]


def info(name="autumn", enabled=True):
    return dataclasses.replace(seasonal.current(), season=name, seasonal=enabled)


class PlaySeasonsTests(unittest.TestCase):
    def setUp(self):
        self.previous_motion = motion.level()
        motion.set_level("full")

    def tearDown(self):
        motion.set_level(self.previous_motion)

    def test_all_seasons_have_small_transparent_bundled_assets(self):
        total = 0
        for name in seasonal.SEASONS:
            scene = PlaySeasonOverlay(info(name))
            for control in [*scene.trees, scene.ground, *[p["image"] for p in scene.particles if p["image"].visible]]:
                path = ROOT / "assets" / control.src
                self.assertFalse(Path(control.src).is_absolute())
                with Image.open(path) as asset:
                    self.assertEqual(asset.mode, "RGBA")
                    self.assertIsNotNone(asset.getchannel("A").getbbox())
                    self.assertEqual(asset.getchannel("A").getextrema(), (0, 255))
            total += sum(p.stat().st_size for p in (ROOT / "assets/play-seasons" / name).glob("*.png"))
        self.assertLess(total, 128 * 1024)

    def test_resize_preserves_tree_aspect_and_header_clearance(self):
        scene = PlaySeasonOverlay(info())
        for size in [(960, 560), (1259, 772), (1600, 940), (2400, 1350)]:
            scene.resize(*size)
            for control, (w, h) in zip(scene.trees, TREE_SIZES):
                self.assertAlmostEqual(control.width / control.height, w / h)
                self.assertGreaterEqual(size[1] - control.height, 150)
            self.assertEqual(scene.ground.width, size[0])
            self.assertFalse(scene.resize(*size))
        self.assertFalse(scene.resize(float("nan"), 700))
        self.assertFalse(scene.resize(1200, 0))

    def test_decorations_ignore_clicks_and_reuse_controls(self):
        scene = PlaySeasonOverlay(info())
        controls = [id(c) for c in scene.trees + [scene.ground]]
        self.assertTrue(scene.control.ignore_interactions)
        # Flet's positioned control must remain the direct Stack child; its
        # size notifier belongs to the non-positioned inner Stack.
        self.assertIsNone(scene.control.on_size_change)
        self.assertIsNotNone(scene.control.content.on_size_change)
        for name in seasonal.SEASONS:
            scene.configure(info(name), weather=True)
            self.assertEqual(controls, [id(c) for c in scene.trees + [scene.ground]])
            self.assertTrue(all(name in c.src for c in scene.trees))

    def test_particles_are_bounded_away_from_launch_controls(self):
        for name in seasonal.SEASONS:
            scene = PlaySeasonOverlay(info(name))
            scene.configure(info(name), weather=True)
            for size in [(960, 560), (1259, 772), (1600, 940)]:
                scene.resize(*size)
                for _ in range(250):
                    scene.step()
                    for p in scene.particles:
                        image = p["image"]
                        if image.visible:
                            self.assertGreaterEqual(image.left, 0)
                            self.assertLessEqual(image.left + image.width, size[0])
                            self.assertGreaterEqual(image.top, 140)
                            self.assertLess(image.top + image.height, size[1] - 275)

    def test_off_hidden_and_reduced_motion_do_not_advance(self):
        scene = PlaySeasonOverlay(info())
        for enabled, weather, active, level in [
            (False, True, True, "full"), (True, False, True, "full"),
            (True, True, False, "full"), (True, True, True, "reduced"),
        ]:
            motion.set_level(level)
            scene.configure(info(enabled=enabled), weather=weather, active=active)
            before = scene._tick
            self.assertFalse(scene.step())
            self.assertFalse(scene.particle_layer.visible)
            self.assertEqual(before, scene._tick)
            self.assertEqual(scene.control.visible, enabled)

    def test_scenery_switch_is_independent_of_seasonal_palette(self):
        scene = PlaySeasonOverlay(info())
        scene.configure(info(), enabled=False)
        self.assertFalse(scene.control.visible)
        self.assertFalse(scene.animating)
        scene.configure(info(), enabled=True)
        self.assertTrue(scene.control.visible)
        self.assertTrue(scene.animating)

    def test_one_scoped_diff_per_active_frame(self):
        scene = PlaySeasonOverlay(info())
        scene.configure(info(), weather=True)
        animator = SeasonalAnimator()
        animator.add_scene(scene)
        with patch("ui.seasonal_ui.thread_safe_ui.refresh") as refresh:
            animator._frame()
            refresh.assert_called_once_with(scene.particle_layer)
            scene.active = False
            animator._frame()
            self.assertEqual(refresh.call_count, 1)
        animator.clear()
        self.assertFalse(animator.has_work)

    def test_empty_ticker_parks_then_wakes_without_replacing_thread(self):
        scene = PlaySeasonOverlay(info())
        scene.configure(info(), weather=True)
        animator = SeasonalAnimator()
        animator.add_scene(scene)
        try:
            animator.start()
            original = animator._thread
            time.sleep(.3)
            animator.clear()
            time.sleep(.2)
            settled = animator._tick
            cpu = time.process_time()
            time.sleep(.45)
            self.assertEqual(animator._tick, settled)
            self.assertLess(time.process_time() - cpu, .1)
            animator.add_scene(scene)
            animator.start()
            time.sleep(.3)
            self.assertGreater(animator._tick, settled)
            self.assertIs(animator._thread, original)
        finally:
            animator.stop()

    def test_asset_generator_is_reproducible_without_preview_files(self):
        spec = importlib.util.spec_from_file_location("play_art", ROOT / "tools/make_play_seasons.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        with tempfile.TemporaryDirectory() as temp:
            for name in seasonal.SEASONS:
                out = Path(temp) / name
                generator.render(name, out)
                for path in out.glob("*.png"):
                    self.assertEqual(path.read_bytes(), (ROOT / "assets/play-seasons" / name / path.name).read_bytes())


if __name__ == "__main__":
    unittest.main()
