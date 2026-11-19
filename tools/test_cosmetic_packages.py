"""Owner batch publishing and actual downloaded model/game resource contracts."""
import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import cosmetic_packages as packages, cosmetics, cosmetics_store

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publisher", ROOT / "worker/manage-cosmetics.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class Packages(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "cosmetics"
        publisher.setup(self.folder)
        self.storage = self.root / "downloads"
        patcher = patch.object(packages, "DIRECTORY", self.storage)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(cosmetics.invalidate_cache)
        cosmetics.invalidate_cache()

    def model(self, kind="pet", item_id="my-pet"):
        source = self.folder / "examples" / (kind + ".json")
        value = json.loads(source.read_text())
        value["id"] = item_id
        source.write_text(json.dumps(value))
        values = publisher.prepare_model(source, kind)
        data = base64.b64decode(values[4])
        metadata = dict(id=values[0], name=values[1], description=values[2], mime_type=values[3],
                        byte_size=values[5], sha256=values[6], preview_png=values[7], kind=kind)
        return data, metadata

    def test_batch_validates_all_and_detects_id_collisions(self):
        self.assertEqual(len(publisher.prepare_folder(self.folder)), 1)
        shutil.copyfile(self.folder / "examples/pet.json", self.folder / "pets/new-pet.json")
        shutil.copyfile(self.folder / "examples/wing.json", self.folder / "wings/new-wing.json")
        values = publisher.prepare_folder(self.folder)
        self.assertEqual(len(values), 3)
        self.assertEqual([v[8] for v in values[1:]], ["pet", "wing"])
        duplicate = self.folder / "wings/duplicate.json"
        duplicate.write_text((self.folder / "wings/new-wing.json").read_text())
        with self.assertRaisesRegex(ValueError, "same id"):
            publisher.prepare_folder(self.folder)

    def test_dry_run_never_reads_credentials_or_contacts_neon(self):
        with patch.object(sys, "argv", ["publisher", "sync", "--folder", str(self.folder), "--dry-run"]), \
                patch.object(publisher, "connection_from_env", side_effect=AssertionError("credentials read")), \
                patch.object(publisher, "query", side_effect=AssertionError("network access")):
            publisher.main()
        (self.folder / "capes/broken.gif").write_bytes(b"invalid")
        with patch.object(sys, "argv", ["publisher", "sync", "--folder", str(self.folder)]), \
                patch.object(publisher, "query", side_effect=AssertionError("partial upload")), self.assertRaises(SystemExit):
            publisher.main()

    def test_unchanged_upsert_keeps_timestamp_and_published_entry(self):
        values = publisher.prepare_folder(self.folder)[0]
        with patch.object(publisher, "query", return_value=[]) as query:
            self.assertEqual(publisher.publish("secret", values), [])
        sql, params = query.call_args.args[1:]
        self.assertIn("IS DISTINCT FROM", sql)
        self.assertIn("cubeon_cosmetics.published", sql)
        self.assertEqual(params[-1], "cape")

    def test_actual_pet_and_wing_download_preview_and_game_sync(self):
        cfg = {"last_version": "1.21.1"}
        game = self.root / "game"
        game.mkdir()
        (game / "options.txt").write_text('resourcePacks:["vanilla","file/player-pack.zip"]\nfov:0.7\n')
        for kind, slot in (("pet", "shoulder"), ("wing", "back")):
            payload, metadata = self.model(kind, "my-" + kind)
            with patch.object(cosmetics_store, "_bytes", return_value=payload) as fetch:
                saved = cosmetics_store.download(metadata)
                self.assertEqual(cosmetics_store.download(metadata), saved)
                self.assertEqual(fetch.call_count, 1)
            self.assertEqual(saved["slot"], slot)
            self.assertIsNotNone(cosmetics.get(saved["id"]))
            thumbnail = cosmetics.render_thumbnail(saved)
            self.assertIsNotNone(thumbnail.getbbox())
            cfg["active_" + slot + "_item"] = saved["id"]
        cosmetics.sync_to_game(cfg, str(game), strict=True)
        selection = json.loads((game / "config/cubeon-cosmetics.json").read_text())
        models = json.loads((game / "config/cubeon-store.json").read_text())
        self.assertEqual({item["id"] for item in models["items"]}, {selection["back"], selection["shoulder"]})
        for item in models["items"]:
            self.assertTrue((game / "resourcepacks/cubeon-store/assets/cubeon-client/textures/cosmetics" / item["texture"]).is_file())
        options = (game / "options.txt").read_text()
        self.assertIn('file/player-pack.zip', options)
        self.assertIn('fov:0.7', options)
        self.assertEqual(options.count('file/cubeon-store'), 1)
        cosmetics.sync_to_game(cfg, str(game), strict=True)
        self.assertEqual((game / "options.txt").read_text(), options)

    def test_revisions_preserve_equipped_models_and_bundled_assets(self):
        payload, metadata = self.model()
        original = packages.install(payload, metadata)
        package = packages.read(payload)
        package["item"]["blurb"] = "Updated"
        revised = packages.encode(package)
        second = packages.install(revised, {**metadata, "sha256": hashlib.sha256(revised).hexdigest()})
        self.assertNotEqual(original["id"], second["id"])
        self.assertIsNotNone(cosmetics.get(original["id"]))
        self.assertIsNotNone(cosmetics.get("shoulder_ember_fox"))
        self.assertEqual(len(packages.installed_items()), 2)

    def test_headwear_and_footwear_download_and_sync_independently(self):
        from gen_store_collection import headwear, footwear
        from gen_cosmetics import render_item
        cfg = {"last_version": "1.21.11"}
        for kind, item in (("head", headwear()[0]), ("feet", footwear()[0])):
            image, boxes = render_item(item)
            directory = self.folder / kind
            image.save(directory / 'model.png')
            model = dict(slot=kind, texture='model.png', tex_w=image.width, tex_h=image.height,
                         boxes=boxes, wing_flare=False)
            if kind == 'head':
                image.save(directory / 'glow.png')
                model['emissive_texture'] = 'glow.png'
            path = directory / 'original.json'
            path.write_text(json.dumps(dict(id='my-' + kind, name=item['name'], model=model)))
            values = publisher.prepare_model(path, kind)
            metadata = dict(zip(('id','name','description','mime_type','file','byte_size','sha256','preview_png','kind'), values))
            payload = base64.b64decode(metadata.pop('file'))
            with patch.object(cosmetics_store, '_bytes', return_value=payload):
                saved = cosmetics_store.download(metadata)
            cfg['active_' + kind + '_item'] = saved['id']
            if kind == 'feet':
                self.assertEqual({b['motion'] for b in saved['boxes']}, {'left_leg','right_leg'})
                bad = packages.read(payload)
                bad['item']['boxes'][0]['motion'] = 'none'
                with self.assertRaises(ValueError):
                    packages.encode(bad)
        game = self.root / 'game'
        cosmetics.sync_to_game(cfg, str(game), strict=True)
        external = json.loads((game / 'config/cubeon-store.json').read_text())
        self.assertEqual({model['slot'] for model in external['items']}, {'head','feet'})
        head = next(model for model in external['items'] if model['slot'] == 'head')
        self.assertTrue(head['emissive_texture'].endswith('_glow.png'))
        self.assertTrue((game / 'resourcepacks/cubeon-store/assets/cubeon-client/textures/cosmetics' / head['emissive_texture']).is_file())
        selection = json.loads((game / 'config/cubeon-cosmetics.json').read_text())
        self.assertEqual(selection['head'], cfg['active_head_item'])
        self.assertEqual(selection['feet'], cfg['active_feet_item'])

    def test_bad_models_and_textures_never_install(self):
        payload, metadata = self.model()
        source = packages.read(payload)
        for mutation in (lambda p: p["item"].update(slot="back"),
                         lambda p: p["item"]["boxes"][0].update(origin=[float('nan'), 0, 0]),
                         lambda p: p["item"].update(boxes=p["item"]["boxes"] * 3000),
                         lambda p: p["textures"].update({"../escape.png": "AAAA"}),
                         lambda p: p["item"]["boxes"][0].update(uv=[2048, 2048])):
            changed = copy.deepcopy(source)
            mutation(changed)
            with self.assertRaises(ValueError):
                packages.read(json.dumps(changed).encode())
        self.assertFalse(self.storage.exists())

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK needed")
    def test_real_java_catalog_merges_only_safe_store_entries(self):
        payload, metadata = self.model()
        saved = packages.install(payload, metadata)
        cfg = {"last_version": "1.20.1", "active_shoulder_item": saved["id"]}
        game = self.root / "game"
        packages.sync_game(cfg, game)
        external = game / "config/cubeon-store.json"
        body = json.loads(external.read_text())
        unsafe = copy.deepcopy(body["items"][0])
        unsafe.update(id="shoulder_ember_fox", texture="../../private.png")
        body["items"].append(unsafe)
        external.write_text(json.dumps(body))
        java = self.root / "Check.java"
        java.write_text('''import com.cubeon.client.cosmetics.CosmeticCatalog;
import java.nio.file.Path;
public class Check { public static void main(String[] args) {
  CosmeticCatalog.bindExternal(Path.of(args[0]));
  var catalog = CosmeticCatalog.get();
  if(catalog.get(args[1]) == null) throw new AssertionError("Downloaded model missing");
  if(catalog.get("shoulder_ember_fox").texture.contains("..")) throw new AssertionError("Bundled replacement");
  CosmeticCatalog.bindExternal(Path.of(args[0]+"-missing"));
  if(CosmeticCatalog.get().get("shoulder_ember_fox") == null) throw new AssertionError("Broken external data removed bundled items");
}}''')
        sources = [ROOT / "mod/src/main/java/com/cubeon/client/Json.java",
                   ROOT / "mod/src/main/java/com/cubeon/client/cosmetics/CosmeticCatalog.java", java]
        result = subprocess.run(["javac", "--release", "17", "-d", str(self.root), *map(str, sources)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        classpath = os.pathsep.join([str(self.root), str(ROOT / "mod/src/main/resources")])
        result = subprocess.run(["java", "-cp", classpath, "Check", str(external), saved["id"]], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
