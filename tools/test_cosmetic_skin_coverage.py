"""Wearables trim covered texels while preserving exposed skin geometry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
import _sandbox_home
_sandbox_home.isolate()
from PIL import Image
from cubeon import appearance, cosmetics
from test_cosmetics import _java_tool


def box(origin, size, motion='none', **extra):
    return dict(origin=origin, size=size, motion=motion, pivot=[0, 0, 0], uv=[0, 0], px=1, **extra)


def fixtures():
    examples = [
        dict(id='shell', slot='head', boxes=[box([-4.25, -8.25, -4.25], [8.5, 8.5, 8.5])]),
        dict(id='horns', slot='head', boxes=[box([-3, -10, -1], [1, 2, 1], mirror=True)]),
        dict(id='halo', slot='head', boxes=[box([-4, -12, -4], [8, .5, 8])]),
        dict(id='open_cowl', slot='head', boxes=[
            box([-4.25, -8.25, -4.25], [8.5, 6.25, .5]),
            box([-4.25, -8.25, 3.75], [8.5, 6.25, .5]),
            box([-4.25, -8.25, -4.25], [.5, 6.25, 8.5]),
            box([3.75, -8.25, -4.25], [.5, 6.25, 8.5]),
            box([-4.25, -8.25, -4.25], [8.5, .5, 8.5])]),
        dict(id='right_boot', slot='feet', boxes=[box([-4.25, 20, -2.25], [4.5, 4.25, 4.5], 'right_leg')]),
        dict(id='left_boot', slot='feet', boxes=[box([-.25, 20, -2.25], [4.5, 4.25, 4.5], 'left_leg')]),
        dict(id='wrist', slot='hand', boxes=[box([-8.25, 9, -2.25], [4.5, 3.25, 4.5])]),
        dict(id='belt', slot='waist', boxes=[box([-4.25, 9, -2.25], [8.5, 2, 4.5])]),
        dict(id='moving', slot='head', boxes=[box([-4.25, -8.25, -4.25], [8.5, 8.5, 8.5], 'hover_head')]),
        dict(id='invisible', slot='head', boxes=[box([-4.25, -8.25, -4.25], [8.5, 8.5, 8.5], faces=[])]),
        dict(id='inside', slot='head', boxes=[box([-3, -7, -3], [6, 6, 6])]),
    ]
    return [{**item, 'name': item['id'], 'texture': item['id']+'.png', 'tex_w': 128, 'tex_h': 128} for item in examples]


class Coverage(unittest.TestCase):
    def test_fitted_headwear_and_floating_art_have_different_coverage(self):
        fitted = dict(slot='head', boxes=[dict(origin=[-4.25,-8.25,-4.25],size=[8.5,8.5,8.5])])
        floating = dict(slot='head', boxes=[dict(origin=[-4,-12,-4],size=[8,.5,8])])
        self.assertEqual(cosmetics.covered_skin_layers(fitted), {'head'})
        self.assertEqual(cosmetics.covered_skin_layers(floating), set())
        self.assertEqual(cosmetics.covered_skin_layers(dict(slot='back')), set())
        self.assertEqual(cosmetics.covered_skin_layers(dict(slot='feet')), set())
        sheet=Image.new('RGBA',(64,64),'white');original=sheet.tobytes()
        full=appearance.CharacterModel(sheet)
        covered=appearance.CharacterModel(sheet,hidden_layers={'head'})
        self.assertLess(len(covered.faces),len(full.faces))
        self.assertEqual(sheet.tobytes(),original)
        self.assertTrue(all(face in full.faces for face in covered.faces))
        aura=cosmetics.get('aura_butterfly')
        self.assertLessEqual(len(aura['boxes']),48)
        panels=[box for box in aura['boxes'] if box.get('faces')==['front','back']]
        self.assertEqual(len(panels),16)
        sheet=cosmetics.texture(aura)
        for box in panels:
            x,y,w,h=cosmetics.face_rects(box)['front']
            self.assertEqual(sheet.crop((x,y,x+w,y+h)).getchannel('A').getextrema(),(0,255))

    def test_horns_preserve_the_hairstyle(self):
        horns = fixtures()[1]
        pixels = cosmetics.covered_skin_pixels(horns)
        self.assertTrue(pixels)
        self.assertLessEqual(len(pixels), 8)
        self.assertEqual(cosmetics.covered_skin_layers(horns), set())
        self.assertTrue(all(0 <= texel//64 < 8 for texel in pixels), 'Only top attachment points are trimmed')
        self.assertEqual(cosmetics.covered_skin_layers(cosmetics.get('head_horns')), set())

    def test_open_mask_preserves_exposed_chin_and_other_body_parts(self):
        cowl = fixtures()[3]
        pixels = cosmetics.covered_skin_pixels(cowl)
        self.assertTrue(all(y*64+x in pixels for y in range(8, 14) for x in range(40, 48)))
        self.assertTrue(all(y*64+x not in pixels for y in range(14, 16) for x in range(40, 48)))
        self.assertTrue(all(texel//64 < 16 for texel in pixels))
        self.assertEqual(cosmetics.covered_skin_layers(cowl), set(), 'An open mask must not disable the whole hat')

    def test_shoes_keep_upper_trousers_and_the_opposite_leg(self):
        for index, atlas_y, other_y in ((4, 32, 48), (5, 48, 32)):
            pixels = cosmetics.covered_skin_pixels(fixtures()[index])
            self.assertTrue(all(y*64+x in pixels for y in range(atlas_y+12, atlas_y+16) for x in range(4, 8)))
            self.assertTrue(all(y*64+x not in pixels for y in range(atlas_y+4, atlas_y+12) for x in range(4, 8)))
            self.assertTrue(all(y*64+x not in pixels for y in range(other_y, other_y+16) for x in range(16)))
            self.assertEqual(cosmetics.covered_skin_layers(fixtures()[index]), set())

    def test_cuffs_and_belts_keep_uncovered_skin_for_both_arm_models(self):
        for slim in (False, True):
            wrist = cosmetics.covered_skin_pixels(fixtures()[6], slim=slim)
            belt = cosmetics.covered_skin_pixels(fixtures()[7], slim=slim)
            self.assertTrue(wrist and belt)
            self.assertEqual(cosmetics.covered_skin_layers(fixtures()[6], slim=slim), set())
            self.assertTrue(all(32 <= p//64 < 48 and 40 <= p%64 < 56 for p in wrist))
            self.assertTrue(all(32 <= p//64 < 48 and 16 <= p%64 < 40 for p in belt))
            self.assertTrue(all(y*64+x not in wrist for y in range(36, 44) for x in range(44, 47)))

    def test_floating_animated_invisible_and_internal_boxes_do_not_hide_skin(self):
        for index in (2, 8, 9, 10):
            self.assertFalse(cosmetics.covered_skin_pixels(fixtures()[index]))
        for slot in ('back', 'shoulder', 'aura', 'trail'):
            item = {**fixtures()[0], 'slot': slot}
            self.assertFalse(cosmetics.covered_skin_pixels(item))

    def test_display_copy_preserves_source_base_colors_and_hd_legacy_sheets(self):
        worn = [fixtures()[1], fixtures()[4], fixtures()[6]]
        pixels = set().union(*(cosmetics.covered_skin_pixels(item) for item in worn))
        for size in ((64, 64), (128, 128), (64, 32), (128, 64)):
            source = Image.new('RGBA', size, (20, 90, 160, 213))
            original = source.tobytes()
            masked = cosmetics.apply_skin_coverage(source, worn)
            self.assertEqual(source.tobytes(), original)
            scale = size[0]//64
            for y in range(size[1]):
                for x in range(size[0]):
                    covered = (y//scale)*64+x//scale in pixels
                    self.assertEqual(masked.getpixel((x, y)), (20, 90, 160, 0 if covered else 213))
            self.assertEqual(cosmetics.apply_skin_coverage(source, []).tobytes(), original)

    def test_launcher_preview_keeps_raised_geometry_after_equipping_and_unequipping(self):
        source = Image.new('RGBA', (64, 64), 'white')
        original = source.tobytes()
        cfg = {'hide_cubeon_cape': True, 'active_head_item': 'horns'}
        with patch.object(appearance.skins, 'compose_skin', return_value=source), \
                patch.object(cosmetics, 'get', side_effect=lambda item, *_: fixtures()[1] if item else None), \
                patch.object(cosmetics, 'preview_faces', return_value=[]):
            dressed = appearance.CharacterModel.from_config(cfg)
            plain = appearance.CharacterModel.from_config({'hide_cubeon_cape': True})
        self.assertEqual(source.tobytes(), original)
        self.assertEqual([face for face in dressed.faces if max(v[1] for v in face.vertices) < 24],
                         [face for face in plain.faces if max(v[1] for v in face.vertices) < 24])
        self.assertTrue(any(min(v[1] for v in face.vertices) > 24 and any(abs(v[2]) > 4 for v in face.vertices)
                            for face in dressed.faces), 'The raised hairstyle survives small headwear')
        self.assertEqual(plain.faces, appearance.CharacterModel(source).faces)

    def test_java_coverage_and_butterfly_rig(self):
        java,javac=_java_tool('java'),_java_tool('javac')
        if not java or not javac:self.skipTest('JDK 17+ required')
        base=ROOT/'mod/src/main/java/com/cubeon/client'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            (path/'CoverageProbe.java').write_text('''
import com.cubeon.client.cosmetics.*;
import java.util.*;
import java.nio.file.*;
public class CoverageProbe {
 public static void main(String[] args) throws Exception {
  var fit=CosmeticCatalog.Catalog.parse("{\\"items\\":[{\\"id\\":\\"fit\\",\\"slot\\":\\"head\\",\\"texture\\":\\"fit.png\\",\\"tex_w\\":128,\\"tex_h\\":128,\\"boxes\\":[{\\"origin\\":[-4.25,-8.25,-4.25],\\"size\\":[8.5,8.5,8.5],\\"uv\\":[0,0],\\"px\\":1}]}]}").get("fit");
  if(CosmeticSkinCoverage.mask(fit)!=1)throw new AssertionError("Fitted head coverage");
  var aura=CosmeticCatalog.get().get("aura_butterfly");
  if(aura==null||aura.emissiveTexture==null||CosmeticSkinCoverage.mask(aura)!=0)throw new AssertionError("Aura must retain skin and have glow");
  if(aura.boxes.stream().mapToDouble(b->b.y).max().getAsDouble()<22||aura.boxes.stream().mapToDouble(b->b.y).min().getAsDouble()>-7)throw new AssertionError("Full body spread");
  var motion=CosmeticAnimation.sample(3,0,false);
  var posed=new CosmeticAnimation.PosedQuad();var quads=CosmeticGeometry.quads(aura,0);
  boolean moves=false;
  for(var quad:quads){posed.set(quad,motion);if(Math.abs(posed.x[0]-quad.x[0])>.01)moves=true;posed.set(quad,null);if(posed.x[0]!=quad.x[0])throw new AssertionError("Motion off");}
  if(!moves)throw new AssertionError("Butterflies must animate");
  if(CosmeticSkinCoverage.hidden(new CosmeticSelection.Items(null,null),"HAT"))throw new AssertionError("Unequipped layers");
  if(CosmeticSkinCoverage.hidden(null,"CAPE"))throw new AssertionError("Capes preserved");
  var samples=CosmeticCatalog.Catalog.parse(Files.readString(Path.of(args[0])));
  for(var item:samples.items()) for(boolean slim:new boolean[]{false,true}) {
   var pixels=CosmeticSkinCoverage.pixels(item,slim);var covered=new ArrayList<Integer>();
   for(int y=0;y<64;y++)for(int x=0;x<64;x++)if(pixels.covered(x,y,64,64))covered.add(y*64+x);
   System.out.println(item.id+"|"+slim+"|"+covered);
   if(pixels!=CosmeticSkinCoverage.pixels(item,slim))throw new AssertionError("Coverage cache identity");
   for(int y=0;y<128;y++)for(int x=0;x<128;x++)
    if(pixels.covered(x,y,128,128)!=pixels.covered(x/2,y/2,64,64))throw new AssertionError("HD atlas mapping");
  }
  System.out.println("Fitted head coverage, full-body luminous butterflies, animation/off and unequip verified");
 }
}''')
            sources=[base/'Json.java',*(base/'cosmetics'/f'{name}.java' for name in
                ('CosmeticCatalog','CosmeticSelection','CosmeticSkinCoverage','CosmeticAnimation','CosmeticGeometry','WingAction'))]
            subprocess.run([javac,'-d',temp,*map(str,sources),str(path/'CoverageProbe.java')],check=True,timeout=60)
            sample_file = path/'samples.json'
            sample_file.write_text(json.dumps({'items': fixtures()}))
            result = subprocess.run([java,'-cp',temp+os.pathsep+str(ROOT/'mod/src/main/resources'),'CoverageProbe',str(sample_file)],
                                    check=True,timeout=30,capture_output=True,text=True)
            samples = {item['id']: item for item in fixtures()}
            checked = 0
            for line in result.stdout.splitlines():
                if line.count('|') != 2:
                    continue
                item, slim, values = line.split('|')
                self.assertEqual(frozenset(json.loads(values)), cosmetics.covered_skin_pixels(samples[item], slim=slim=='true'))
                checked += 1
            self.assertEqual(checked, len(samples)*2, result.stdout)

if __name__=='__main__':unittest.main()
