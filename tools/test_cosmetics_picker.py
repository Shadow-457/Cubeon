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
import msgpack
from flet.controls.base_control import BaseControl
from flet.controls.object_patch import ObjectPatch
from flet.messaging.protocol import configure_encode_object_for_msgpack
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
        return [c for c in self.picker_controls() if callable(getattr(c, 'set_selected', None))
                and callable(getattr(c, 'set_sublabel', None))]

    def picker_controls(self):
        stack = next(c for c in fz.walk(self.root) if c.data == 'cosmetics-panes')
        pane = next(c for c in stack.controls if c.visible)
        return fz.walk(pane)

    def grid(self):
        return next(c for c in self.picker_controls() if isinstance(c, ft.GridView))

    def apply(self, tooltip):
        next(c for c in self.picker_controls() if isinstance(c, ft.Container)
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

    def test_one_thumbnail_worker_defers_hidden_panes_and_filtered_cards(self):
        self.tab('Back')
        self.assertEqual(len(self.jobs), 1)
        self.tab('Pets')
        self.assertEqual(len(self.jobs), 1)
        self.jobs.pop(0)()
        shoulder_count = len(self.grid().thumb_window)
        self.assertEqual(self.raster.call_count, shoulder_count)
        self.assertTrue(all(call.args[0]['slot'] == 'shoulder' for call in self.raster.call_args_list))
        self.assertTrue(all(call.kwargs['size'] == (64, 64) for call in self.raster.call_args_list))
        self.tab('Back')
        self.tab('Small wings')
        self.assertEqual(len(self.jobs), 1)
        before = self.raster.call_count
        self.jobs.pop(0)()
        self.assertEqual(self.raster.call_count - before, 5)
        self.assertTrue(all(call.args[0]['id'].endswith('_small')
                            for call in self.raster.call_args_list[before:]))
        self.tab('All')
        self.jobs.pop(0)()
        rendered_ids = [call.args[0]['id'] for call in self.raster.call_args_list]
        self.assertEqual(len(rendered_ids), len(set(rendered_ids)))
        self.assertLess(self.raster.call_count, len(cosmetics.items('back')) + len(cosmetics.items('shoulder')))
        self.tab('Pets')
        self.tab('Back')
        self.assertFalse(self.jobs)
        self.assertTrue(all(image.cache_width == image.width for card in self.cards()
                            for image in fz.walk(card) if isinstance(image, ft.Image)))

    def test_switching_during_thumbnail_render_does_not_drain_old_pane(self):
        self.tab('Back')
        def render(item, *args, **kwargs):
            if item['slot'] == 'back':
                self.tab('Pets')
            return Image.new('RGBA', (64, 64), 'white')
        self.raster.side_effect = render
        self.jobs.pop(0)()
        self.assertFalse(self.jobs)
        self.assertEqual(sum(call.args[0]['slot'] == 'back' for call in self.raster.call_args_list), 1)
        self.assertEqual(self.raster.call_count, 1 + len(self.grid().thumb_window))
        self.assertEqual(self.page.update_calls, 0)

    def test_remove_clears_only_the_current_slot(self):
        self.cfg['active_shoulder_item'] = 'shoulder_ember_fox'
        self.tab('Back')
        self.apply('Apply Ember Wings (Small)')
        remove = next(c for c in self.picker_controls() if c.tooltip == 'Remove the equipped item')
        self.assertFalse(remove.disabled)
        remove.on_click(None)
        self.assertIsNone(self.cfg['active_back_item'])
        self.assertEqual(self.cfg['active_shoulder_item'], 'shoulder_ember_fox')
        self.assertTrue(remove.disabled)
        self.assertIn('nothing equipped', fz.subtree_text(self.root))

    def test_butterfly_aura_equips_independently_and_loads_art_only_on_open(self):
        self.cfg['active_back_item'] = 'back_ember_wings_small'
        self.cfg['active_shoulder_item'] = 'shoulder_ember_fox'
        rendered = self.raster.call_count
        self.tab('Aura')
        self.assertIn('celestial butterfly aura', fz.subtree_text(self.root))
        self.assertEqual(self.raster.call_count, rendered)
        self.apply('Apply Celestial Butterfly Aura')
        self.assertEqual(self.cfg['active_aura_item'], 'aura_butterfly')
        self.assertEqual(self.cfg['active_back_item'], 'back_ember_wings_small')
        self.assertEqual(self.cfg['active_shoulder_item'], 'shoulder_ember_fox')

    def test_head_and_downloaded_feet_use_the_existing_picker(self):
        self.tab('Head')
        self.apply('Apply Ember Horns')
        self.assertEqual(self.cfg['active_head_item'], 'head_horns')
        shoe = {'id': 'store_shoe_fixture', 'slot': 'feet', 'name': 'Harbor High Tops', 'blurb': 'Sneakers'}
        with patch.object(cosmetics, 'items', return_value=[shoe]), \
                patch.object(cosmetics, 'get', side_effect=lambda key, *args: shoe if key == shoe['id'] else None):
            self.tab('Feet')
            self.apply('Apply Harbor High Tops')
            self.assertEqual(self.cfg['active_feet_item'], shoe['id'])
            self.assertEqual(self.cfg['active_head_item'], 'head_horns')
            self.assertEqual(self.page.update_calls, 0)

    def test_downloaded_delete_keeps_other_cards_and_clears_only_its_slot(self):
        entry = dict(id="store_" + "a" * 32, slot="back", name="Downloaded Wings", blurb="Local revision",
                     feathers=[{}], wing_flare=True, _store_directory="local", store_id="sample")
        extra = [entry]
        original_items, original_get = cosmetics.items, cosmetics.get
        def items(slot=None, directory=None):
            return original_items(slot, directory) + (extra if slot in (None, "back") else [])
        def get(item_id, directory=None):
            return next((item for item in extra if item["id"] == item_id), None) or original_get(item_id, directory)
        def delete(cfg, item_id):
            extra.clear()
            if cfg.get("active_back_item") == item_id:
                cfg["active_back_item"] = None
        with patch.object(cosmetics, "items", side_effect=items), patch.object(cosmetics, "get", side_effect=get), \
                patch.object(skin_ui.core, "delete_downloaded_cosmetic", side_effect=delete) as remove:
            self.cfg.update(active_back_item=entry["id"], active_shoulder_item="shoulder_ember_fox")
            self.tab("Back")
            cards = self.cards()
            downloaded = next(card for card in cards if "downloaded wings" in fz.subtree_text(card))
            images = [c for card in cards if card is not downloaded for c in fz.walk(card) if isinstance(c, ft.Image)]
            self.preview.reset_mock()
            button = next(c for c in fz.walk(downloaded) if isinstance(c, ft.PopupMenuItem) and c.tooltip == "Delete")
            button.on_click(None)
            remove.assert_called_once_with(self.cfg, entry["id"])
            self.assertEqual(self.cards(), [card for card in cards if card is not downloaded])
            self.assertEqual(images, [c for card in self.cards() for c in fz.walk(card) if isinstance(c, ft.Image)])
            self.assertIsNone(self.cfg["active_back_item"])
            self.assertEqual(self.cfg["active_shoulder_item"], "shoulder_ember_fox")
            self.assertEqual(self.preview.call_count, 1)
            self.assertEqual(self.page.update_calls, 0)

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

    def test_cached_category_switch_only_sends_visibility_without_remounting(self):
        self.tab('Back')
        self.jobs.pop(0)()
        self.tab('Pets')
        self.jobs.pop(0)()
        stack = next(c for c in fz.walk(self.root) if c.data == 'cosmetics-panes')
        ObjectPatch.from_diff(None, stack, BaseControl)
        controls = [id(c) for c in fz.walk(stack)]
        self.tab('Back')
        with thread_safe_ui.update_scope(stack):
            change, added, removed = ObjectPatch.from_diff(stack, stack, BaseControl)
        encode = configure_encode_object_for_msgpack(BaseControl)
        patch_bytes = msgpack.packb(change.to_message(), default=encode)
        self.assertFalse(added)
        self.assertFalse(removed)
        self.assertEqual(controls, [id(c) for c in fz.walk(stack)])
        self.assertNotIn(b'src', patch_bytes)
        self.assertLess(len(patch_bytes), 2048)
        self.assertEqual(sum(pane.visible for pane in stack.controls), 1)

    def test_native_category_preparation_coalesces_without_catalogue_reads_on_click(self):
        jobs = []
        self.page.run_thread = lambda callback: jobs.append(callback)
        with patch.object(thread_safe_ui, 'has_ui_loop', return_value=True):
            self.root = skin_ui.build_skin_section(self.page, self.cfg,
                section_label=section_label, pixel_divider=pixel_divider, **THEME,
                mc_version='1.21.11', mc_loader='fabric',
                file_picker=ft.FilePicker(), cape_file_picker=ft.FilePicker())
        with patch.object(cosmetics, 'items', wraps=cosmetics.items) as catalogue:
            self.tab('Back')
            self.tab('Head')
            self.tab('Pets')
            self.assertEqual(len(jobs), 1)
            self.assertEqual(catalogue.call_count, 0)
            stack = next(c for c in fz.walk(self.root) if c.data == 'cosmetics-panes')
            self.assertEqual(sum(pane.visible for pane in stack.controls), 1)
            jobs.pop(0)()
            self.assertEqual(catalogue.call_count, 1)
            self.assertEqual(catalogue.call_args.args[0], 'shoulder')
            self.assertTrue(self.cards())

    def test_superseded_library_read_cannot_restore_a_removed_item(self):
        self.tab('Back')
        stack = next(c for c in fz.walk(self.root) if c.data == 'cosmetics-panes')
        reload_items = next(pane for pane in stack.controls if pane.visible).content.load_items
        current = cosmetics.items('back')
        stale = dict(id='store_removed_fixture', slot='back', name='Removed Wings', blurb='Old revision')
        first = True
        def read(slot=None, directory=None):
            nonlocal first
            if first:
                first = False
                # A newer refresh completes while this older read is pending.
                reload_items()
                return current + [stale]
            return current
        with patch.object(cosmetics, 'items', side_effect=read):
            self.assertFalse(reload_items())
        self.assertFalse(any('removed wings' in fz.subtree_text(card) for card in self.cards()))

    def test_default_steve_card_has_real_art_and_clears_custom_skin(self):
        image = next(c for c in fz.walk(self.root) if isinstance(c, ft.Image)
                     and c.src == skin_ui.DEFAULT_SKIN_PREVIEW_SRC)
        self.assertTrue(image.visible)
        self.apply('Apply steve')
        self.assertEqual(self.cfg['active_skin'], 'steve.png')
        self.apply('Apply Steve (Default Minecraft skin)')
        self.assertIsNone(self.cfg['active_skin'])
        self.assertIn('steve · default skin', fz.subtree_text(self.root))
        self.assertIn(image, list(fz.walk(self.root)))
        self.assertEqual(self.page.update_calls, 0)

    def test_grid_resize_fits_cards_without_rebuilding_or_rendering(self):
        self.tab('Back')
        self.apply('Apply Ember Wings (Small)')
        cards = self.cards()
        images = [c for c in fz.walk(self.root) if isinstance(c, ft.Image)]
        grid = next(c for c in fz.walk(self.root) if isinstance(c, ft.GridView)
                    and cards[0] in c.controls)
        jobs = len(self.jobs)
        for width in (280, 620, 180, 900):
            grid.on_size_change(SimpleNamespace(control=grid, width=width))
            self.assertEqual(cards, self.cards())
            self.assertEqual(images, [c for c in fz.walk(self.root) if isinstance(c, ft.Image)])
            columns = max(1, min(4, int((width + 12) / 160)))
            self.assertEqual(grid.runs_count, columns)
            cell_width = grid.child_aspect_ratio * grid.card_height
            self.assertAlmostEqual(columns * cell_width + (columns - 1) * 12, width)
        self.assertEqual(self.cfg['active_back_item'], 'back_ember_wings_small')
        self.assertEqual(len(self.jobs), jobs)
        self.assertEqual(self.raster.call_count, 0)
        self.assertEqual(self.page.update_calls, 0)

    def test_compact_layout_keeps_preview_small_and_picker_scroll_bounded(self):
        layout = next(c for c in fz.walk(self.root) if c.data == 'cosmetics-layout')
        picker = next(c for c in fz.walk(self.root) if c.data == 'cosmetics-picker')
        scroll = next(c for c in fz.walk(self.root) if c.data == 'cosmetics-picker-scroll')
        model = next(c for c in fz.walk(self.root) if c.data == 'appearance-model')
        viewport = next(c for c in fz.walk(self.root) if isinstance(c, ft.Container)
                        and isinstance(c.content, ft.GestureDetector))
        image = model.controls[1]
        self.assertEqual(self.root.opacity, 0)
        layout.on_size_change(SimpleNamespace(width=640))
        viewport.on_size_change(SimpleNamespace(width=640))
        self.assertEqual(self.root.opacity, 0)
        scroll.on_size_change(SimpleNamespace(control=scroll, width=608, height=150))
        self.assertEqual(self.root.opacity, 1)
        self.assertLessEqual(model.width, 176)
        for width in (640, 980, 380):
            layout.on_size_change(SimpleNamespace(width=width))
            viewport.on_size_change(SimpleNamespace(width=width if width < 760 else 300))
            self.assertIs(model.controls[1], image)
            self.assertLessEqual(model.width, 176 if width < 760 else 256)
            self.root.set_viewport_height(600)
            self.assertEqual(picker.height, 200 if width < 760 else 500)
            self.root.set_viewport_height(900)
            self.assertEqual(picker.height, 320 if width < 760 else 520)
            self.assertIn(scroll, list(fz.walk(picker)))
        self.assertEqual(scroll.scroll, ft.ScrollMode.ALWAYS)
        self.assertTrue(scroll.expand)
        self.assertEqual(self.page.update_calls, 0)

    def test_wardrobe_modes_keep_categories_and_controls_without_a_dropdown(self):
        modes = next(c for c in fz.walk(self.root) if c.data == 'wardrobe-modes')
        categories = next(c for c in fz.walk(self.root) if c.data == 'wardrobe-categories')
        controls = [id(c) for c in fz.walk(modes)] + [id(c) for c in fz.walk(categories)]
        self.assertFalse(any(isinstance(c, ft.Dropdown) for c in fz.walk(self.root)))
        self.tab('Head')
        cards = self.cards()
        self.tab('Browse')
        self.assertFalse(categories.visible)
        self.tab('My items')
        self.assertTrue(categories.visible)
        self.assertEqual(cards, self.cards())
        self.assertEqual(controls, [id(c) for c in fz.walk(modes)] + [id(c) for c in fz.walk(categories)])

    def test_hidden_capes_are_lazy_and_initial_preview_is_requested_once(self):
        self.preview.reset_mock()
        with patch.object(skin_ui.core, 'list_capes', wraps=skin_ui.core.list_capes) as read:
            self.root = skin_ui.build_skin_section(self.page,
                {'active_skin': 'steve.png', 'active_cape': 'custom.png'},
                section_label=section_label, pixel_divider=pixel_divider, **THEME,
                file_picker=ft.FilePicker(), cape_file_picker=ft.FilePicker())
            read.assert_not_called()
            self.preview.assert_called_once_with()
            self.tab('Cape')
            read.assert_called_once()
            self.tab('Head')
            self.tab('Cape')
            read.assert_called_once()

    def test_large_library_renders_nearby_rows_and_scrolls_without_remounting(self):
        template = cosmetics.items('head')[0]
        items = [{**template, 'id': f'head_fixture_{i}', 'name': f'Head {i}'} for i in range(200)]
        lookup = {item['id']: item for item in items}
        with patch.object(cosmetics, 'items', return_value=items), \
                patch.object(cosmetics, 'get', side_effect=lambda key, *_: lookup.get(key)):
            self.tab('Head')
            grid = self.grid()
            self.assertTrue(grid.build_controls_on_demand)
            self.assertEqual(grid.cache_extent, grid.card_height + 12)
            controls = [id(c) for c in fz.walk(grid)]
            self.jobs.pop(0)()
            self.assertEqual(self.raster.call_count, len(grid.thumb_window))
            self.assertLess(self.raster.call_count, 20)
            before = self.raster.call_count
            with patch.object(ft.context, 'disable_auto_update') as disable:
                grid.on_scroll(SimpleNamespace(control=grid, pixels=2000))
                disable.assert_called_once()
            self.jobs.pop(0)()
            self.assertGreater(self.raster.call_count, before)
            self.assertLess(self.raster.call_count, 40)
            self.assertEqual(controls, [id(c) for c in fz.walk(grid)])
            grid.on_scroll(SimpleNamespace(control=grid, pixels=0))
            self.assertFalse(self.jobs)
            self.assertEqual(self.page.update_calls, 0)

    def test_equipping_and_filters_do_not_refresh_the_whole_page_or_remount_filters(self):
        self.tab('Back')
        grid = self.grid()
        filters = [c for c in self.picker_controls() if callable(getattr(c, 'set_selected', None))
                   and not callable(getattr(c, 'set_sublabel', None))]
        with patch.object(thread_safe_ui, 'refresh') as repaint:
            self.apply('Apply Ember Wings (Small)')
            self.assertNotIn(grid, [call.args[0] for call in repaint.call_args_list])
        with patch.object(ft.context, 'disable_auto_update') as disable:
            self.tab('Small wings')
            self.assertTrue(disable.called)
        self.assertEqual(filters, [c for c in self.picker_controls() if callable(getattr(c, 'set_selected', None))
                                  and not callable(getattr(c, 'set_sublabel', None))])

    def test_upload_adds_skin_and_arm_menu_changes_only_that_card(self):
        entry = dict(filename='new.png', name='New skin', slim=False, model='auto')
        originals = skin_ui.core.list_custom_skins()
        with patch.object(skin_ui.core, 'add_custom_skin', return_value=entry), \
                patch.object(skin_ui.core, 'list_custom_skins', return_value=originals + [entry]):
            before = self.cards()
            # The upload handler is retained on the shared picker.
            import inspect
            upload = next(c for c in self.picker_controls() if isinstance(c, ft.Container)
                          and callable(c.on_click) and 'upload skin' in fz.subtree_text(c))
            handle = inspect.getclosurevars(upload.on_click).nonlocals['handle_skin_files']
            handle([SimpleNamespace(name='New skin.png', path='/fixture.png')])
            self.jobs[-1]()
            self.assertEqual(self.cfg['active_skin'], entry['filename'])
            self.assertTrue(all(card in self.cards() for card in before))
            added = next(card for card in self.cards() if 'new skin' in fz.subtree_text(card))
            menu = next(c for c in fz.walk(added) if isinstance(c, ft.PopupMenuItem)
                        and str(c.tooltip).startswith('Change arms:'))
            with patch.object(skin_ui.core, 'set_skin_model', side_effect=lambda *args: entry.update(model='slim', slim=True) or True):
                menu.on_click(None)
            self.assertTrue(all(card in self.cards() for card in before))
            self.assertNotIn(added, self.cards())
            self.assertIn('alex · 3 px', fz.subtree_text(self.root))


if __name__ == '__main__':
    unittest.main()
