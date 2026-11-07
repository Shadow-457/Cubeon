"""GIF import, timing, bounded decoding, persistence and local bridge regressions."""
from pathlib import Path
from contextlib import ExitStack
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from PIL import Image
from cubeon import capes, paths
from cubeon.ingame_capes import InGameCapes
from test_mod_bridge import find_jdk


JAVA = r'''
package com.cubeon.client;
import com.cubeon.client.skins.*;
import java.nio.file.*;
import java.util.*;
public final class GifCapeTest {
 static int checks;
 static void check(boolean ok,String why) { checks++; if(!ok) throw new AssertionError(why); }
 static void invalid(Map<String,Object> animation) throws Exception {
  try { CapeFrames.read(animation); throw new AssertionError("Invalid animation accepted"); }
  catch(IllegalArgumentException expected) { checks++; }
 }
 public static void main(String[] args) throws Exception {
  var response=Json.parseObject(Files.readString(Path.of(args[0])));
  var raw=(Map<String,Object>)response.get("applied");
  var animation=(Map<String,Object>)raw.get("animation");
  var frames=CapeFrames.read(animation);
  check(frames.count()==3,"All GIF frames decoded");
  check(!Arrays.equals(frames.png(0),frames.png(1)),"Distinct game frames");
  check(frames.preview(0)[5*64+5]!=frames.preview(1)[5*64+5],"Distinct preview frames");
  long start=1_000_000_000L;
  for(long[] sample:new long[][]{{0,0},{39,0},{40,1},{139,1},{140,2},{339,2},{340,0},{680,0}})
   check(frames.index(start+sample[0]*1_000_000L,start)==sample[1],"Source timing and endless loop: "+sample[0]);
  var finite=new HashMap<String,Object>(animation);finite.put("loop",null);
  var once=CapeFrames.read(finite);
  check(once.index(start+340_000_000L,start)==2,"Absent loop plays once and holds last frame");
  finite.put("loop",1);
  var twice=CapeFrames.read(finite);
  check(twice.index(start+340_000_000L,start)==0,"Finite loop repeat starts again");
  check(twice.index(start+680_000_000L,start)==2,"Finite loop stops at its final frame");
  var bad=new HashMap<String,Object>(animation);bad.put("durations",List.of(0,100,200));invalid(bad);
  bad=new HashMap<>(animation);bad.put("count",501);invalid(bad);
  bad=new HashMap<>(animation);bad.put("width",128);invalid(bad);
  bad=new HashMap<>(animation);bad.put("loop",-1);invalid(bad);
  bad=new HashMap<>(animation);bad.put("count",3.5);invalid(bad);
  CapeAnimation.accept(response);
  var first=CapeAnimation.get();
  check(first!=null && first.frames()!=null,"Startup bridge applies animation without opening library");
  CapeAnimation.accept(response);
  check(CapeAnimation.get()==first,"Unchanged polls do not reload or restart animation");
  byte[] png=CapeFrames.localPng((String)raw.get("texture_path"));
  CapeAnimation.apply(png,false,frames,(String)raw.get("id"));
  check(CapeAnimation.get()==first,"Confirming same cape does not restart it");
  var missing=new HashMap<String,Object>(raw);missing.put("texture_path",args[0]+".missing");
  var damaged=new HashMap<String,Object>(response);damaged.put("applied",missing);damaged.put("revision","damaged");
  CapeAnimation.accept(damaged);
  check(CapeAnimation.get()==first,"Damaged local files preserve last complete selection");
  damaged.put("applied",raw);CapeAnimation.accept(damaged);
  check(CapeAnimation.get()==first,"Repaired files retry the same revision safely");
  check(CapeFrames.localGif((String)raw.get("gif_path"))[0]=='G',"Animated export keeps GIF bytes");
  CapeAnimation.apply(png,false,null,"still");
  check(CapeAnimation.get().frames()==null,"Switch to still removes animation");
  CapeAnimation.apply(png,true,null,"__none__");
  check(CapeAnimation.get().hidden(),"Hide replaces animated selection");
  CapeAnimation.accept(Map.of("ok",true,"enabled",false,"revision","disabled"));
  check(CapeAnimation.get()==null,"Management opt-out clears local override");
  System.out.println("GIF cape Java timing, decoding and bridge: "+checks+" checks passed.");
 }
}
'''


