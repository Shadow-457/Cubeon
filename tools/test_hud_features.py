"""Run actual persisted HUD config and bounded display state with native-free fixtures."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'mod/src/main'


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
class HudFeaturesTests(unittest.TestCase):
    def test_defaults_migration_reset_sampling_and_combos(self):
        gson = next(iter(Path.home().glob('.gradle/caches/modules-2/files-2.1/com.google.code.gson/gson/*/*/gson-*.jar')), None)
        if gson is None:
            self.skipTest('Cached Gson required; run a mod build first')
        with tempfile.TemporaryDirectory(prefix='cubeon-hud-features-') as temporary:
            folder = Path(temporary)
            stubs = {
                'net/fabricmc/loader/api/FabricLoader.java': '''package net.fabricmc.loader.api;
public class FabricLoader {
 public static FabricLoader getInstance(){return new FabricLoader();}
 public java.nio.file.Path getConfigDir(){return java.nio.file.Path.of(System.getProperty("probe.config"));}
}''',
                'com/cubeon/client/hud/CubeonHudClient.java': '''package com.cubeon.client.hud;
public class CubeonHudClient { public static final Log LOGGER=new Log();
 public static class Log { public void warn(String value,Exception e){throw new RuntimeException(value,e);} }
}''',
                'Probe.java': r'''
import com.cubeon.client.hud.*;
import com.cubeon.client.ui.*;
import java.nio.file.*;
import java.util.*;
public class Probe {
 static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
 static class Canvas implements ClientUi.Canvas {
  List<String> text=new ArrayList<>(); int draws;
  public void fill(int a,int b,int c,int d,int color){check(a>=0&&b>=0&&c<=320&&d<=240,"HUD bounds");draws++;}
  public void text(String value,int x,int y,int color){text.add(value);}
  public String translate(String key){return key;}
 }
 public static void main(String[] args)throws Exception {
  var c=CubeonHudConfig.get();
  check(!c.showFps&&!c.showKeys&&!c.showArmor&&!c.showPing&&!c.showCps&&!c.showEnemyHealth,"Original HUDs default off");
  check(!c.autoSprint&&!c.extrasEnabled(),"New features default off");
  check(c.menuAnimations,"Menu motion defaults on");
  check(!c.temporalMotionBlur&&c.temporalBlurStrength==1,"Motion blur+ defaults off at normal strength");
  check(!c.showOwnNameTag,"Own name tag defaults off");
  for(var f:HudFeatures.values())if(f.extra())check(!c.extra(f.slot).enabled,"Every new HUD defaults off");
  Path config=Path.of(System.getProperty("probe.config"));
  Files.writeString(config.resolve("keyhud.json"),"{\"showFps\":true,\"scale\":1.5,\"fpsX\":0.75}");
  CubeonHudConfig.load();c=CubeonHudConfig.get();
  check(c.showFps&&c.scaleFor("fps")==1.5f&&c.fpsX==.75f&&!c.autoSprint&&!c.extrasEnabled(),"Legacy configs retain choices and opt-in defaults");
  check(c.menuAnimations,"Old configs keep the default menu motion choice");
  c.extra("coordinates").enabled=true;c.extra("coordinates").x=.72f;c.setScaleFor("coordinates",2);
  c.autoSprint=true;
  CubeonHudConfig.save();CubeonHudConfig.load();c=CubeonHudConfig.get();
  check(c.extraEnabled("coordinates")&&c.extra("coordinates").x==.72f&&c.scaleFor("coordinates")==2&&c.autoSprint,"Selections persist independently");
  String saved=Files.readString(config.resolve("cubeon-client-hud.json"));
  c.showOwnNameTag=true;c.menuAnimations=false;c.setScaleForLive("coordinates",1.37f);
  check(Files.readString(config.resolve("cubeon-client-hud.json")).equals(saved),"Live slider changes avoid disk writes");
  CubeonHudConfig.save();CubeonHudConfig.load();c=CubeonHudConfig.get();
  check(c.showOwnNameTag,"Own name tag preference persists");
  check(!c.menuAnimations&&c.scaleFor("coordinates")==1.37f&&c.scaleFor("fps")==1.5f,"Motion setting and arbitrary per-overlay slider sizes persist");
  CubeonHudConfig.resetPositions();check(c.showFps&&c.extraEnabled("coordinates")&&c.extra("coordinates").x==0&&c.scaleFor("coordinates")==1,"Layout reset keeps toggles and resets positions/sizes");
  var canvas=new Canvas();
  check(HudFeatures.slot("minimap")==null,"Removed minimap has no catalogue slot");
  Files.writeString(config.resolve("cubeon-client-hud.json"),"{\"customReticle\":true,\"extraOverlays\":{\"minimap\":{\"enabled\":true},\"coordinates\":{\"enabled\":true,\"x\":0.72,\"scale\":1.25}}}");
  CubeonHudConfig.load();c=CubeonHudConfig.get();
  check(!c.extraOverlays.containsKey("minimap")&&c.extraEnabled("coordinates")&&c.scaleFor("coordinates")==1.25f,"Removed saved features are pruned without changing remaining preferences");
  CubeonHudConfig.save();
  check(!Files.readString(config.resolve("cubeon-client-hud.json")).contains("customReticle"),"Removed crosshair toggle is not persisted");
  c.cameraMotionBlur=true;c.temporalMotionBlur=true;c.temporalBlurStrength=4;
  CubeonHudConfig.save();CubeonHudConfig.load();c=CubeonHudConfig.get();
  check(c.temporalMotionBlur&&!c.cameraMotionBlur&&c.temporalBlurStrength==2,"Plus persists, clamps strength and avoids stacking blur effects");
  c.temporalBlurStrength=.01f;CubeonHudConfig.save();CubeonHudConfig.load();c=CubeonHudConfig.get();
  check(c.temporalBlurStrength==.25f,"Plus strength clamps at the minimum");
  c.temporalBlurStrength=Float.NaN;CubeonHudConfig.save();CubeonHudConfig.load();c=CubeonHudConfig.get();
  check(c.temporalBlurStrength==1,"Invalid plus strength restores the default");
  c.extra("combo").enabled=true;
  ExtraHud.damage(7,1,2,1,1000);check(ExtraHud.combo(1000)==0,"Projectile hits do not count");
  ExtraHud.damage(7,1,1,1,1100);ExtraHud.damage(7,1,1,1,1500);check(ExtraHud.combo(1500)==2,"Confirmed same-target melee hits stack");
  ExtraHud.damage(8,1,1,1,2000);check(ExtraHud.combo(2000)==1,"Target changes restart combo");
  ExtraHud.damage(1,8,8,1,2100);check(ExtraHud.combo(2100)==0,"Incoming damage resets combo");
  ExtraHud.damage(8,1,1,1,2200);check(ExtraHud.combo(5300)==0,"Idle combo expires");
  c.extra("combo").enabled=false;ExtraHud.damage(8,1,1,1,5400);check(ExtraHud.combo(5400)==0,"Disabled combo does not accumulate");
  ExtraHud.system(Double.NaN);canvas=new Canvas();ExtraHud.render(canvas,HudFeatures.SYSTEM,0,0,false);
  check(canvas.text.contains("GPU frame: —"),"Unavailable GPU data is not an invented percentage");
  ExtraHud.environment(18000,"Plains",9,15);canvas=new Canvas();ExtraHud.render(canvas,HudFeatures.DAYLIGHT,0,0,false);
  check(canvas.text.contains("Day 0   00:00")&&canvas.text.contains("Block 9   Sky 15"),"Time conversion and light readouts");
  c.worldClock=true;canvas=new Canvas();ExtraHud.render(canvas,HudFeatures.CLOCK,0,0,false);check(canvas.text.contains("00:00"),"Clock mode uses world time");
  ExtraHud.effects(Collections.nCopies(20,new ExtraHud.Effect("An unusually long effect name","1:20",0xaaaaaa,0,null)));
  check(ExtraHud.effects().size()==6&&ExtraHud.height(HudFeatures.POTIONS)==74,"Potion rows remain bounded");
  canvas=new Canvas();ExtraHud.render(canvas,HudFeatures.POTIONS,0,0,false);
  check(canvas.text.contains("1:20"),"Long potion names cannot truncate duration timers");
  ExtraHud.effects(List.of());canvas=new Canvas();ExtraHud.render(canvas,HudFeatures.POTIONS,0,0,false);check(canvas.draws==0,"Empty potion HUD is absent during gameplay");check(ExtraHud.height(HudFeatures.POTIONS)==12,"Empty potion HUD collapses to one compact line");
  for(var f:List.of(HudFeatures.CLOCK,HudFeatures.DIRECTION,HudFeatures.BIOME,HudFeatures.COMBO))check(ExtraHud.height(f)==12,"Single-line HUDs stay compact");
  for(var f:List.of(HudFeatures.SYSTEM,HudFeatures.COORDINATES,HudFeatures.DAYLIGHT))check(ExtraHud.height(f)==24,"Two-line readings have no repeated heading");
  canvas=new Canvas();ExtraHud.render(canvas,HudFeatures.BIOME,0,0,false);
  check(canvas.draws==1&&ExtraHud.width(HudFeatures.BIOME,canvas::width)<50,"New readout uses one tight backing rather than a wide green card");
  ExtraHud.reset();canvas=new Canvas();ExtraHud.render(canvas,HudFeatures.COMBO,0,0,false);check(canvas.draws==0,"Idle combo is hidden during gameplay");
  System.out.println("Defaults, migration, persistence, reset, removed-feature migration, confirmed combos, effects, GPU fallback, and clock passed.");
 }
}'''}
            for name, text in stubs.items():
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            shared = MAIN / 'java/com/cubeon/client'
            sources = [*folder.rglob('*.java'), shared/'hud/HudFeatures.java', shared/'hud/CubeonHudConfig.java',
                       shared/'hud/ExtraHud.java', shared/'ui/ClientTheme.java', shared/'ui/ClientUi.java', shared/'emotes/EmoteFavorites.java',
                       shared/'emotes/EmoteState.java', shared/'emotes/EmotePose.java', shared/'Bridge.java', shared/'Json.java']
            result = subprocess.run(['javac','--release','17','-cp',str(gson),'-d',str(folder),*map(str,sources)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result = subprocess.run(['java','-Dprobe.config='+str(folder),'-cp',str(folder)+':'+str(gson),'Probe'],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
