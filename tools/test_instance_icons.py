"""Bundled SVG catalog and per-instance icon editing/persistence, offline."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import types
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
            def picker():
                return VersionPicker(app_driver.DriverPage(),get_selected=lambda:'vanilla-v1',label_for=lambda v:v,
                  get_instances=lambda:[{'id':'vanilla-v1','loader':'vanilla'},{'id':'fabric-v2','loader':'fabric'}],
                  on_pick=picked.append,on_browse_online=lambda:None,
                  get_icon=scope['_instance_icon'],on_set_icon=scope['_save_instance_icon'])
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
                self.assertTrue(all(c is not p.page for c in refreshes))

if __name__=='__main__': unittest.main()
