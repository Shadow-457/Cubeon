"""Exercise the roaming pet's routes, resting poses, resize and motion gates."""
import dataclasses
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import motion, seasonal
from ui.launcher_pet import LauncherPet, SIZE

ROOT = Path(__file__).resolve().parents[1]


class PetTests(unittest.TestCase):
    def setUp(self):
        self.previous = motion.level()
        motion.set_level('full')
        self.info = dataclasses.replace(seasonal.current(), seasonal=True)

    def tearDown(self):
        motion.set_level(self.previous)

    def pet(self):
        pet = LauncherPet(self.info)
        pet.configure(self.info, enabled=True, active_tab='play')
        pet.resize(1440, 900)
        return pet

    def test_route_walks_climbs_and_sits_on_play(self):
        pet = self.pet()
        states = set()
        climbed = False
        for _ in range(3500):
            pet.step()
            self.assertGreaterEqual(pet.x, 0)
            self.assertLessEqual(pet.x + SIZE, 1440)
            self.assertGreaterEqual(pet.y, 0)
            self.assertLessEqual(pet.y + SIZE, 900)
            states.add((pet.state, pet._rest_kind))
            climbed |= abs(pet.sprite.rotate or 0) > 1
            if pet.state == 'rest':
                self.assertTrue(pet.sprite.content.src.endswith('-rest.png'))
                if pet._rest_kind == 'button':
                    self.assertEqual(pet.y + SIZE, 900 - 287)
        self.assertIn(('rest', 'button'), states)
        self.assertIn(('rest', 'border'), states)
        self.assertTrue(climbed)
        self.assertTrue(pet.control.ignore_interactions)

    def test_non_play_tabs_follow_borders_without_old_button_perches(self):
        pet = self.pet()
        for _ in range(1500):
            pet.step()
            if pet.state == 'rest' and pet._rest_kind == 'button':
                break
        self.assertEqual(pet._rest_kind, 'button')
        pet.configure(self.info, enabled=True, active_tab='mods')
        self.assertEqual(pet.y, 900 - SIZE - 12)
        self.assertEqual(pet.state, 'rest')
        self.assertEqual(pet.sprite.rotate, 0)
        self.assertFalse(any(kind == 'button' for _, _, kind in pet.route))
        for _ in range(1500):
            pet.step()
        pet.configure(self.info, enabled=True, active_tab='play')
        self.assertTrue(any(kind == 'button' for _, _, kind in pet.route))

    def test_off_and_reduced_do_no_work(self):
        pet = self.pet()
        for enabled, level in [(False, 'full'), (True, 'reduced')]:
            motion.set_level(level)
            pet.configure(self.info, enabled=enabled, active_tab='play')
            point = (pet.x, pet.y)
            for _ in range(100):
                self.assertFalse(pet.step())
            self.assertEqual(point, (pet.x, pet.y))
            self.assertEqual(pet.control.visible, enabled)
            self.assertTrue(pet.sprite.content.src.endswith('-rest.png'))

    def test_pause_freezes_the_sprite_codec_and_route(self):
        pet = self.pet()
        pet.wait = 0
        for _ in range(8):
            pet.step()
        pet.set_paused(True)
        point = (pet.x, pet.y)
        self.assertTrue(pet.sprite.content.src.endswith('-rest.png'))
        self.assertFalse(pet.step())
        self.assertEqual(point, (pet.x, pet.y))
        pet.set_paused(False)
        self.assertTrue(pet.animating)

    def test_resizing_keeps_pet_inside_and_updates_perches(self):
        pet = self.pet()
        for size in [(1100, 740), (1920, 1080), (980, 640)]:
            pet.resize(*size)
            self.assertLessEqual(pet.x + SIZE, size[0])
            self.assertLessEqual(pet.y + SIZE, size[1])
            self.assertEqual(pet.y, size[1] - SIZE - 12)
            self.assertTrue(all(0 <= x <= size[0] - SIZE and 0 <= y <= size[1] - SIZE for x,y,_ in pet.route))
        self.assertFalse(pet.resize(float('nan'), 800))
        self.assertIsNone(pet.control.on_size_change)
        self.assertIsNotNone(pet.control.content.on_size_change)

    def test_shrinking_removes_an_unavailable_button_perch(self):
        pet = self.pet()
        for _ in range(1500):
            pet.step()
            if pet.state == 'rest' and pet._rest_kind == 'button':
                break
        self.assertEqual(pet._rest_kind, 'button')
        pet.resize(1200, 740)
        self.assertEqual(pet.y + SIZE, 740 - 287)
        pet.resize(1100, 740)
        self.assertEqual(pet._rest_kind, 'floor')
        self.assertFalse(any(kind == 'button' for _, _, kind in pet.route))
        pet.resize(960, 600)
        self.assertEqual(pet._rest_kind, 'floor')
        self.assertEqual(pet.y, 600 - SIZE - 12)
        self.assertFalse(any(kind == 'button' for _, _, kind in pet.route))

    def test_every_season_has_a_resting_pose_and_reuses_the_pet(self):
        pet = self.pet()
        identity = id(pet.sprite)
        for name in seasonal.SEASONS:
            info = dataclasses.replace(self.info, season=name)
            pet.configure(info, enabled=True, active_tab='play')
            self.assertEqual(id(pet.sprite), identity)
            self.assertTrue((ROOT/'assets'/pet.sprite.content.src).is_file())

    def test_launcher_toggle_and_tab_switch_update_the_real_models(self):
        import inspect
        import _fuzz_common as fz
        stubs = fz.install_safe_stubs()
        load = stubs.core.load_config
        stubs.core.load_config = lambda: dict(load(), seasonal_theme=True,
                                             season_overlay=True, season_pet=False,
                                             onboarded=True)
        seasonal.refresh(stubs.core.load_config())
        page = fz.FakePage()
        stubs.app.run_sync(page)
        controls = list(fz.every_control(page))
        handler = lambda name: next(c for c in controls if getattr(getattr(c, 'on_change', None), '__name__', '') == name)
        toggle = handler('_on_season_overlay_toggle')
        buddy = handler('_on_season_pet_toggle')
        overlay = next(c for c in controls if c.data == 'play-season-overlay').content.on_size_change.__self__
        pet = next(c for c in controls if c.data == 'launcher-roaming-pet').content.on_size_change.__self__
        apply = inspect.getclosurevars(toggle.on_change).nonlocals['_season_runtime_apply']
        animator = inspect.getclosurevars(apply).nonlocals['_season_rt']['animator']
        try:
            toggle.value = False
            toggle.on_change(fz.FakeEvent(toggle))
            self.assertFalse(overlay.control.visible)
            buddy.value = True
            buddy.on_change(fz.FakeEvent(buddy))
            self.assertTrue(pet.control.visible)
            page.window.on_event(SimpleNamespace(type='blur'))
            self.assertTrue(pet.paused)
            self.assertTrue(animator._paused)
            self.assertFalse(pet.animating)
            self.assertTrue(pet.sprite.content.src.endswith('-rest.png'))
            page.window.on_event(SimpleNamespace(type='focus'))
            self.assertFalse(animator._paused)
            self.assertTrue(pet.animating)
            pet.state, pet._rest_kind, pet.y = 'rest', 'button', 400
            nav = next(c for c in controls if getattr(getattr(c, 'on_click', None), '__defaults__', None) == ('mods',))
            nav.on_click(fz.FakeEvent(nav))
            self.assertEqual(pet.active_tab, 'mods')
            self.assertEqual(pet.y, pet.size[1] - SIZE - 12)
            self.assertFalse(overlay.animating)
            buddy.value = False
            buddy.on_change(fz.FakeEvent(buddy))
            self.assertFalse(pet.control.visible)
            self.assertFalse(animator.has_work)
        finally:
            animator.stop()


if __name__ == '__main__':
    unittest.main()
