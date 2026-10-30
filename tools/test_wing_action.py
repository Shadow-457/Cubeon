"""Exercise the real N key adapters with queued input, focus and menu fixtures."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'mod/src/main'

COMMON = {
    'com/cubeon/client/hud/CubeonHudClient.java': 'package com.cubeon.client.hud; public class CubeonHudClient { public static final String MOD_ID="cubeon-client"; }',
    'com/cubeon/client/hud/CubeonHudConfig.java': 'package com.cubeon.client.hud; public class CubeonHudConfig { public boolean cosmeticAnimations=true; private static final CubeonHudConfig VALUE=new CubeonHudConfig(); public static CubeonHudConfig get(){return VALUE;} }',
    'com/cubeon/client/hud/FreelookController.java': 'package com.cubeon.client.hud; public class FreelookController { public static boolean sync(){return false;} }',
    'com/cubeon/client/hud/screen/CubeonHudMenuScreen.java': 'package com.cubeon.client.hud.screen; public class CubeonHudMenuScreen {}',
    'com/cubeon/client/hud/screen/EmoteMenuScreen.java': 'package com.cubeon.client.hud.screen; public class EmoteMenuScreen {}',
    'com/cubeon/client/cosmetics/CosmeticSelection.java': 'package com.cubeon.client.cosmetics; public class CosmeticSelection { public static String wing="back_ember_wings"; public static String selectedWing(){return wing != null && wing.endsWith("_small") ? null : wing;} }',
    'org/lwjgl/glfw/GLFW.java': 'package org.lwjgl.glfw; public class GLFW { public static final int GLFW_KEY_K=75,GLFW_KEY_B=66,GLFW_KEY_N=78,GLFW_KEY_Z=90,GLFW_KEY_LEFT_ALT=342; }',
    'net/minecraft/client/util/InputUtil.java': 'package net.minecraft.client.util; public class InputUtil { public enum Type { KEYSYM } }',
    'com/mojang/blaze3d/platform/InputConstants.java': 'package com.mojang.blaze3d.platform; public class InputConstants { public enum Type { KEYSYM,KEYBOARD } public static final int KEY_K=75,KEY_B=66,KEY_N=78,KEY_LALT=342; }',
    'net/minecraft/util/Identifier.java': 'package net.minecraft.util; public class Identifier { public static Identifier of(String n,String p){return new Identifier();} }',
    'net/minecraft/resources/Identifier.java': 'package net.minecraft.resources; public class Identifier { public static Identifier fromNamespaceAndPath(String n,String p){return new Identifier();} }',
}

BINDING = '''package {package};
public class {binding} {{
 public String name; public int code,queued; public boolean down;
 public {binding}(String n,{input}.Type t,int c,Object category){{name=n;code=c;}}
 public boolean {held}(){{return down;}}
 public boolean {pressed}(){{if(queued==0)return false;queued--;return true;}}
 public static class Category {{
  public static Category {category}({identifier} id){{return new Category();}}
 }}
}}'''

CLIENT = '''package net.minecraft.client;
public class {client} {{
 private static final {client} VALUE=new {client}();
 public static {client} getInstance(){{return VALUE;}}
 public Player player=new Player(); public Object {world}=new Object(),{screen};
 public boolean focused=true; public Mouse {mouse}=new Mouse(); public Gui gui=new Gui();
 public Object getCameraEntity(){{return player;}}
 public boolean {focused}(){{return focused;}}
 public void setScreen(Object value){{{screen}=value;}}
 public class Gui {{ public Object screen(){{return {screen};}} public void setScreen(Object value){{{screen}=value;}} }}
 public static class Mouse {{public boolean grabbed=true;public boolean {grabbed}(){{return grabbed;}}}}
 public static class Player {{public int {age}=200; public boolean alive=true,sleeping;
  public boolean isAlive(){{return alive;}} public boolean isSleeping(){{return sleeping;}}}}
}}'''

HARNESS = '''package probe;
import com.cubeon.client.hud.*;
import com.cubeon.client.cosmetics.*;
import net.minecraft.client.{client};
import {binding_package}.{binding};
import java.lang.reflect.Field;
public class NTest {{
 static int checks;
 static void check(boolean condition,String label){{checks++;if(!condition)throw new AssertionError(label);}}
 public static void main(String[] args) throws Exception {{
  var mc={client}.getInstance(); CubeonHudKeybinds.register();
  Field field=CubeonHudKeybinds.class.getDeclaredField("wingFlare");field.setAccessible(true);
  var key=({binding})field.get(null);
  check(key.code==78 && key.name.equals("key.cubeon-client.wing_flare"),"N default and control label");
  check({helper}.keys.contains(key),"Registered native key binding");
  key.down=true;key.queued=1;CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10)==0,"Native N press plays the action");
  check(key.queued==0,"Press queue drained");
  mc.player.{age}++;key.queued=4;CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)>.049f,"Repeats do not restart");
  mc.{screen}=new Object();key.queued=2;CubeonHudKeybinds.tick();
  check(key.queued==0 && WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"Menus cancel and drain N");
  mc.{screen}=null;key.queued=1;CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"Held N cannot carry out of a menu");
  key.down=false;CubeonHudKeybinds.tick();key.down=true;key.queued=1;CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)==0,"Release and fresh press work");
  mc.focused=false;CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"Focus loss cancels");
  mc.focused=true;key.down=false;CubeonHudKeybinds.tick();
  mc.{mouse}.grabbed=false;key.down=true;key.queued=1;CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"Free mouse ignores N");
  mc.{mouse}.grabbed=true;key.down=false;CubeonHudKeybinds.tick();
  CubeonHudConfig.get().cosmeticAnimations=false;key.down=true;key.queued=1;CubeonHudKeybinds.tick();
  check(key.queued==0 && WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"Motion OFF ignores N");
  CubeonHudConfig.get().cosmeticAnimations=true;key.down=false;CubeonHudKeybinds.tick();
  CosmeticSelection.wing=null;key.down=true;key.queued=1;CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"No equipped wing ignores N");
  CosmeticSelection.wing="back_ember_wings";key.down=false;CubeonHudKeybinds.tick();
  key.code=71;{helper}.press(78);CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"Old key stops after rebinding");
  {helper}.press(71);CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)==0,"Rebound key plays action");
  CosmeticSelection.wing="back_ember_wings_small";CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"Switching to Small cancels a Giant flare");
  key.down=false;CubeonHudKeybinds.tick();key.down=true;key.queued=1;CubeonHudKeybinds.tick();
  check(key.queued==0 && WingAction.INSTANCE.elapsed(mc.player,mc.{world},10.05f)<0,"Small wings completely ignore N");
  mc.player=null;CubeonHudKeybinds.tick();
  check(WingAction.INSTANCE.elapsed(null,mc.{world},10.05f)<0,"Leaving world clears action");
  System.out.println(checks+" native wing input checks passed.");
 }}
}}'''


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'A JDK is required')
class WingInputTests(unittest.TestCase):
    def test_native_keybinding_eras(self):
        for adapter in sorted(MAIN.glob('java-overlay-hud-*/com/cubeon/client/hud/CubeonHudKeybinds.java')):
            era = adapter.relative_to(MAIN).parts[0]
            mojang = 'KeyMapping' in adapter.read_text()
            names = dict(client='Minecraft' if mojang else 'MinecraftClient',
                         package='net.minecraft.client' if mojang else 'net.minecraft.client.option',
                         binding='KeyMapping' if mojang else 'KeyBinding',
                         input='com.mojang.blaze3d.platform.InputConstants' if mojang else 'net.minecraft.client.util.InputUtil',
                         held='isDown' if mojang else 'isPressed', pressed='consumeClick' if mojang else 'wasPressed',
                         category='register' if mojang else 'create',
                         identifier='net.minecraft.resources.Identifier' if mojang else 'net.minecraft.util.Identifier',
                         world='level' if mojang else 'world', screen='screen' if mojang else 'currentScreen',
                         mouse='mouseHandler' if mojang else 'mouse', age='tickCount' if mojang else 'age',
                         focused='isWindowActive' if mojang else 'isWindowFocused',
                         grabbed='isMouseGrabbed' if mojang else 'isCursorLocked')
            names['binding_package'] = names['package']
            helper_package = 'net.fabricmc.fabric.api.client.' + ('keymapping' if mojang else 'keybinding') + '.v1'
            helper_name = 'KeyMappingHelper' if mojang else 'KeyBindingHelper'
            names['helper'] = helper_package + '.' + helper_name
            fixtures = dict(COMMON)
            fixtures[names['package'].replace('.', '/') + '/' + names['binding'] + '.java'] = BINDING.format(**names)
            fixtures['net/minecraft/client/' + names['client'] + '.java'] = CLIENT.format(**names)
            fixtures[helper_package.replace('.', '/') + '/' + helper_name + '.java'] = f'''package {helper_package};
public class {helper_name} {{
 public static java.util.List<{names['package']}.{names['binding']}> keys=new java.util.ArrayList<>();
 public static void register{names['binding']}({names['package']}.{names['binding']} key){{keys.add(key);}}
 public static void press(int code){{for(var key:keys)if(key.code==code){{key.down=true;key.queued++;}}}}
}}'''
            fixtures['probe/NTest.java'] = HARNESS.format(**names)
            with self.subTest(era=era), tempfile.TemporaryDirectory(prefix='cubeon-wing-input-') as temporary:
                folder = Path(temporary)
                files = []
                for name, source in fixtures.items():
                    path = folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source)
                    files.append(str(path))
                files += [str(adapter), str(MAIN / 'java/com/cubeon/client/cosmetics/WingAction.java')]
                built = subprocess.run(['javac', '--release', '17', '-d', str(folder), *files], capture_output=True, text=True, timeout=60)
                self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                tested = subprocess.run(['java', '-cp', str(folder), 'probe.NTest'], capture_output=True, text=True, timeout=60)
                self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
                print(era + ': ' + tested.stdout.strip())


if __name__ == '__main__':
    unittest.main()
