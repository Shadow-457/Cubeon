"""Bundled SVG catalog and per-instance icon editing/persistence, offline."""
import ast
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import atomicio, instance_icons, instances, thread_safe_ui
from ui.versions import VersionPicker
import app_driver
from _fuzz_common import walk

class InstanceIconsTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.custom_dir = patch.object(instance_icons, 'CUSTOM_DIR', self.root / 'stored')
        self.custom_dir.start()
        self.addCleanup(self.custom_dir.stop)
        instance_icons._custom_source.cache_clear()
        self.addCleanup(instance_icons._custom_source.cache_clear)

    def image(self):
        from PIL import Image
        path = self.root / 'original.png'
        Image.new('RGBA', (240, 120), (20, 180, 80, 120)).save(path)
        return path

    def gif(self, *, loop=0):
        from PIL import Image
        path = self.root / 'animated.gif'
        first = Image.new('RGBA', (64, 32))
        first.paste((0, 0, 0, 255), (8, 8, 16, 16))
        second = Image.new('RGBA', (64, 32))
        second.paste((255, 0, 0, 255), (40, 8, 48, 16))
        first.save(path, save_all=True, append_images=[second], duration=[80, 170],
                   disposal=2, **({'loop': loop} if loop is not None else {}))
        return path

    def test_gif_retains_animation_timing_loop_and_transparency_after_original_moves(self):
        from PIL import Image
        for loop in (0, 3, None):
            with self.subTest(loop=loop):
                path = self.gif(loop=loop)
                original = path.read_bytes()
                key = instance_icons.import_image(path)
                self.assertEqual(instance_icons.import_image(path), key)
                self.assertEqual(path.read_bytes(), original)
                self.assertTrue((instance_icons.CUSTOM_DIR / (key + '.gif')).is_file())
                path.unlink()
                with Image.open(io.BytesIO(base64.b64decode(instance_icons.source(key)))) as icon:
                    self.assertEqual(icon.format, 'GIF')
                    self.assertEqual(icon.size, (128, 128))
                    self.assertEqual(icon.n_frames, 2)
                    self.assertEqual(icon.info.get('loop'), loop)
                    self.assertEqual(icon.info['duration'], 80)
                    first = icon.convert('RGBA')
                    self.assertEqual(first.getpixel((44, 60)), (0, 0, 0, 255))
                    self.assertEqual(first.getpixel((0, 0))[3], 0)
                    icon.seek(1)
                    self.assertEqual(icon.info['duration'], 170)
                    second = icon.convert('RGBA')
                    self.assertEqual(second.getpixel((76, 60)), (255, 0, 0, 255))
                    self.assertEqual(second.getpixel((44, 60))[3], 0)

    def test_gif_display_uses_animated_bytes_and_import_limits_do_not_replace_existing_icon(self):
        key = instance_icons.import_image(self.gif())
        picture = instance_icons.source(key)
        p = VersionPicker(app_driver.DriverPage(), get_selected=lambda: 'instance', label_for=lambda v: v,
                          on_pick=lambda *a: None, on_browse_online=lambda: None, get_icon=lambda v: key)
        row, _, _ = p._installed_row({'id': 'instance', 'loader': 'fabric'}, False)
        self.assertTrue(any(getattr(c, 'src', None) == picture for c in walk(row)))
        p._mode, p._new_icon = 'new', key
        p._render_icons()
        self.assertEqual(p.custom_icon_preview.src, picture)
        retired = []
        with patch.object(thread_safe_ui, 'refresh'), patch.object(
                threading, 'Timer', side_effect=lambda delay, fn: types.SimpleNamespace(
                    daemon=False, start=lambda: retired.append(fn))):
            p.open()
            p._mode, p._new_step = 'new', 3
            p._apply_mode()
            p._render_icons()
            p.close()
            retired.pop()()
            self.assertFalse(p.list.visible)
            self.assertFalse(p.icon_categories.visible)
            p.open()
            self.assertTrue(p.list.visible)
        with patch.object(instance_icons, '_MAX_STORED_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'shorter or simpler GIF'):
                instance_icons.import_image(self.gif(loop=4))
        self.assertEqual(instance_icons.source(key), picture)
        self.assertEqual(len(list(instance_icons.CUSTOM_DIR.iterdir())), 1)

    def test_custom_image_is_portable_small_deduplicated_and_keeps_transparency(self):
        from PIL import Image
        path = self.image()
        original = path.read_bytes()
        key = instance_icons.import_image(path)
        self.assertTrue(instance_icons.valid(key))
        self.assertEqual(key, instance_icons.import_image(path))
        self.assertEqual(len(list(instance_icons.CUSTOM_DIR.iterdir())), 1)
        self.assertEqual(path.read_bytes(), original)
        path.unlink()
        with Image.open(io.BytesIO(base64.b64decode(instance_icons.source(key)))) as icon:
            self.assertEqual(icon.size, (128, 128))
            self.assertEqual(icon.getpixel((0, 0))[3], 0)
            self.assertEqual(icon.getpixel((64, 64))[3], 120)
            self.assertTrue(all(abs(actual - expected) <= 1 for actual, expected in
                                zip(icon.getpixel((64, 64))[:3], (20, 180, 80))))
        self.assertFalse(instance_icons.valid('custom-../../outside'))
        self.assertEqual(instance_icons.source('custom-' + '0' * 64, loader='fabric'),
                         'instance_icons/mob-creeper.svg')

    def test_invalid_or_failed_import_keeps_existing_icon_and_leaves_no_temp_file(self):
        valid = instance_icons.import_image(self.image())
        stored = instance_icons.source(valid)
        invalid = self.root / 'invalid.png'
        invalid.write_bytes(b'not an image')
        with self.assertRaises(ValueError):
            instance_icons.import_image(invalid)
        other = self.root / 'other.png'
        from PIL import Image
        Image.new('RGB', (8, 8), 'red').save(other)
        with patch.object(instance_icons.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                instance_icons.import_image(other)
        self.assertEqual(instance_icons.source(valid), stored)
        self.assertEqual(len(list(instance_icons.CUSTOM_DIR.iterdir())), 1)

    def test_compact_upload_new_flow_cancel_and_stale_completion(self):
        completions, committed = [], []
        p = VersionPicker(app_driver.DriverPage(), get_selected=lambda: 'old', label_for=lambda v: v,
                          on_pick=lambda *args: self.fail('Uploading must not select an instance'),
                          on_browse_online=lambda: None, on_create=lambda *args: committed.append(args),
                          on_upload_icon=completions.append)
        key = instance_icons.import_image(self.image())
        with patch.object(thread_safe_ui, 'refresh'):
            p.icon_upload.on_click(None)
            self.assertEqual(completions, [])
            p.open()
            p._mode, p._new_step, p._new_version = 'new', 3, '1.20.1'
            p._apply_mode()
            p._render_icons()
            original_layout = tuple(p.panel.content.controls)
            original_tiles = len(list(walk(p.list)))
            self.assertEqual((p.icon_upload.width, p.icon_upload.height), (32, 32))
            p.icon_upload.on_click(None)
            p.icon_upload.on_click(None)
            self.assertEqual(len(completions), 1)
            completions.pop()(None)
            self.assertFalse(p.icon_upload.disabled)
            p.icon_upload.on_click(None)
            completions.pop()(key)
            self.assertEqual(p._new_icon, key)
            self.assertTrue(p.custom_icon_preview.visible)
            self.assertEqual(tuple(p.panel.content.controls), original_layout)
            self.assertEqual(len(list(walk(p.list))), original_tiles)
            self.assertEqual(committed, [])
            p._back()
            p._next()
            self.assertEqual(p._new_icon, key)
            p.icon_upload.on_click(None)
            p.close()
            completions.pop()('block-tnt')
            self.assertEqual(p._new_icon, key)
            self.assertFalse(p.icon_upload.disabled)
            p.open()
            p._mode, p._new_step, p._new_version = 'new', 3, '1.20.1'
            p._next()
            self.assertEqual(committed, [('1.20.1', 'vanilla', key)])

    def test_main_upload_uses_one_picker_and_imports_off_the_ui_thread(self):
        import flet as ft
        from test_content_install_feedback import QueuedThread
        tree = ast.parse((ROOT / 'main.py').read_text())
        upload = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                      and n.name == '_upload_instance_icon')
        wrapper = ast.parse('def make_upload():\n    instance_icon_picker = None\n    return None').body[0]
        wrapper.body[1:] = [upload, ast.Return(value=ast.Name(id='_upload_instance_icon', ctx=ast.Load()))]
        chooser_calls, results, errors = [], [], []
        page = app_driver.DriverPage()
        scope = {'page': page, 'ft': ft, 'threading': threading, 'thread_safe_ui': thread_safe_ui,
                 'show_snack': errors.append,
                 'run_file_picker': lambda page, picker, **kw: chooser_calls.append((picker, kw))}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                     '<main icon upload>', 'exec'), scope)
        pick = scope['make_upload']()
        with patch.object(thread_safe_ui, 'refresh'), patch.object(threading, 'Thread', QueuedThread):
            QueuedThread.jobs.clear()
            pick(results.append)
            chooser, request = chooser_calls[-1]
            self.assertEqual(request['allowed_extensions'], ['png', 'jpg', 'jpeg', 'webp', 'gif'])
            request['on_files']([])
            self.assertEqual(len(results), 1)
            self.assertIsNone(results[0])
            pick(results.append)
            self.assertIs(chooser_calls[-1][0], chooser)
            self.assertEqual(page.overlay.count(chooser), 1)
            chooser_calls[-1][1]['on_files']([types.SimpleNamespace(path=str(self.image()))])
            self.assertEqual(len(results), 1)
            self.assertIsNone(results[0])
            self.assertEqual(len(QueuedThread.jobs), 1)
            QueuedThread.jobs.pop()()
            self.assertTrue(instance_icons.is_custom(results[-1]))
            self.assertEqual(errors, [])
            pick(results.append)
            chooser_calls[-1][1]['on_files']([types.SimpleNamespace(path=None)])
            self.assertIsNone(results[-1])
            self.assertIn('saved on this computer', errors[-1])

    def test_catalog(self):
        self.assertEqual(len(instance_icons.CATALOG),40)
        self.assertEqual(len(instance_icons.BLOCKS),20)
        self.assertEqual(len(instance_icons.MOBS),20)
        self.assertEqual(len({i['id'] for i in instance_icons.CATALOG}),40)
        pictures=[]
        for icon in instance_icons.CATALOG:
            source=(ROOT/'assets'/icon['src']).read_text()
            tree=ET.fromstring(source)
            self.assertTrue(tree.tag.endswith('svg'))
            self.assertIn('viewBox',tree.attrib)
            self.assertNotIn('href=',source)
            self.assertNotIn('<script',source)
            pictures.append(source)
        self.assertEqual(len(set(pictures)),40)
        self.assertFalse(instance_icons.valid('../../etc/passwd'))
        self.assertEqual(instance_icons.source('invalid'),'instance_icons/block-grass.svg')

    def test_edit_persists_without_switching_or_new_window(self):
        # Use the real main callbacks with a local atomic config destination.
        tree=ast.parse((ROOT/'main.py').read_text())
        functions=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in ('_instance_icon','_save_instance_icon')]
        with tempfile.TemporaryDirectory() as directory:
            config_path=Path(directory)/'config.json'
            cfg={'instance_icons':{'other':'mob-pig'},'version_labels':{'vanilla-v1':'My world'}}
            state={'installed':['vanilla-v1','fabric-v2'],'installed_meta':{}}
            snacks=[]
            def save(value): atomicio.write_json(str(config_path),value)
            core=types.SimpleNamespace(save_config=save)
            scope={'cfg':cfg,'state':state,'instance_info':instances,'core':core,'show_snack':snacks.append}
            exec(compile(ast.Module(body=functions,type_ignores=[]),'<icon callbacks>','exec'),scope)
            picked=[]
            uploads=[]
            def picker():
                return VersionPicker(app_driver.DriverPage(),get_selected=lambda:'vanilla-v1',label_for=lambda v:v,
                  get_instances=lambda:[{'id':'vanilla-v1','loader':'vanilla'},{'id':'fabric-v2','loader':'fabric'}],
                  on_pick=picked.append,on_browse_online=lambda:None,
                  get_icon=scope['_instance_icon'],on_set_icon=scope['_save_instance_icon'],
                  on_upload_icon=uploads.append)
            p=picker()
            refreshes=[]
            with patch.object(thread_safe_ui,'refresh',side_effect=refreshes.append):
                p.open()
                pencil=next(c for c in walk(p.panel) if getattr(c,'data',None)=='instance-icon-edit-fabric-v2')
                pencil.on_click(None)
                self.assertEqual(p._mode,'icons')
                self.assertFalse(p.filter_field.visible)
                self.assertFalse(p.browse_link.visible)
                options=[c for c in walk(p.list) if str(getattr(c,'data','')).startswith('instance-icon-option-')]
                self.assertEqual(len(options),20)
                self.assertTrue(all(c.data.startswith('instance-icon-option-mob-') for c in options))
                p._change_icon_category('block')
                option=next(c for c in walk(p.list) if getattr(c,'data',None)=='instance-icon-option-block-tnt')
                option.on_click(None)
                self.assertEqual(p._mode,'installed')
                self.assertEqual(picked,[])
                saved=json.loads(config_path.read_text())
                self.assertEqual(saved['instance_icons'],{'other':'mob-pig','fabric-v2':'block-tnt'})
                self.assertEqual(saved['version_labels'],cfg['version_labels'])
                rebuilt=picker()
                row,_,_=rebuilt._installed_row({'id':'fabric-v2','loader':'fabric'},False)
                self.assertTrue(any(getattr(c,'src',None)=='instance_icons/block-tnt.svg' for c in walk(row)))
                p._open_icons('fabric-v2')
                with patch.object(core,'save_config',side_effect=OSError('disk full')):
                    p._choose_icon('mob-bee')
                self.assertEqual(p._mode,'icons')
                self.assertEqual(cfg['instance_icons']['fabric-v2'],'block-tnt')
                self.assertEqual(len(snacks),1)
                self.assertFalse(scope['_save_instance_icon']('missing','mob-cat'))
                self.assertFalse(scope['_save_instance_icon']('fabric-v2','bad-path'))
                custom = instance_icons.import_image(self.image())
                p.icon_upload.on_click(None)
                with patch.object(core, 'save_config', side_effect=OSError('disk full')):
                    uploads.pop()(custom)
                self.assertEqual(cfg['instance_icons']['fabric-v2'], 'block-tnt')
                self.assertEqual(p._mode, 'icons')
                p.icon_upload.on_click(None)
                uploads.pop()(custom)
                self.assertEqual(p._mode, 'installed')
                self.assertEqual(json.loads(config_path.read_text())['instance_icons']['fabric-v2'], custom)
                row, _, _ = picker()._installed_row({'id':'fabric-v2','loader':'fabric'}, False)
                self.assertTrue(any(getattr(c, 'src', None) == instance_icons.source(custom) for c in walk(row)))
                self.assertEqual(picked, [])
                self.assertTrue(all(c is not p.page for c in refreshes))

if __name__=='__main__': unittest.main()
