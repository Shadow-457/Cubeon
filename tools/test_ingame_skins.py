"""Real authenticated skin bridge, persistence/isolation, Java worker and preview bounds."""
from pathlib import Path
import base64
import http.client
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import paths, skins, capes, config, local_api, cosmetics
from cubeon.ingame_skins import InGameSkins
from test_mod_bridge import find_jdk


HARNESS = r'''
package com.cubeon.client;
import com.cubeon.client.skins.*;
import com.cubeon.client.ui.*;
import java.nio.file.*;
import java.util.function.BooleanSupplier;
public final class SkinTest {
 static void check(boolean condition,String why) { if(!condition) throw new AssertionError(why); }
 static void await(BooleanSupplier condition) throws Exception {
  long end=System.nanoTime()+8_000_000_000L;
  while(!condition.getAsBoolean()&&System.nanoTime()<end) Thread.sleep(10);
  check(condition.getAsBoolean(),"skin worker completed");
 }
 static class Canvas implements ClientUi.Canvas {
  final int w,h;int count;boolean shoulderLabel;
  Canvas(int w,int h) { this.w=w;this.h=h; }
  public void fill(int x,int y,int x1,int y1,int color) {
   check(x>=0&&y>=0&&x1<=w&&y1<=h&&x<=x1&&y<=y1,"skin quads fit screen");count++;
  }
  public void text(String text,int x,int y,int color) {
   check(x-width(text)/2>=0&&x+(width(text)+1)/2<=w&&y>=0&&y+9<=h,"skin text fits: "+text);
  }
  public String translate(String key) {
   return switch(key) {
    case "cubeonclient.skins.title"->"Skins";case "cubeonclient.capes.title"->"Capes";
    case "cubeonclient.back.title"->"Back";case "cubeonclient.shoulder.title"->"Shoulder";
    default->key.substring(key.lastIndexOf('.')+1).replace('_',' ');
   };
  }
  public void textScaled(String label,int x,int y,int color,float scale) {
   if(label.equals("Shoulder")) shoulderLabel=true;
   text(label,x,y,color);
  }
 }
 public static void main(String[] args) throws Exception {
  if(args.length>0 && args[0].equals("gif-poll")) {
   check(LiveCape.get()==null,"Fresh game starts without cached selection");
   Bridge.get().setCapeSink(CapeAnimation::accept);Bridge.get().start();
   await(()->LiveCape.get()!=null && LiveCape.get().frames()!=null);
   check(LiveCape.get().frames().count()==3,"Authenticated startup poll loads every GIF frame");
   try(var library=new SkinLibrary("cape")) {
    library.open();await(()->!library.state().busy()&&!library.state().items().isEmpty());
    var applied=library.state().applied();
    check(applied.animation()!=null,"Cape library retains animation on active preview");
    library.select(applied.id());library.apply();await(()->!library.state().busy());
    check(LiveCape.get().frames()!=null && !LiveCape.get().hidden(),"GIF Confirm retains live animation");
    library.select("__none__");library.apply();await(()->!library.state().busy());
    check(LiveCape.get().hidden() && LiveCape.get().frames()==null,"None clears GIF animation through authenticated API");
   }
   System.out.println("Authenticated GIF startup poll, library Confirm and hide passed.");
   return;
  }
  try(var library=new SkinLibrary()) {
   long start=System.nanoTime();library.open();
   check(System.nanoTime()-start<100_000_000L,"opening skins does not block on HTTP");
   await(()->!library.state().busy()&&!library.state().items().isEmpty());
   check(library.state().items().size()==13,"only one library page loaded");
   check(LiveSkin.get()==null,"opening/previewing does not apply a skin");
   var chosen=library.state().items().get(1);library.select(chosen.id());
   var preview=new SkinPreview();Canvas c=new Canvas(200,240);
   preview.render(c,chosen,0,0,144,208,-20);int[] front=preview.pixels();
   check(java.util.Arrays.stream(front).anyMatch(pixel->pixel!=0),"real textured 3D model draws");
   preview.render(c,chosen,0,0,144,208,90);
   check(!java.util.Arrays.equals(front,preview.pixels()),"rotation changes model geometry");
   start=System.nanoTime();library.apply();
   check(System.nanoTime()-start<100_000_000L,"Apply queues off game thread");
   await(()->!library.state().busy());
   check(LiveSkin.get()!=null,"confirmed Apply reaches native skin adapter");
   check(library.state().applied().id().equals(chosen.id()),"same skin saved in launcher");
   library.lookup("bad name");await(()->!library.state().busy());
   check(library.state().status().contains("username"),"lookup failure shown without changing skin");
   check(library.state().applied().id().equals(chosen.id()),"failed lookup preserves active skin");
   library.model();await(()->!library.state().busy());
   check(library.state().selectedSkin().slim(),"explicit Alex model applies live");
   library.select("");library.apply();await(()->!library.state().busy());
   check(!LiveSkin.get().slim(),"Steve restores classic arms");
  }
  try(var capes=new SkinLibrary("cape")) {
   capes.open();await(()->!capes.state().busy()&&!capes.state().items().isEmpty());
   check(capes.state().items().size()==3,"cape library includes default, none and uploaded cape");
   check(LiveCape.get()==null,"browsing capes does not equip them");
   var cape=capes.state().items().get(2);capes.select(cape.id());
   var preview=new SkinPreview();var canvas=new Canvas(200,240);
   preview.render(canvas,capes.playerSkin(),cape,0,0,144,208,160,127);int[] withCape=preview.pixels();
   preview.render(canvas,capes.playerSkin(),null,0,0,144,208,160,127);
   check(!java.util.Arrays.equals(withCape,preview.pixels()),"cape appears on rotating player preview");
   capes.apply();await(()->!capes.state().busy());
   check(LiveCape.get()!=null&&!LiveCape.get().hidden(),"cape Confirm reaches live adapter");
   check(LiveCape.get().png().length>cape.png().length,"HD cape kept for game texture");
   capes.select("__none__");capes.apply();await(()->!capes.state().busy());
   check(LiveCape.get().hidden(),"No Cape hides immediately after Confirm");
   capes.select("");capes.apply();await(()->!capes.state().busy());
   check(!LiveCape.get().hidden(),"Cubeon Cape restores default");
  }
  try(var menu=new SkinMenu()) {
   var field=SkinMenu.class.getDeclaredField("library");field.setAccessible(true);
   var library=(SkinLibrary)field.get(menu);await(()->!library.state().busy());
   for(int[] size:new int[][]{{320,240},{640,360},{960,540}}) {
    Canvas canvas=new Canvas(size[0],size[1]);menu.render(canvas,size[0],size[1],0,0);
    check(canvas.count<15000,"preview work bounded by visible pixels");
    var bounds=SkinMenu.class.getDeclaredField("modelRect");bounds.setAccessible(true);
    var model=(HudMenu.Rect)bounds.get(menu);
    check(model.x()+model.w()/2==size[0]/2,"player preview centered in full viewport");
    var angle=SkinMenu.class.getDeclaredField("yaw");angle.setAccessible(true);
    int before=angle.getInt(menu);
    check(menu.click(model.x()+model.w()/2,model.y()+model.h()/2),"player captures drag");
    // Rendering while dragging must not replace the previous drag position with hover coordinates.
    menu.render(canvas,size[0],size[1],0,0);
    menu.drag(model.x()+model.w()/2+10,model.y()+model.h()/2);menu.release();
    check(angle.getInt(menu)==before-15,"rightward drag rotates in corrected direction");
    for(int part=0;part<6;part++) check(menu.activate(SkinMenu.LAYER+part),"layer toggle functional");
    menu.activate(SkinMenu.GRID);menu.render(canvas,size[0],size[1],0,0);
    menu.activate(SkinMenu.GRID);
   }
   library.select("");
   await(()->!library.state().busy());
   check(menu.activate(SkinMenu.CAPES),"cape tab opens");
   var capeField=SkinMenu.class.getDeclaredField("capeLibrary");capeField.setAccessible(true);
   var capeLibrary=(SkinLibrary)capeField.get(menu);await(()->!capeLibrary.state().busy());
   for(int[] size:new int[][]{{320,240},{640,360},{960,540}}) {
    menu.render(new Canvas(size[0],size[1]),size[0],size[1],0,0);
    menu.activate(SkinMenu.GRID);menu.render(new Canvas(size[0],size[1]),size[0],size[1],0,0);menu.activate(SkinMenu.GRID);
   }
   var cached=capeLibrary.state();menu.activate(SkinMenu.SKINS);menu.activate(SkinMenu.CAPES);
   check(capeLibrary.state()==cached&&!capeLibrary.state().busy(),"returning to cape tab retains loaded page");
   for(int tab:new int[]{SkinMenu.BACK_ITEMS,SkinMenu.SHOULDER}) {
    menu.activate(tab);
    var itemField=SkinMenu.class.getDeclaredField(tab==SkinMenu.BACK_ITEMS?"backLibrary":"shoulderLibrary");
    itemField.setAccessible(true);var items=(SkinLibrary)itemField.get(menu);
    await(()->!items.state().busy());
    check(items.state().items().size()==13,"cosmetic catalogue is paged with None");
    check(items.state().applied().id().equals("__none__"),"new slot begins unequipped");
    var chosen=items.state().items().get(1);items.select(chosen.id());
    check(chosen.cosmetic()!=null&&!chosen.cosmetic().quads().isEmpty(),"bundled item prepared on worker");
    check(items.state().applied().id().equals("__none__"),"browsing does not equip cosmetic");
    for(int[] size:new int[][]{{320,240},{640,360},{960,540}}) {
     Canvas canvas=new Canvas(size[0],size[1]);menu.render(canvas,size[0],size[1],0,0);
     check(canvas.count<15000,"cosmetic preview work remains bounded");
     check(canvas.shoulderLabel,"Shoulder category stays fully named at every GUI size");
     var rects=SkinMenu.class.getDeclaredField("controls");rects.setAccessible(true);
     var controls=(HudMenu.Rect[])rects.get(menu);
     check(controls[SkinMenu.WINGS_VISIBLE]!=null,"preview wing visibility stays reachable");
     for(int id:new int[]{SkinMenu.IMPORT,SkinMenu.DELETE,SkinMenu.EXPORT,SkinMenu.MODEL,SkinMenu.SEARCH})
      check(controls[id]==null,"cosmetics hide image-only actions");
     for(int id:new int[]{SkinMenu.SKINS,SkinMenu.CAPES,SkinMenu.BACK_ITEMS,SkinMenu.SHOULDER})
      check(controls[id]!=null && menu.hit(controls[id].x()+2,controls[id].y()+2)==id,"all category tabs clickable");
     menu.activate(SkinMenu.GRID);menu.render(new Canvas(size[0],size[1]),size[0],size[1],0,0);menu.activate(SkinMenu.GRID);
    }
    var cachedState=items.state();
    var previewField=SkinMenu.class.getDeclaredField("preview");previewField.setAccessible(true);
    var menuPreview=(SkinPreview)previewField.get(menu);
    menu.render(new Canvas(640,360),640,360,0,0);var visible=menuPreview.pixels();
    menu.activate(SkinMenu.WINGS_VISIBLE);menu.render(new Canvas(640,360),640,360,0,0);
    check(items.state()==cachedState,"wing visibility never equips or clears a selection");
    if(tab==SkinMenu.BACK_ITEMS) check(!java.util.Arrays.equals(visible,menuPreview.pixels()),"wing toggle hides only preview geometry");
    menu.activate(SkinMenu.SKINS);menu.activate(tab);await(()->!items.state().busy());
    var visibility=SkinMenu.class.getDeclaredField("previewWings");visibility.setAccessible(true);
    check(!visibility.getBoolean(menu),"preview visibility survives category changes");
    items.select(chosen.id());
    menu.activate(SkinMenu.WINGS_VISIBLE);menu.render(new Canvas(640,360),640,360,0,0);
    check(java.util.Arrays.equals(visible,menuPreview.pixels()),"wing preview can be restored without changing selection");
    var p=new SkinPreview();var c=new Canvas(200,240);
    p.render(c,items.playerSkin(),null,items.previewItems(),0,0,180,220,160,127);int[] equipped=p.pixels();
    p.render(c,items.playerSkin(),null,0,0,180,220,160,127);
    check(!java.util.Arrays.equals(equipped,p.pixels()),"chosen cosmetic draws on player model");
    var liveBody=LiveSkin.get();var liveCape=LiveCape.get();
    menu.activate(SkinMenu.APPLY);await(()->!items.state().busy());
    check(items.state().applied().id().equals(chosen.id()),"Confirm persists cosmetic through authenticated HTTP");
    check(LiveSkin.get()==liveBody&&LiveCape.get()==liveCape,"cosmetic Confirm preserves live body and cape");
    items.page(1);await(()->!items.state().busy());
    check(items.state().offset()==12,"next page exposes remaining catalogue items");
    items.select("__none__");menu.activate(SkinMenu.APPLY);await(()->!items.state().busy());
    check(items.state().applied().id().equals("__none__"),"None removes only this slot");
   }
   menu.activate(SkinMenu.SKINS);
   menu.focus();menu.paste("Test_123");check(menu.type('!'),"typing owns input");
   menu.backspace();check(menu.escape(),"Escape releases text before returning to parent");
  }
  // Every bundled wing/pet must fit a full orbit, including the giant variants.
  try(var library=new SkinLibrary()) {
   library.open();await(()->!library.state().busy());
   var body=library.state().applied();
   var p=new SkinPreview();var c=new Canvas(100,140);
   for(var item:com.cubeon.client.cosmetics.CosmeticCatalog.get().items()) {
    if(!item.slot.equals("back")&&!item.slot.equals("shoulder")) continue;
    var model=CosmeticPreview.load(item.id);check(model!=null,"every wing/pet texture decodes");
    for(int yaw:new int[]{0,90,180,270}) {
     p.render(c,body,null,java.util.List.of(model),0,0,100,140,yaw,127);
     var pixels=p.pixels();
     check(java.util.Arrays.stream(pixels).anyMatch(pixel->pixel!=0),"orbit draws a textured model");
     for(int x=0;x<100;x++) check(pixels[x]==0&&pixels[13900+x]==0,"orbit has vertical padding");
     for(int y=0;y<140;y++) check(pixels[y*100]==0&&pixels[y*100+99]==0,"orbit has horizontal padding");
    }
   }
  }
  System.out.println("Skin worker, explicit/live Apply, model, preview, errors and responsive bounds passed.");
 }
}
'''


