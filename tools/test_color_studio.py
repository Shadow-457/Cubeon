"""Native color-wheel geometry, retained preview, contrast and safe saves."""
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from cubeon import config, theme, thread_safe_ui
from cubeon.color_templates import (CUSTOM_PALETTE_KEY, contrast_ratio, custom_palette,
                                    normalize_custom_palette)
from templates.color_green import PALETTE
from ui.color_studio import ColorStudio, seed_color, wheel_position
from app_driver import DriverPage


class PaletteTests(unittest.TestCase):
    def test_dark_palette_preserves_semantics_and_readable_foregrounds(self):
        import colorsys
        for hue in range(0, 360, 15):
            rgb = colorsys.hsv_to_rgb(hue / 360, 1, 1)
            seed = '#' + ''.join(f'{round(v * 255):02X}' for v in rgb)
            for depth in (0, .5, 1):
                for vividness in (0, 1):
                    palette = custom_palette(dict(seed=seed, depth=depth, vividness=vividness))
                    self.assertGreaterEqual(contrast_ratio(palette['ON_ACCENT'], palette['ACCENT']), 7)
                    for surface in ('BG', 'SURFACE', 'SURFACE_HI', 'SURFACE_MAX'):
                        self.assertGreaterEqual(contrast_ratio(palette['TEXT'], palette[surface]), 7)
                        self.assertGreaterEqual(contrast_ratio(palette['TEXT_DIM'], palette[surface]), 4.5)
                    self.assertGreaterEqual(contrast_ratio(palette['ACCENT'], palette['SURFACE_MAX']), 4.5)
                    for semantic in ('INFO', 'DANGER', 'WARNING', 'ON_DANGER', 'ON_WARNING'):
                        self.assertEqual(palette[semantic], PALETTE[semantic])
        self.assertNotEqual(custom_palette({'seed': '#FF6600', 'depth': 0})['BG'],
                            custom_palette({'seed': '#FF6600', 'depth': 1})['BG'])

    def test_invalid_saved_values_do_not_create_a_palette(self):
        for value in (None, [], 'green', {}, {'seed': 'red'}, {'seed': '#123456', 'depth': float('nan')},
                      {'seed': '#123456', 'vividness': float('inf')}, {'seed': '#123456', 'depth': 'bad'}):
            self.assertIsNone(normalize_custom_palette(value))
        self.assertEqual(normalize_custom_palette({'seed': '#abcdef', 'depth': 100, 'vividness': -1}),
                         {'seed': '#ABCDEF', 'depth': 1., 'vividness': 0.})

    def test_recipe_binds_tokens_before_ui_imports_and_cli_still_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / '.cubeon_launcher').mkdir()
            recipe = {'seed': '#B743DF', 'depth': .8, 'vividness': .7}
            cfg_path = home / '.cubeon_launcher/config.json'
            cfg_path.write_text(json.dumps({CUSTOM_PALETTE_KEY: recipe}))
            env = dict(os.environ, HOME=str(home))
            script = 'from cubeon.theme import ACCENT, THEME, ACTIVE_TEMPLATE; print(ACCENT, THEME["ACCENT"], ACTIVE_TEMPLATE)'
            result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                                    text=True, capture_output=True, check=True, timeout=15)
            accent = custom_palette(recipe)['ACCENT']
            self.assertEqual(result.stdout.strip(), f'{accent} {accent} custom')
            result = subprocess.run([sys.executable, '-c', script, '--color1'], cwd=ROOT, env=env,
                                    text=True, capture_output=True, check=True, timeout=15)
            self.assertEqual(result.stdout.strip(), f'{PALETTE["ACCENT"]} {PALETTE["ACCENT"]} green')
            result = subprocess.run([sys.executable, '-c', script, '--cubeon-installer'], cwd=ROOT, env=env,
                                    text=True, capture_output=True, check=True, timeout=15)
            self.assertEqual(result.stdout.strip(), f'{PALETTE["ACCENT"]} {PALETTE["ACCENT"]} green')


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'username': 'StudioTest', CUSTOM_PALETTE_KEY: None}
        self.studio = ColorStudio(DriverPage(), self.cfg, on_restart=lambda e: None,
                                  set_status=lambda message: None)
        self.repaint = patch.object(thread_safe_ui, 'refresh').start()
        self.addCleanup(patch.stopall)

    def test_wheel_matches_clockwise_gradient_and_clamps_outside_drags(self):
        for point, color in [((100, 50), '#FF0000'), ((50, 100), '#80FF00'),
                             ((0, 50), '#00FFFF'), ((50, 0), '#8000FF')]:
            self.assertEqual(seed_color(*wheel_position(*point, 100), 1), color)
        self.assertEqual(wheel_position(150, 50, 100), (0, 1))
        self.assertEqual(wheel_position(50, 50, 100, .7), (.7, 0))
        self.assertEqual(seed_color(.5, 0, 1), '#FFFFFF')

    def test_drag_updates_retained_preview_without_filesystem_or_config_work(self):
        studio = self.studio
        identities = studio.preview, studio.preview_play, studio.field, studio.marker
        with patch.object(config, 'save_config') as save, patch('builtins.open') as files:
            studio.brightness.value = 100
            studio._brightness(None)
            studio._point(SimpleNamespace(local_position=SimpleNamespace(x=224, y=112)))
            self.assertFalse(save.called or files.called)
        self.assertEqual(studio.recipe['seed'], '#FF0000')
        palette = custom_palette(studio.recipe)
        self.assertTrue(all(isinstance(icon, ft.Icon) for icon in studio.preview_icons))
        self.assertEqual([icon.color for icon in studio.preview_icons],
                         [palette['ACCENT'], palette['TEXT_DIM'], palette['TEXT_DIM']])
        self.assertIsNone(self.cfg[CUSTOM_PALETTE_KEY])
        self.assertEqual(identities, (studio.preview, studio.preview_play, studio.field, studio.marker))
        self.assertFalse(studio.save.disabled)
        before = studio.recipe.copy()
        studio._point(SimpleNamespace(local_position=SimpleNamespace(x=float('nan'), y=0)))
        self.assertEqual(before, studio.recipe)

    def test_resize_keeps_wheel_circular_and_marker_inside(self):
        studio = self.studio
        studio._resized(SimpleNamespace(width=150))
        self.assertEqual((studio.field.width, studio.field.height, studio.field.border_radius), (150, 150, 75))
        self.assertGreaterEqual(studio.marker.left, 0)
        self.assertLessEqual(studio.marker.left + 20, 150)
        studio._resized(SimpleNamespace(width=900))
        self.assertEqual(studio.size, 224)

    def test_hex_keyboard_input_and_brightness_control_the_same_retained_wheel(self):
        studio = self.studio
        studio.hex_field.value = '107fa0'
        self.assertTrue(studio._hex_changed())
        self.assertEqual(studio.recipe['seed'], '#107FA0')
        hue, saturation, _ = studio.hsv
        studio.brightness.value = 50
        studio._brightness(None)
        self.assertEqual(studio.hsv, (hue, saturation, .5))
        self.assertAlmostEqual(studio.shade.opacity, .5)
        recipe = studio.recipe.copy()
        studio.hex_field.value = 'bad'
        self.assertFalse(studio._hex_changed())
        self.assertEqual(studio.recipe, recipe)
        with patch.object(config, 'save_config') as save:
            studio._save()
            save.assert_not_called()

    def test_failed_save_rolls_back_config_and_retry_saves_only_recipe(self):
        studio = self.studio
        studio.hex_field.value = '107FA0'
        studio._hex_changed()
        with patch.object(config, 'save_config', side_effect=OSError('disk full')):
            studio._save()
        self.assertIsNone(self.cfg[CUSTOM_PALETTE_KEY])
        self.assertFalse(studio.restart.visible)
        self.assertFalse(studio.save.disabled)
        with patch.object(config, 'save_config') as save:
            studio._save()
            save.assert_called_once_with(self.cfg)
        self.assertEqual(set(self.cfg[CUSTOM_PALETTE_KEY]), {'seed', 'depth', 'vividness'})
        self.assertTrue(studio.restart.visible)
        self.assertTrue(studio.save.disabled)
        studio._restore()
        self.assertIsNone(studio.recipe)
        with patch.object(config, 'save_config'):
            studio._save()
        self.assertIsNone(self.cfg[CUSTOM_PALETTE_KEY])
        self.assertEqual(studio.preview_play.bgcolor, PALETTE['ACCENT'])

    def test_old_saved_recipe_is_retained_without_extra_controls(self):
        recipe = dict(seed='#B743DF', depth=.8, vividness=.7)
        studio = ColorStudio(DriverPage(), {CUSTOM_PALETTE_KEY: recipe},
                             on_restart=lambda e: None, set_status=lambda m: None)
        self.assertEqual(studio.recipe, recipe)
        self.assertTrue(studio.save.disabled)
        studio._point(SimpleNamespace(local_position=SimpleNamespace(x=224, y=112)))
        self.assertEqual((studio.recipe['depth'], studio.recipe['vividness']), (.8, .7))
        self.assertFalse(hasattr(studio, 'depth') or hasattr(studio, 'vividness') or hasattr(studio, 'file_picker'))

    def test_appearance_retains_wheel_without_loading_images(self):
        import threading
        import app_driver
        from _fuzz_common import walk
        with patch.object(threading.Thread, 'start'), patch('builtins.open', wraps=open):
            driver = app_driver.build_headless()
            switch = inspect.getclosurevars(driver.tabs()['settings'].on_click).nonlocals['switch_tab']
            root = inspect.getclosurevars(switch).nonlocals['tabs']['settings']
            studio = next(control for control in walk(root) if getattr(control, 'data', None) == 'color-studio')
            root.select_section('appearance')
            self.assertIn(studio, list(walk(root)))
            wheel = next(control for control in walk(studio) if getattr(control, 'data', None) == 'color-wheel')
            self.assertIsInstance(wheel.content.controls[0].gradient, ft.SweepGradient)
            root.select_section('account')
            root.select_section('appearance')
            self.assertIs(next(control for control in walk(root) if getattr(control, 'data', None) == 'color-studio'), studio)


if __name__ == '__main__':
    unittest.main()
