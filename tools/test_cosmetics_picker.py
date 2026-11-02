"""One-click selection/filtering reuses artwork and repaints only the picker."""
import contextlib
import os
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
from app_driver import DriverPage
import flet as ft
from PIL import Image
from cubeon import cosmetics, thread_safe_ui
from cubeon.theme import THEME, section_label, pixel_divider
import ui.skin_tab as skin_ui
from ui.appearance_preview import AppearancePreview

fz.install_safe_stubs()


class CosmeticsPicker(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.jobs = []
        jobs = self.jobs
        class QueuedThread:
            def __init__(self, target, args=(), **kwargs):
                self.target = lambda: target(*args)
            def start(self):
                jobs.append(self.target)
        self.stack.enter_context(patch.object(skin_ui, 'threading',
            SimpleNamespace(**{**vars(threading), 'Thread': QueuedThread})))
        self.stack.enter_context(patch.object(thread_safe_ui, 'refresh'))
        self.preview = self.stack.enter_context(patch.object(AppearancePreview, 'refresh'))
        self.raster = self.stack.enter_context(patch.object(cosmetics, 'render_thumbnail',
            return_value=Image.new('RGBA', (76, 76), 'white')))
        self.equip = self.stack.enter_context(patch.object(skin_ui.core, 'set_active_cosmetic',
            side_effect=lambda cfg, slot, item: cfg.update({f'active_{slot}_item': item})))
        self.stack.enter_context(patch.object(skin_ui.core, 'set_active_skin',
            side_effect=lambda cfg, filename: cfg.update(active_skin=filename)))
        self.stack.enter_context(patch.object(skin_ui.core, 'set_active_cape',
            side_effect=lambda cfg, filename: cfg.update(active_cape=filename, hide_cubeon_cape=False)))
        self.stack.enter_context(patch.object(skin_ui.core, 'set_hide_cubeon_cape',
            side_effect=lambda cfg, value: cfg.update(hide_cubeon_cape=value)))
        self.page = DriverPage()
        self.cfg = {'username': 'PickerFixture'}
        self.root = skin_ui.build_skin_section(self.page, self.cfg,
            section_label=section_label, pixel_divider=pixel_divider, **THEME,
            mc_version='1.21.11', mc_loader='fabric',
            file_picker=ft.FilePicker(), cape_file_picker=ft.FilePicker())

    def tab(self, label):
        control = next(c for c in fz.walk(self.root) if callable(getattr(c, 'on_click', None))
                       and any(getattr(t, 'value', None) == label for t in fz.walk(c)))
        control.on_click(None)

    def cards(self):
        return [c for c in fz.walk(self.root) if callable(getattr(c, 'set_selected', None))]

    def apply(self, tooltip):
        next(c for c in fz.walk(self.root) if isinstance(c, ft.Container)
             and c.tooltip == tooltip).cubeon_keyboard_button.on_click(None)

    def test_one_click_retains_cards_images_and_skips_repeated_apply(self):
        self.tab('Back')
        for job in list(self.jobs):
            job()
        cards = self.cards()
        images = [c for c in fz.walk(self.root) if isinstance(c, ft.Image)]
        rendered, jobs = self.raster.call_count, len(self.jobs)
        self.preview.reset_mock()
        self.apply('Apply Ember Wings (Small)')
        self.assertEqual(self.cfg['active_back_item'], 'back_ember_wings_small')
        self.assertEqual(cards, self.cards())
        self.assertEqual(images, [c for c in fz.walk(self.root) if isinstance(c, ft.Image)])
        self.assertEqual(self.preview.call_count, 1)
        self.apply('Apply Ember Wings (Small)')
        self.assertEqual(self.equip.call_count, 1)
        self.assertEqual(self.raster.call_count, rendered)
        self.assertEqual(len(self.jobs), jobs)
        self.assertEqual(self.page.update_calls, 0)
        self.assertIn('equipped: ember wings (small)', fz.subtree_text(self.root))

    def test_filters_and_pane_returns_preserve_cards(self):
        self.tab('Back')
        cards = self.cards()
        self.tab('Small wings')
        visible = [c for c in self.cards() if c.visible]
        self.assertEqual(len(visible), 5)
        self.assertTrue(all('small' in fz.subtree_text(c) for c in visible))
        self.tab('Skin')
        self.tab('Back')
        self.assertEqual(cards, self.cards())
        self.assertEqual(visible, [c for c in self.cards() if c.visible])
        self.tab('All')
        self.assertTrue(all(c.visible for c in cards))
        self.assertEqual(self.page.update_calls, 0)

    def test_remove_clears_only_the_current_slot(self):
        self.cfg['active_shoulder_item'] = 'shoulder_ember_fox'
        self.tab('Back')
        self.apply('Apply Ember Wings (Small)')
        remove = next(c for c in fz.walk(self.root) if c.tooltip == 'Remove the equipped item')
        self.assertFalse(remove.disabled)
        remove.on_click(None)
        self.assertIsNone(self.cfg['active_back_item'])
        self.assertEqual(self.cfg['active_shoulder_item'], 'shoulder_ember_fox')
        self.assertTrue(remove.disabled)
        self.assertIn('nothing equipped', fz.subtree_text(self.root))

    def test_skin_and_cape_choices_retain_their_images(self):
        cards = self.cards()
        self.apply('Apply steve')
        self.assertEqual(self.cfg['active_skin'], 'steve.png')
        self.assertEqual(cards, self.cards())
        self.tab('Cape')
        cards = self.cards()
        self.apply('Apply None (No cape on your screen)')
        self.assertTrue(self.cfg['hide_cubeon_cape'])
        self.apply('Apply Cubeon Cape (Default)')
        self.assertFalse(self.cfg['hide_cubeon_cape'])
        self.assertEqual(cards, self.cards())
        self.assertEqual(self.page.update_calls, 0)


if __name__ == '__main__':
    unittest.main()