class SkinTests(unittest.TestCase):
    def setUp(self):
        builtin_catalogue = patch.object(capes, "list_builtin_capes", return_value=[])
        builtin_catalogue.start()
        self.addCleanup(builtin_catalogue.stop)
        skins._save_skins_meta({"skins": []})
        capes._save_capes_meta({"capes": []})
        self.cfg = dict(config.DEFAULT_CONFIG, username="SkinTester", manage_skin_mod=False,
                        csl_enabled=True, active_skin=None)
        self.state = {"running_version": "fabric-skin-test", "selected_version": "other-instance"}
        self.game = paths.game_dir_for(self.state["running_version"])
        self.service = InGameSkins(self.cfg, self.state)
        self.png = Path(paths.CUBEON_HOME) / "input.png"
        skins.default_base_skin().save(self.png)

    def upload(self):
        return self.service.action({"action": "import", "path": str(self.png)})["selected"]

    def apply(self, filename, **extra):
        return self.service.action({"action": "apply", "id": filename, "game_dir": self.game, **extra})

    def test_import_preview_does_not_apply_and_legacy_normalizes(self):
        entry = self.upload()
        self.assertTrue(entry)
        self.assertIsNone(self.cfg["active_skin"])
        self.assertEqual(self.service.snapshot()["applied"]["name"], "Steve")
        skins.default_base_skin().crop((0, 0, 64, 32)).save(self.png)
        result = self.service.action({"action": "import", "path": str(self.png)})
        data = base64.b64decode(next(i for i in result["items"] if i["id"] == result["selected"])["png"])
        from PIL import Image
        import io
        self.assertEqual(Image.open(io.BytesIO(data)).size, (64, 64))

    def test_aura_applies_and_clears_without_replacing_pets_or_wings(self):
        self.cfg.update(active_back_item='back_ember_wings_small',
                        active_shoulder_item='shoulder_ember_fox')
        page = self.service.snapshot(kind='aura')
        self.assertEqual([item['id'] for item in page['items']],
                         ['__none__', 'aura_shadow'])
        self.service.action({'kind': 'aura', 'action': 'apply',
                             'id': 'aura_shadow', 'game_dir': self.game})
        mirror = Path(cosmetics.game_config_path(self.game))
        self.assertEqual(json.loads(mirror.read_text())['aura'], 'aura_shadow')
        self.service.action({'kind': 'aura', 'action': 'apply',
                             'id': '__none__', 'game_dir': self.game})
        payload = json.loads(mirror.read_text())
        self.assertIsNone(payload['aura'])
        self.assertEqual(payload['back'], 'back_ember_wings_small')
        self.assertEqual(payload['shoulder'], 'shoulder_ember_fox')
        with self.assertRaises(ValueError):
            self.service.action({'kind': 'aura', 'action': 'apply',
                                 'id': 'shoulder_ember_fox', 'game_dir': self.game})

    def test_cosmetic_pages_apply_and_cross_slot_isolation_without_csl(self):
        self.cfg["csl_enabled"] = False
        self.cfg["active_cape"] = "untouched.png"
        self.cfg["active_skin"] = "untouched.png"
        other = Path(paths.game_dir_for("other-instance")) / "config/cubeon-cosmetics.json"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_bytes(b"other instance")
        choices = {}
        for kind in ("back", "shoulder"):
            page = self.service.snapshot(kind=kind)
            self.assertEqual(len(page["items"]), 13)
            self.assertEqual(page["items"][0]["id"], "__none__")
            self.assertEqual(page["applied"]["id"], "__none__")
            ids = [i["id"] for i in page["items"][1:]]
            ids += [i["id"] for i in self.service.snapshot(12, kind)["items"][1:]]
            self.assertEqual(ids, [i["id"] for i in cosmetics.items(kind)])
            choices[kind] = ids[-1]
            result = self.service.action({"kind": kind, "action": "apply", "id": ids[-1], "game_dir": self.game})
            self.assertEqual(result["applied"]["id"], ids[-1])
            self.assertTrue(result["skin_support"])
            self.assertEqual(config.load_config()[f"active_{kind}_item"], ids[-1])
        mirror = Path(cosmetics.game_config_path(self.game))
        payload = json.loads(mirror.read_text())
        self.assertEqual(payload["back"], choices["back"])
        self.assertEqual(payload["shoulder"], choices["shoulder"])
        self.service.action({"kind": "back", "action": "apply", "id": "__none__", "game_dir": self.game})
        payload = json.loads(mirror.read_text())
        self.assertIsNone(payload["back"])
        self.assertEqual(payload["shoulder"], choices["shoulder"])
        self.assertEqual(self.cfg["active_cape"], "untouched.png")
        self.assertEqual(self.cfg["active_skin"], "untouched.png")
        self.assertEqual(other.read_bytes(), b"other instance")

    def test_cosmetic_invalid_items_actions_and_sessions(self):
        choice = cosmetics.items("back")[0]["id"]
        for kind, selected in (("shoulder", choice), ("back", "../escape"), ("back", "missing")):
            with self.assertRaises(ValueError):
                self.service.action({"kind": kind, "action": "apply", "id": selected, "game_dir": self.game})
        for operation in ("delete", "import", "model", "lookup"):
            with self.assertRaisesRegex(ValueError, "action"):
                self.service.action({"kind": "back", "action": operation, "id": choice})
        for game in ("wrong", paths.game_dir_for("other-instance"), None):
            with self.assertRaisesRegex(ValueError, "session"):
                self.service.action({"kind": "back", "action": "apply", "id": choice, "game_dir": game})
        self.state["running_version"] = None
        with self.assertRaisesRegex(ValueError, "session"):
            self.service.action({"kind": "back", "action": "apply", "id": choice, "game_dir": self.game})

    def test_cosmetic_failed_save_restores_exact_mirror_and_config(self):
        choice = cosmetics.items("back")[0]["id"]
        mirror = Path(cosmetics.game_config_path(self.game))
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_bytes(b'{"version": 1, "back": null}\n')
        before_cfg, before_bytes = dict(self.cfg), mirror.read_bytes()
        with patch("cubeon.cosmetics.save_config", side_effect=OSError("save failed")):
            with self.assertRaises(OSError):
                self.service.action({"kind": "back", "action": "apply", "id": choice, "game_dir": self.game})
        self.assertEqual(self.cfg, before_cfg)
        self.assertEqual(mirror.read_bytes(), before_bytes)
        mirror.unlink()
        with patch("cubeon.cosmetics.save_config", side_effect=OSError("save failed")):
            with self.assertRaises(OSError):
                self.service.action({"kind": "back", "action": "apply", "id": choice, "game_dir": self.game})
        self.assertFalse(mirror.exists())
        self.assertEqual(self.cfg, before_cfg)
        with patch("cubeon.cosmetics.os.replace", side_effect=PermissionError("read-only game")), patch("cubeon.cosmetics.save_config") as save:
            with self.assertRaises(PermissionError):
                self.service.action({"kind": "back", "action": "apply", "id": choice, "game_dir": self.game})
        save.assert_not_called()
        self.assertEqual(self.cfg, before_cfg)

    def test_actual_save_and_running_instance_validation(self):
        entry = self.upload()
        with self.assertRaisesRegex(ValueError, "session"):
            self.apply(entry, game_dir=paths.game_dir_for("other-instance"))
        self.assertIsNone(self.cfg["active_skin"])
        result = self.apply(entry)
        self.assertEqual(result["active"], entry)
        self.assertEqual(config.load_config()["active_skin"], entry)
        self.assertEqual(self.state["selected_version"], "other-instance")
        self.assertEqual(self.apply("")["applied"]["name"], "Steve")

    def test_skin_ids_and_opt_out_are_enforced(self):
        entry = self.upload()
        for value in ("../../secret.png", "C:\\secret.png", "missing.png"):
            with self.assertRaises(ValueError):
                self.apply(value)
        self.cfg["csl_enabled"] = False
        with self.assertRaisesRegex(ValueError, "CustomSkinLoader"):
            self.apply(entry)
        self.assertIsNone(self.cfg["active_skin"])

    def test_delete_requires_saved_skin_and_preserves_active(self):
        entry = self.upload()
        with self.assertRaisesRegex(ValueError, "default"):
            self.service.action({"action": "delete", "id": ""})
        with self.assertRaisesRegex(ValueError, "library"):
            self.service.action({"action": "delete", "id": "../outside.png"})
        self.apply(entry)
        with self.assertRaisesRegex(ValueError, "wearing"):
            self.service.action({"action": "delete", "id": entry})
        self.assertTrue(Path(skins.get_custom_skin_path(entry)).is_file())
        self.apply("")
        result = self.service.action({"action": "delete", "id": entry})
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["username"], "SkinTester")
        self.assertFalse(Path(skins.get_custom_skin_path(entry)).exists())

    def test_cape_library_apply_hide_and_safe_deletion(self):
        result = self.service.snapshot(kind="cape")
        self.assertEqual([i["id"] for i in result["items"]], ["", "__none__"])
        uploaded = self.service.action({"kind": "cape", "action": "import", "path": str(self.png)})
        entry = uploaded["selected"]
        self.assertFalse(self.cfg.get("active_cape"))
        for value in ("../escape.png", "missing.png"):
            with self.assertRaises(ValueError):
                self.service.action({"kind": "cape", "action": "apply", "id": value, "game_dir": self.game})
        with self.assertRaisesRegex(ValueError, "session"):
            self.service.action({"kind": "cape", "action": "apply", "id": entry, "game_dir": "wrong"})
        self.cfg["csl_enabled"] = False
        with self.assertRaisesRegex(ValueError, "CustomSkinLoader"):
            self.service.action({"kind": "cape", "action": "apply", "id": entry, "game_dir": self.game})
        self.cfg["csl_enabled"] = True
        self.service.action({"kind": "cape", "action": "apply", "id": entry, "game_dir": self.game})
        self.assertEqual(config.load_config()["active_cape"], entry)
        with self.assertRaisesRegex(ValueError, "wearing"):
            self.service.action({"kind": "cape", "action": "delete", "id": entry})
        self.service.action({"kind": "cape", "action": "apply", "id": "__none__", "game_dir": self.game})
        self.assertTrue(self.cfg["hide_cubeon_cape"])
        self.assertIsNone(self.cfg["active_cape"])
        self.service.action({"kind": "cape", "action": "delete", "id": entry})
        self.assertEqual(self.service.snapshot(kind="cape")["total"], 0)
        self.service.action({"kind": "cape", "action": "apply", "id": "", "game_dir": self.game})
        self.assertFalse(self.cfg["hide_cubeon_cape"])
        self.assertIsNone(self.cfg["active_skin"])

    def test_cape_failed_save_restores_private_mirror(self):
        entry = self.service.action({"kind": "cape", "action": "import", "path": str(self.png)})["selected"]
        self.cfg["manage_skin_mod"] = True
        private = Path(paths.CUBEON_HOME) / "private-cape-game"
        mirror = private / "CustomSkinLoader/LocalSkin/capes/SkinTester.png"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_bytes(b"old cape")
        shared = Path(paths.CSL_LOCAL_CAPES_DIR) / "SkinTester.png"
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_bytes(b"old unowned shared cape")
        with patch("cubeon.ingame_capes.paths.game_dir_for", return_value=str(private)), \
                patch("cubeon.capes.save_config", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.service.action({"kind": "cape", "action": "apply", "id": entry, "game_dir": str(private)})
        self.assertIsNone(self.cfg.get("active_cape"))
        self.assertFalse(self.cfg.get("hide_cubeon_cape"))
        self.assertEqual(mirror.read_bytes(), b"old cape")
        self.assertEqual(shared.read_bytes(), b"old unowned shared cape")

    def test_failed_save_restores_config_and_private_mirror(self):
        entry = self.upload()
        self.cfg["manage_skin_mod"] = True
        private = Path(paths.CUBEON_HOME) / "private-game"
        private.mkdir(exist_ok=True)
        mirror = private / "CustomSkinLoader/LocalSkin/skins/SkinTester.png"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_bytes(b"previous skin bytes")
        with patch("cubeon.ingame_skins.paths.game_dir_for", return_value=str(private)), \
                patch("cubeon.skins.save_config", side_effect=OSError("disk failure")), \
                patch("cubeon.skins._publish_skin_async"):
            with self.assertRaises(OSError):
                self.apply(entry, game_dir=str(private))
        self.assertIsNone(self.cfg["active_skin"])
        self.assertEqual(mirror.read_bytes(), b"previous skin bytes")

    def test_paging_and_bad_files_dont_hide_library(self):
        for _ in range(15):
            self.upload()
        first = self.service.snapshot()
        second = self.service.snapshot(first["page_size"])
        self.assertEqual(len(first["items"]), 13)
        self.assertEqual(len(second["items"]), 4)
        self.assertEqual(second["total"], 15)
        Path(skins.get_custom_skin_path(first["items"][1]["id"])).write_bytes(b"invalid")
        self.assertEqual(len(self.service.snapshot()["items"]), 12)

    def test_explicit_mojang_lookup_validates_destination_and_model(self):
        texture = {"textures": {"SKIN": {"url": "http://textures.minecraft.net/texture/" + "a" * 64,
                                         "metadata": {"model": "slim"}}}}
        class Response:
            status_code = 200
            def __init__(self, data): self.data = data
            def iter_content(self, size): yield self.data
            def close(self): pass
        def responses():
            return [Response(json.dumps({"id": "a" * 32}).encode()),
                    Response(json.dumps({"properties": [{"name": "textures", "value":
                        base64.b64encode(json.dumps(texture).encode()).decode()}]}).encode()),
                    Response(self.png.read_bytes())]
        with patch("cubeon.net._do_get", side_effect=responses()) as fetch:
            result = self.service.action({"action": "lookup", "username": "TestPlayer"})
        selected = next(i for i in result["items"] if i["id"] == result["selected"])
        self.assertTrue(selected["slim"])
        self.assertIsNone(self.cfg["active_skin"])
        self.assertEqual(fetch.call_count, 3)
        texture["textures"]["SKIN"]["url"] = "https://untrusted.example/skin.png"
        with patch("cubeon.net._do_get", side_effect=responses()) as fetch:
            with self.assertRaisesRegex(ValueError, "downloadable"):
                self.service.action({"action": "lookup", "username": "TestPlayer"})
        self.assertEqual(fetch.call_count, 2)

    def test_java_real_authenticated_api(self):
        javac, java = find_jdk()
        if not javac:
            self.fail("A JDK is required for the actual skin bridge test.")
        for _ in range(13): self.upload()
        from PIL import Image
        hd = Path(paths.CUBEON_HOME) / "hd-cape.png"
        image = Image.new("RGBA", (128, 64), (180, 50, 30, 255))
        for x in range(128):
            for y in range(64):
                image.putpixel((x, y), ((x * 17 + y) % 256, (y * 29 + x) % 256, (x * y) % 256, 255))
        image.save(hd)
        self.service.action({"kind": "cape", "action": "import", "path": str(hd)})
        local_api.set_skins_provider(self.service.snapshot)
        local_api.set_cape_provider(self.service.capes.live_state)
        local_api.set_skin_handler(self.service.action)
        self.assertTrue(local_api.start())
        server = local_api.start._server
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            conn.request("GET", "/skins")
            response = conn.getresponse()
            self.assertEqual(response.status, 401)
            response.read(); conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            conn.request("GET", "/cape?game_dir=" + self.game)
            response = conn.getresponse()
            self.assertEqual(response.status, 401)
            response.read(); conn.close()
            with tempfile.TemporaryDirectory() as tmp:
                harness = Path(tmp) / "SkinTest.java"
                harness.write_text(HARNESS)
                source = ROOT / "mod/src/main/java/com/cubeon/client"
                files = [source / p for p in ("Bridge.java", "Json.java", "ui/ClientUi.java", "ui/ClientTheme.java", "ui/MenuUi.java", "ui/HudIcon.java",
                    "ui/HudMenu.java", "ui/SkinMenu.java", "hud/HudFeatures.java", "skins/SkinLibrary.java",
                    "skins/SkinPreview.java", "skins/CosmeticPreview.java", "cosmetics/CosmeticCatalog.java",
                    "cosmetics/CosmeticGeometry.java", "skins/LiveSkin.java", "skins/LiveCape.java", "skins/CapeFrames.java", "skins/CapeAnimation.java")]
                subprocess.run([javac, "--release", "17", "-d", tmp, *map(str, files), str(harness)], check=True)
                subprocess.run([java, "-Duser.home=" + str(Path(local_api._TOKEN_FILE).parent.parent),
                                "-cp", tmp + os.pathsep + str(ROOT / "mod/src/main/resources"), "com.cubeon.client.SkinTest"],
                               cwd=self.game, check=True, timeout=30)
                gif = Path(paths.CUBEON_HOME) / "animated-cape.gif"
                frames = [Image.new("RGBA", (64, 32), color) for color in ("red", "green", "blue")]
                frames[0].save(gif, "GIF", save_all=True, append_images=frames[1:], duration=[40, 100, 200], loop=0)
                entry = self.service.action({"kind": "cape", "action": "import", "path": str(gif)})["selected"]
                self.service.action({"kind": "cape", "action": "apply", "id": entry, "game_dir": self.game})
                subprocess.run([java, "-Duser.home=" + str(Path(local_api._TOKEN_FILE).parent.parent),
                                "-cp", tmp, "com.cubeon.client.SkinTest", "gif-poll"],
                               cwd=self.game, check=True, timeout=30)
            self.assertIsNone(self.cfg["active_skin"])
        finally:
            local_api.stop()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
