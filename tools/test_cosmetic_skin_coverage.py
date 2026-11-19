"""Fitted wearables suppress outer layers without changing skins or other slots."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
import _sandbox_home
_sandbox_home.isolate()
from PIL import Image
from cubeon import appearance, cosmetics
from test_cosmetics import _java_tool

class Coverage(unittest.TestCase):
    def test_fitted_headwear_and_floating_art_have_different_coverage(self):
        fitted = dict(slot='head', boxes=[dict(origin=[-4.25,-8.25,-4.25],size=[8.5,8.5,8.5])])
        floating = dict(slot='head', boxes=[dict(origin=[-4,-12,-4],size=[8,.5,8])])
        self.assertEqual(cosmetics.covered_skin_layers(fitted), {'head'})
        self.assertEqual(cosmetics.covered_skin_layers(floating), set())
        self.assertEqual(cosmetics.covered_skin_layers(dict(slot='back')), set())
        self.assertEqual(cosmetics.covered_skin_layers(dict(slot='feet')), {'left_leg','right_leg'})
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

    def test_java_coverage_and_butterfly_rig(self):
        java,javac=_java_tool('java'),_java_tool('javac')
        if not java or not javac:self.skipTest('JDK 17+ required')
        base=ROOT/'mod/src/main/java/com/cubeon/client'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            (path/'CoverageProbe.java').write_text('''
import com.cubeon.client.cosmetics.*;
import java.util.*;
public class CoverageProbe {
 public static void main(String[] args) {
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
  System.out.println("Fitted head coverage, full-body luminous butterflies, animation/off and unequip verified");
 }
}''')
            sources=[base/'Json.java',*(base/'cosmetics'/f'{name}.java' for name in
                ('CosmeticCatalog','CosmeticSelection','CosmeticSkinCoverage','CosmeticAnimation','CosmeticGeometry','WingAction'))]
            subprocess.run([javac,'-d',temp,*map(str,sources),str(path/'CoverageProbe.java')],check=True,timeout=60)
            subprocess.run([java,'-cp',temp+os.pathsep+str(ROOT/'mod/src/main/resources'),'CoverageProbe'],check=True,timeout=30)

if __name__=='__main__':unittest.main()