class GifCapes(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cubeon-gif-test-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.library = self.folder / "capes"
        self.library.mkdir()
        self.game = self.folder / "game"
        self.game.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(capes, "CAPES_DIR", str(self.library)))
        self.stack.enter_context(patch.object(capes, "CAPES_META_PATH", str(self.library / "capes.json")))
        self.stack.enter_context(patch.object(paths, "CAPES_DIR", str(self.library)))
        self.stack.enter_context(patch.object(paths, "game_dir_for", return_value=str(self.game)))
        self.cfg = {"username": "GifTester", "active_cape": None, "manage_skin_mod": True}
        self.state = {"running_version": "gif-fixture"}
        self.bridge = InGameCapes(self.cfg, self.state, threading.RLock())

    def gif(self, size=(20, 32), loop=0, disposal=2):
        source = self.folder / "input.gif"
        frames = [Image.new("RGBA", size, color) for color in ("red", "green", "blue")]
        frames[0].save(source, "GIF", save_all=True, append_images=frames[1:],
                       duration=[40, 100, 200], disposal=disposal,
                       **({"loop": loop} if loop is not None else {}))
        return source

    def imported(self, **kwargs):
        return capes.add_custom_cape(str(self.gif(**kwargs)), "Rainbow")

    def test_import_preserves_frames_timing_fitting_and_transparency(self):
        entry = self.imported()
        self.assertTrue(entry["animated"])
        path = capes.get_custom_cape_path(entry["filename"])
        manifest = capes.animation_info(entry["filename"])
        self.assertEqual((manifest["count"], manifest["durations"], manifest["loop"]), (3, [40, 100, 200], 0))
        with Image.open(path + ".frames.png") as atlas:
            self.assertEqual(atlas.size, (64, 96))
            self.assertEqual([atlas.getpixel((5, 5 + 32*i))[:3] for i in range(3)],
                             [(255, 0, 0), (0, 128, 0), (0, 0, 255)])
            self.assertEqual(atlas.getpixel((40, 5))[3], 0)
        with Image.open(path + ".gif") as exported:
            self.assertEqual(exported.n_frames, 3)
            self.assertEqual(exported.info["loop"], 0)
            exported.seek(1)
            self.assertEqual(exported.info["duration"], 100)
            self.assertEqual(exported.convert("RGBA").getpixel((40, 5))[3], 0)
        preview = self.folder / "preview.gif"
        capes.render_cape_preview(entry["filename"], str(preview))
        with Image.open(preview) as image:
            self.assertEqual((image.n_frames, image.size), (3, (100, 160)))

    def test_composited_partial_frames_respect_disposal(self):
        for disposal in (1, 2, 3):
            frames = []
            for color, box in (("red", (1, 1, 11, 17)), ("green", (3, 3, 7, 7)), ("blue", (7, 7, 10, 10))):
                frame = Image.new("RGBA", (64, 32))
                frame.paste(color, box)
                frames.append(frame)
            source = self.folder / "partial.gif"
            frames[0].save(source, "GIF", save_all=True, append_images=frames[1:],
                           duration=[40, 100, 200], disposal=disposal, transparency=0)
            with Image.open(source) as original:
                expected = []
                for index in range(original.n_frames):
                    original.seek(index)
                    expected.append(original.convert("RGBA").tobytes())
            entry = capes.add_custom_cape(str(source), "Partial")
            with Image.open(capes.get_custom_cape_path(entry["filename"]) + ".frames.png") as atlas:
                for index, pixels in enumerate(expected):
                    self.assertEqual(atlas.crop((0, index*32, 64, (index+1)*32)).tobytes(), pixels)

    def test_hd_animation_bounded_and_static_hd_preserved(self):
        entry = self.imported(size=(256, 128))
        self.assertEqual(capes.animation_info(entry["filename"])["width"], 128)
        source = self.folder / "hd.png"
        Image.new("RGBA", (1024, 512), "red").save(source)
        entry = capes.add_custom_cape(str(source), "Still HD")
        self.assertNotIn("animated", entry)
        with Image.open(capes.get_custom_cape_path(entry["filename"])) as image:
            self.assertEqual(image.size, (1024, 512))

    def test_limits_and_invalid_inputs_leave_no_partial_entries(self):
        source = self.gif()
        for key, limit in (("MAX_GIF_FRAMES", 2), ("MAX_DECODED_PIXELS", 1000), ("MAX_SOURCE_PIXELS", 500)):
            with patch.object(capes, key, limit), self.assertRaises(ValueError):
                capes.add_custom_cape(str(source), "Too big")
            self.assertEqual(list(self.library.iterdir()), [])
        source.write_bytes(b"GIF89a invalid")
        self.assertFalse(capes.validate_cape_file(str(source))[0])
        with source.open("wb") as stream:
            stream.truncate(capes.MAX_SOURCE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "8 MB"):
            capes.add_custom_cape(str(source), "Too big")

    def test_import_write_failure_rolls_back_all_sidecars(self):
        source = self.gif()
        with patch.object(capes, "_save_capes_meta", side_effect=OSError("disk full")), self.assertRaises(OSError):
            capes.add_custom_cape(str(source), "Failure")
        self.assertEqual(list(self.library.iterdir()), [])

    def test_loop_counts_and_single_frame_gif(self):
        for loop in (None, 1, 65535):
            entry = self.imported(loop=loop)
            self.assertEqual(capes.animation_info(entry["filename"])["loop"], loop)
            with Image.open(capes.get_custom_cape_path(entry["filename"]) + ".gif") as image:
                self.assertEqual(image.info.get("loop"), loop)
        source = self.folder / "single.gif"
        Image.new("RGB", (5, 9), "red").save(source)
        entry = capes.add_custom_cape(str(source), "Single")
        self.assertNotIn("animated", entry)
        self.assertIsNone(capes.animation_info(entry["filename"]))

    def test_startup_poll_switch_hide_and_wrong_session(self):
        entry = self.imported()
        capes.set_active_cape(self.cfg, entry["filename"])
        first = self.bridge.live_state(str(self.game))
        self.assertTrue(first["enabled"])
        self.assertEqual(first["applied"]["animation"]["count"], 3)
        self.assertEqual(self.bridge.live_state(str(self.game))["revision"], first["revision"])
        self.assertFalse(self.bridge.live_state("other game")["enabled"])
        self.cfg["csl_enabled"] = False
        self.assertFalse(self.bridge.live_state(str(self.game))["enabled"])
        self.cfg["csl_enabled"] = True
        capes.set_hide_cubeon_cape(self.cfg, True)
        hidden = self.bridge.live_state(str(self.game))
        self.assertTrue(hidden["applied"]["hidden"])
        self.assertNotIn("animation", hidden["applied"])
        capes.set_active_cape(self.cfg, None)
        still = self.bridge.live_state(str(self.game))
        self.assertNotIn("animation", still["applied"])
        self.assertNotEqual(still["revision"], first["revision"])
        self.cfg["manage_skin_mod"] = False
        self.assertFalse(self.bridge.live_state(str(self.game))["enabled"])

    def test_damaged_sidecars_do_not_break_library_or_save_selection(self):
        entry = self.imported()
        capes.set_active_cape(self.cfg, entry["filename"])
        path = Path(capes.get_custom_cape_path(entry["filename"]) + ".frames.json")
        original = path.read_bytes()
        for damaged in (b"invalid JSON", b'{}', b'{"count":501}'):
            path.write_bytes(damaged)
            self.assertTrue(self.bridge.snapshot()["ok"])
            self.assertNotIn("animation", self.bridge.live_state(str(self.game))["applied"])
            with self.assertRaises(ValueError):
                capes.set_active_cape(self.cfg, entry["filename"])
        path.write_bytes(original)
        path.unlink()
        with self.assertRaises(ValueError):
            capes.set_active_cape(self.cfg, entry["filename"])
        path.write_bytes(original)
        atlas = Path(capes.get_custom_cape_path(entry["filename"]) + ".frames.png")
        atlas.write_bytes(b"broken PNG")
        with self.assertRaises(ValueError):
            capes.set_active_cape(self.cfg, entry["filename"])
        self.assertTrue(self.bridge.snapshot()["ok"])
        Path(capes.get_custom_cape_path(entry["filename"])).unlink()
        self.assertFalse(self.bridge.live_state(str(self.game))["enabled"])

    def test_failed_save_restores_prior_cape(self):
        entry = self.imported()
        original = dict(self.cfg)
        with patch.object(capes, "save_config", side_effect=OSError("disk full")), self.assertRaises(OSError):
            capes.set_active_cape(self.cfg, entry["filename"])
        self.assertEqual(self.cfg, original)

    def test_delete_cleans_animation_and_rejects_traversal(self):
        entry = self.imported()
        for filename in ("../outside.png", "..\\outside.png", ".hidden.png", "bad\x00.png"):
            with self.assertRaises(ValueError):
                capes.delete_custom_cape(filename)
        capes.delete_custom_cape(entry["filename"])
        self.assertEqual(capes.list_custom_capes(), [])
        self.assertEqual([p.name for p in self.library.iterdir()], ["capes.json"])

    def test_java_frame_timing_and_background_state(self):
        javac, java = find_jdk()
        self.assertTrue(javac, "A JDK is required for GIF cape verification")
        entry = self.imported()
        capes.set_active_cape(self.cfg, entry["filename"])
        payload = self.folder / "payload.json"
        payload.write_text(json.dumps(self.bridge.live_state(str(self.game))))
        harness = self.folder / "GifCapeTest.java"
        harness.write_text(JAVA)
        source = ROOT / "mod/src/main/java/com/cubeon/client"
        classes = self.folder / "classes"
        classes.mkdir()
        subprocess.run([javac, "--release", "17", "-d", str(classes), str(source / "Json.java"),
                        str(source / "skins/CapeFrames.java"), str(source / "skins/CapeAnimation.java"),
                        str(harness)], check=True, timeout=30)
        subprocess.run([java, "-cp", str(classes), "com.cubeon.client.GifCapeTest", str(payload)], check=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
