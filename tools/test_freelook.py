"""Exercise production orbit state; --targets also audits cached real Minecraft bytecode."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
package com.cubeon.client.hud;
import java.lang.reflect.Field;
public class FreelookTest {
    static int checks;
    static void check(boolean ok, String why) {
        checks++;
        if (!ok) throw new AssertionError(why);
    }
    static void near(double a, double b, String why) {
        check(Math.abs(a-b) < .000001, why + ": " + a + " vs " + b);
    }
    static Object player = new Object(), world = new Object();
    static int update(Freelook f, boolean held, boolean eligible, int view) {
        return f.update(held, eligible, player, world, 35, 20, view);
    }
    public static void main(String[] args) throws Exception {
        for (int view=0; view<3; view++) {
            Freelook f = new Freelook();
            check(!f.look(20, 10) && !f.scroll(1), "Normal input unconsumed");
            check(update(f, true, true, view) == 1 && f.active(), "Rear orbit starts from each view");
            near(f.yaw(), view == 2 ? -145 : 35, "Front view facing preserved");
            near(f.pitch(), view == 2 ? -20 : 20, "Front view pitch preserved");
            near(f.distance(), 4, "Default camera distance");
            float yaw=f.yaw(), pitch=f.pitch();
            check(f.look(40, -20), "Active look consumed");
            near(f.yaw(), yaw+6, "Vanilla-scaled camera yaw");
            near(f.pitch(), pitch-3, "Vanilla-scaled camera pitch");
            f.update(true, true, player, world, -60, -30, 1);
            near(f.yaw(), yaw+6, "Player angles never override orbit yaw");
            near(f.pitch(), pitch-3, "Player angles never override orbit pitch");
            check(update(f, false, true, 1) == view && !f.active(), "Release restores saved view");
            check(!f.look(3, 7) && !f.scroll(-1), "Release restores input immediately");
            for (String name : new String[]{"owner", "world"}) {
                Field field=Freelook.class.getDeclaredField(name); field.setAccessible(true);
                check(field.get(f) == null, "Stop releases player/world references");
            }
        }
        for (int reason=0; reason<4; reason++) {
            Freelook f=new Freelook(); update(f, true, true, 0);
            Object nextPlayer=reason==1 ? new Object() : player;
            Object nextWorld=reason==2 ? new Object() : world;
            int nextView=reason==3 ? 2 : 1;
            int restored=f.update(true, reason!=0, nextPlayer, nextWorld, 0, 0, nextView);
            check(restored == (reason==3 ? 2 : 0) && !f.active(), "Menu/focus/entity/world/F5 stops");
            check(update(f, true, true, restored) == restored && !f.active(), "Interrupted hold cannot restart");
            update(f, false, true, restored);
            check(update(f, true, true, restored) == 1 && f.active(), "Fresh hold restarts");
        }
        Freelook blocked=new Freelook();
        update(blocked, true, false, 0);
        check(update(blocked, true, true, 0) == 0 && !blocked.active(), "Hold started in menu remains blocked");
        update(blocked, false, true, 0); update(blocked, true, true, 0);
        check(blocked.active(), "Release clears menu gate");
        for (int view : new int[]{0,2}) {
            Freelook f=new Freelook(); update(f,true,true,0);
            check(update(f,true,true,view)==view && !f.active(), "Manual F5 wins both directions");
        }
        Freelook f=new Freelook(); update(f,true,true,0);
        f.look(1000000, 1000000);
        check(f.yaw()>=-180 && f.yaw()<180 && f.pitch()==90, "Large look wraps/clamps");
        f.look(0,-1000000); near(f.pitch(),-90,"Lower pitch clamp");
        float yaw=f.yaw(), pitch=f.pitch();
        f.look(Double.NaN,Double.POSITIVE_INFINITY);
        near(f.yaw(),yaw,"Invalid yaw ignored"); near(f.pitch(),pitch,"Invalid pitch ignored");
        check(!f.scroll(0) && !f.scroll(Double.NaN) && !f.scroll(Double.NEGATIVE_INFINITY), "Unused wheel events unconsumed");
        check(f.scroll(1),"Active wheel consumed");
        double closer=f.easeDistance(1);
        check(closer<4 && closer>1,"Scroll up approaches player");
        f.scroll(-2); check(f.easeDistance(1)>closer,"Scroll down moves outward");
        f.scroll(1000000); near(f.easeDistance(10),1,"Near distance clamp");
        f.scroll(-1000000); near(f.easeDistance(10),12,"Far distance clamp");
        update(f,false,true,1); update(f,true,true,0);
        near(f.distance(),12,"Chosen distance remembered between holds");
        double reference=0;
        for (int fps : new int[]{30,60,240}) {
            Freelook orbit=new Freelook(); update(orbit,true,true,0); orbit.scroll(-4);
            double distance=0;
            for (int frame=0; frame<fps; frame++) distance=orbit.easeDistance(1.0/fps);
            check(distance>4 && distance<12,"Easing bounded");
            if(reference!=0) near(distance,reference,"Distance easing independent of FPS");
            reference=distance;
        }
        System.out.println(checks + " freelook state checks passed.");
    }
}
'''

# These fixtures expose input and perspective effects of the production Yarn
# controller/callbacks. The separate real-JAR audit validates injection targets.
ADAPTER_STUBS = {
    'net/minecraft/client/option/Perspective.java': '''package net.minecraft.client.option;
public enum Perspective { FIRST_PERSON, THIRD_PERSON_BACK, THIRD_PERSON_FRONT }''',
    'net/minecraft/client/option/GameOptions.java': '''package net.minecraft.client.option;
public class GameOptions {
 public Perspective view=Perspective.FIRST_PERSON;
 public Perspective getPerspective(){return view;}
 public void setPerspective(Perspective p){view=p;}
}''',
    'net/minecraft/client/network/ClientPlayerEntity.java': '''package net.minecraft.client.network;
public class ClientPlayerEntity {
 public float yaw=35,pitch=20; public int turns; public boolean alive=true,sleeping;
 public float getYaw(){return yaw;} public float getPitch(){return pitch;}
 public boolean isAlive(){return alive;} public boolean isSleeping(){return sleeping;}
 public void changeLookDirection(double x,double y){turns++;yaw+=x*.15;pitch+=y*.15;}
}''',
    'net/minecraft/client/Mouse.java': '''package net.minecraft.client;
public class Mouse {public boolean locked=true;public boolean isCursorLocked(){return locked;}}''',
    'net/minecraft/client/render/Camera.java': 'package net.minecraft.client.render; public class Camera {}',
    'net/minecraft/client/MinecraftClient.java': '''package net.minecraft.client;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.client.option.GameOptions;
public class MinecraftClient {
 private static final MinecraftClient INSTANCE=new MinecraftClient();
 public static MinecraftClient getInstance(){return INSTANCE;}
 public ClientPlayerEntity player=new ClientPlayerEntity(); public Object world=new Object(),currentScreen;
 public GameOptions options=new GameOptions();public Mouse mouse=new Mouse();public boolean focused=true;
 public Object getCameraEntity(){return player;} public boolean isWindowFocused(){return focused;}
}''',
    'com/cubeon/client/hud/CubeonHudKeybinds.java': '''package com.cubeon.client.hud;
public class CubeonHudKeybinds {
 public static boolean held,zoomHeld;
 public static boolean freelookHeld(){return held;}
 public static boolean zoomActive(){return zoomHeld && !FreelookController.sync();}
}''',
    'com/cubeon/client/hud/CubeonHudConfig.java': '''package com.cubeon.client.hud;
public class CubeonHudConfig {
 public float zoomFactor=4;private static final CubeonHudConfig INSTANCE=new CubeonHudConfig();
 public static CubeonHudConfig get(){return INSTANCE;}
}''',
}
ADAPTER_HARNESS = r'''
package com.cubeon.client.hud;
import java.lang.reflect.Method;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.Perspective;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.invoke.arg.Args;
import com.cubeon.client.mixin.*;
public class FreelookAdaptersTest {
 static int checks;
 static void check(boolean ok,String why){checks++;if(!ok)throw new AssertionError(why);}
 static Object call(Object o,String name,Object...args) throws Exception {
  Method m=java.util.Arrays.stream(o.getClass().getSuperclass().getDeclaredMethods())
          .filter(v->v.getName().equals(name)).findFirst().orElseThrow();
  m.setAccessible(true);return m.invoke(o,args);
 }
 static class CameraHook extends FreelookCameraMixin {}
 static class LookHook extends ZoomLookMixin {}
 static class ScrollHook extends FreelookScrollMixin {}
 static class Rotation extends Args {
  Rotation(){super(new Object[]{35f,20f});}
  public <T> void set(int index,T value){values[index]=value;}
  public void setAll(Object...args){System.arraycopy(args,0,values,0,args.length);}
 }
 public static void main(String[] args) throws Exception {
  MinecraftClient mc=MinecraftClient.getInstance();
  for(int view=0;view<3;view++)for(boolean reverse:new boolean[]{false,true}){
   CubeonHudKeybinds.held=false;FreelookController.sync();
   mc.options.view=Perspective.values()[view];mc.currentScreen=null;mc.focused=true;
   CameraHook camera=new CameraHook();LookHook look=new LookHook();ScrollHook wheel=new ScrollHook();
   CubeonHudKeybinds.held=true;
   boolean rear,front;
   if(reverse){front=(boolean)call(camera,"cubeon$frontView",view==2);rear=(boolean)call(camera,"cubeon$thirdPerson",view!=0);}
   else{rear=(boolean)call(camera,"cubeon$thirdPerson",view!=0);front=(boolean)call(camera,"cubeon$frontView",view==2);}
   check(rear&&!front,"Entry flags rear-only in either callback order");
   Rotation rotation=new Rotation();call(camera,"cubeon$freelookRotation",rotation);
   check(rotation.<Float>get(0)==Freelook.INSTANCE.yaw()&&rotation.<Float>get(1)==Freelook.INSTANCE.pitch(),"Camera uses independent rotation");
   call(camera,"cubeon$finishedView",new CallbackInfo("frame",false));
   float yaw=mc.player.yaw,pitch=mc.player.pitch;int turns=mc.player.turns;
   CubeonHudKeybinds.zoomHeld=true;
   call(look,"cubeon$zoomLook",mc.player,40.0,20.0);
   check(mc.player.turns==turns&&mc.player.yaw==yaw&&mc.player.pitch==pitch,"Freelook never turns player even with zoom held");
   CallbackInfo scroll=new CallbackInfo("scroll",true);
   call(wheel,"cubeon$freelookScroll",0L,0.0,-1.0,scroll);
   check(scroll.isCancelled(),"Active wheel cancels hotbar handling");
   double selected=Freelook.INSTANCE.easeDistance(10);
   Object vanilla=CAMERA_DISTANCE_ARGUMENT;
   double clipped=((Number)call(camera,"cubeon$freelookDistance",vanilla)).doubleValue();
   check(Math.abs(clipped-selected*2)<.00001,"Distance preserves vanilla entity scaling");
   // The caller read rear-view flags before Alt was released. Both modifiers
   // must see the restored view even after the first modifier stops the state.
   CubeonHudKeybinds.held=false;
   if(reverse){front=(boolean)call(camera,"cubeon$frontView",false);rear=(boolean)call(camera,"cubeon$thirdPerson",true);}
   else{rear=(boolean)call(camera,"cubeon$thirdPerson",true);front=(boolean)call(camera,"cubeon$frontView",false);}
   check(rear==(view!=0)&&front==(view==2),"Same-frame release restores both saved flags");
   call(camera,"cubeon$finishedView",new CallbackInfo("frame",false));
   CubeonHudKeybinds.zoomHeld=false;
   call(look,"cubeon$zoomLook",mc.player,40.0,20.0);
   check(mc.player.turns==turns+1&&Math.abs(mc.player.yaw-yaw-6)<.00001,"Normal aim immediately restored");
   scroll=new CallbackInfo("scroll",true);call(wheel,"cubeon$freelookScroll",0L,0.0,1.0,scroll);
   check(!scroll.isCancelled(),"Normal wheel reaches hotbar");
   // Ineligible camera/input events stop the state and restore the saved view.
   CubeonHudKeybinds.held=true;FreelookController.sync();mc.focused=false;
   check(!FreelookController.look(5,5)&&mc.options.view.ordinal()==view,"Focus loss restores view and input");
   mc.focused=true;check(!FreelookController.sync(),"Focus regain with stale hold stays off");
   CubeonHudKeybinds.held=false;FreelookController.sync();
   CubeonHudKeybinds.held=true;FreelookController.sync();mc.currentScreen=new Object();
   check(!FreelookController.scroll(-1)&&mc.options.view.ordinal()==view,"Menu restores view and wheel");
   mc.currentScreen=null;CubeonHudKeybinds.held=false;FreelookController.sync();
  }
  System.out.println(checks+" production camera/controller/input checks passed.");
 }
}
'''


@unittest.skipUnless(shutil.which('java') and shutil.which('javac'), 'JDK required')
class FreelookTests(unittest.TestCase):
    def test_production_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            harness = folder / 'FreelookTest.java'
            harness.write_text(HARNESS)
            source = ROOT / 'mod/src/main/java/com/cubeon/client/hud/Freelook.java'
            result = subprocess.run(['javac', '--release', '17', '-d', str(folder),
                                     str(source), str(harness)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run(['java', '-cp', str(folder), 'com.cubeon.client.hud.FreelookTest'],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_production_camera_and_input_callbacks(self):
        jars = list(Path.home().glob('.gradle/caches/modules-2/files-2.1/net.fabricmc/sponge-mixin/*/*/*.jar'))
        if not jars:
            self.skipTest('cached Fabric Mixin library required for callback checks')
        for precision in ('double', 'float'):
            with self.subTest(precision=precision), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                sources = []
                for name, code in ADAPTER_STUBS.items():
                    path = folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(code)
                    sources.append(str(path))
                harness = folder / 'FreelookAdaptersTest.java'
                harness.write_text(ADAPTER_HARNESS.replace('CAMERA_DISTANCE_ARGUMENT',
                                                         'Double.valueOf(8)' if precision == 'double' else 'Float.valueOf(8)'))
                sources.append(str(harness))
                for name in ('Freelook', 'Zoom'):
                    sources.append(str(ROOT / f'mod/src/main/java/com/cubeon/client/hud/{name}.java'))
                sources.extend(str(ROOT / path) for path in (
                    'mod/src/main/java-overlay-freelook-yarn/com/cubeon/client/hud/FreelookController.java',
                    'mod/src/main/java-overlay-freelook-yarn/com/cubeon/client/mixin/FreelookScrollMixin.java',
                    f'mod/src/main/java-overlay-freelook-camera-{precision}/com/cubeon/client/mixin/FreelookCameraMixin.java',
                    f'mod/src/main/java-overlay-zoom-{precision}/com/cubeon/client/mixin/ZoomLookMixin.java'))
                run = subprocess.run(['javac', '-proc:none', '--release', '17', '-cp', str(jars[0]),
                                      '-d', str(folder), *sources], capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                run = subprocess.run(['java', '-cp', str(folder)+os.pathsep+str(jars[0]),
                                      'com.cubeon.client.hud.FreelookAdaptersTest'], capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                print(precision + ': ' + run.stdout.strip())


def audit_targets():
    """Check descriptors and invocations used by our mixins against every mapped game JAR."""
    base = ROOT / 'mod/.gradle/loom-cache/minecraftMaven/net/minecraft'
    paths = list(base.glob('*/*/*.jar'))
    matrix = json.loads((ROOT / 'mod/brackets.json').read_text())['brackets']
    for bracket in matrix:
        version = bracket['compile_against']
        game = next(p for p in paths if p.parent.name.split('-net.fabricmc')[0] == version
                    and '-sources' not in p.name)
        native = bracket['mappings'] == 'none'
        def javap(cls):
            return subprocess.check_output(['javap', '-p', '-c', '-classpath', str(game), cls],
                                           text=True, timeout=60)
        def method_body(bytecode, name):
            # javap declarations are indented two spaces; instruction lines are deeper.
            return next(block for block in re.split(r'(?m)(?=^  \S)', bytecode)
                        if re.match(r'  [^\n]*\b' + name + r'\(', block))
        def require(ok, why):
            if not ok:
                raise AssertionError(f'{version}: {why}')
        camera_cls = 'net.minecraft.client.Camera' if native else 'net.minecraft.client.render.Camera'
        camera = javap(camera_cls)
        precision = 'float' if native or version.startswith('1.21') else 'double'
        collision = 'getMaxZoom' if native else 'clipToSpace'
        require(f'{collision}({precision});' in camera, 'collision parameter precision')
        rotation = method_body(camera, 'alignWithEntity' if native else 'update')
        require('setRotation:(FF)V' in rotation, 'camera rotation invocation')
        require(collision in rotation, 'chosen distance enters vanilla collision test')
        require('RaycastContext' in camera or 'ClipContext' in camera, 'vanilla wall raycast retained')
        if not native:
            require(re.search(r'update\([^\n]+boolean, boolean, float\);', camera), 'rear/front argument slots')
        else:
            require('update(net.minecraft.client.DeltaTracker);' in camera, 'native update before view lookup')
        enum = javap('net.minecraft.client.CameraType' if native else 'net.minecraft.client.option.Perspective')
        views = re.findall(r'public static final [^;]+ (\w+);', enum)
        require(views == ['FIRST_PERSON', 'THIRD_PERSON_BACK', 'THIRD_PERSON_FRONT'], 'perspective ordinals')
        mouse = javap('net.minecraft.client.MouseHandler' if native else 'net.minecraft.client.Mouse')
        body = method_body(mouse, 'turnPlayer' if native else 'updateMouse')
        target = 'LocalPlayer.turn:(DD)V' if native else 'ClientPlayerEntity.changeLookDirection:(DD)V'
        require(body.count(target) == 1, 'exact mouse redirect target')
        require(('onScroll(long, double, double);' if native else 'onMouseScroll(long, double, double);') in mouse,
                'scroll callback descriptor')
        print(f'{version}: camera rotation, collision, view and input targets passed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', action='store_true', help='requires all mapped Minecraft JARs cached by Loom')
    args = parser.parse_args()
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(FreelookTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.targets:
        audit_targets()
