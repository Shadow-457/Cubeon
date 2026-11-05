"""Exercise 26.3 input/zoom/blur; --legacy-blur checks real 1.20 sky post-processing."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import zipfile

from minecraft_launcher_lib.command import get_minecraft_command

ROOT = Path(__file__).resolve().parents[1]
GAME = Path.home() / '.cubeon_minecraft'
PROFILE = Path.home() / '.cubeon_launcher/mod_profiles/26.3-fabric'
OUT = ROOT / 'archive/ui-captures/client-263-fixes'
JAVA = Path.home() / 'jdks/jdk-25.0.4.1+1/bin'

PROBE = r'''
package probe;
import com.cubeon.client.hud.*;
import com.cubeon.client.hud.blur.CameraBlurRenderer;
import com.cubeon.client.hud.screen.CubeonHudMenuScreen;
import com.cubeon.client.ui.HudMenu;
import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.input.KeyEvent;
import java.lang.reflect.*;
import java.nio.file.*;

public class ClientProbe implements ClientModInitializer {
    int ticks, stage, movingFrames;
    long started;
    float normalFov;
    static int checks;
    static void check(boolean ok, String why) {
        if (!ok) throw new AssertionError(why); checks++;
    }
    static Object field(Object obj, String name) throws Exception {
        Field f=obj.getClass().getDeclaredField(name); f.setAccessible(true); return f.get(obj);
    }
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(mc -> {
            if(mc.level==null || mc.player==null) return;
            try {
                ticks++;
                if(stage==0 && ticks>=40) {
                    CubeonHudConfig.get().cameraMotionBlur=true;
                    CameraBlurRenderer.reset(); stage=1; ticks=0;
                } else if(stage==1) {
                    mc.player.setYRot(mc.player.getYRot()+4);
                    if(CameraBlur.INSTANCE.moving()) movingFrames++;
                    if(ticks>=40) {
                        check(!(boolean)fieldStatic(CameraBlurRenderer.class,"failed"),"Real GPU blur pass succeeds");
                        check(fieldStatic(CameraBlurRenderer.class,"scratch")!=null,"Real GPU blur allocates scene texture");
                        check(movingFrames>10,"Rendered moving camera produces blur");
                        System.out.println("CUBEON_263_BLUR_PASS");
                        var screen=new CubeonHudMenuScreen(); mc.gui.setScreen(screen);
                        var menu=(HudMenu)field(screen,"menu");
                        var r=menu.control(HudMenu.SEARCH);
                        screen.mouseClicked(new net.minecraft.client.input.MouseButtonEvent(r.x()+8,r.y()+8,
                                new net.minecraft.client.input.MouseButtonInfo(InputConstants.MOUSE_BUTTON_LEFT,0)),false);
                        System.out.println("CUBEON_263_SEARCH_READY"); stage=2; started=System.nanoTime();
                    }
                } else if(stage==2) {
                    var screen=(CubeonHudMenuScreen)mc.gui.screen();
                    var menu=(HudMenu)field(screen,"menu");
                    if(menu.query().equals("blur")) {
                        check(screen.isInputCaptured(),"Search captures shortcuts");
                        screen.keyPressed(new KeyEvent(InputConstants.KEY_BACKSPACE,InputConstants.KEYCODE_BACKSPACE,0));
                        check(menu.query().equals("blu"),"Backspace edits search");
                        screen.keyPressed(new KeyEvent(InputConstants.KEY_RETURN,InputConstants.KEYCODE_RETURN,0));
                        check(!screen.isInputCaptured(),"Enter releases text input");
                        screen.keyPressed(new KeyEvent(InputConstants.KEY_SLASH,0,0));
                        check(screen.isInputCaptured(),"Slash focuses search");
                        screen.keyPressed(new KeyEvent(InputConstants.KEY_ESCAPE,0,0));
                        check(!screen.isInputCaptured() && mc.gui.screen()==screen,"Escape first releases search");
                        screen.onClose();
                        normalFov=mc.gameRenderer.mainCamera().getFov();
                        System.out.println("CUBEON_263_SEARCH_PASS");
                        stage=3; ticks=0;
                    } else if(System.nanoTime()-started>15_000_000_000L) throw new AssertionError("SDL typing never reached search: "+menu.query());
                } else if(stage==3 && ticks>=8) {
                    var zoom=(KeyMapping)fieldStatic(CubeonHudKeybinds.class,"zoom");
                    zoom.setDown(true); stage=4; ticks=0;
                } else if(stage==4 && ticks>=20) {
                    check(mc.gameRenderer.mainCamera().getFov()<normalFov*.4,"Real camera projection zooms");
                    var mouse=mc.mouseHandler;
                    float yaw=mc.player.getYRot();
                    look(mc,60,0);
                    check(Math.abs(mc.player.getYRot()-yaw)<3,"Native zoom redirect slows mouse aiming");
                    Method scroll=mouse.getClass().getDeclaredMethod("onScroll",long.class,double.class,double.class); scroll.setAccessible(true);
                    int slot=mc.player.getInventory().getSelectedSlot();
                    scroll.invoke(mouse,mc.getWindow().handle(),0d,-1d);
                    check(mc.player.getInventory().getSelectedSlot()==slot,"Zoom wheel preserves hotbar");
                    stage=5; ticks=0;
                } else if(stage==5 && ticks>=15) {
                    check(mc.gameRenderer.mainCamera().getFov()>normalFov*.27,"Wheel widens zoom");
                    ((KeyMapping)fieldStatic(CubeonHudKeybinds.class,"zoom")).setDown(false);
                    stage=6; ticks=0;
                } else if(stage==6 && ticks>=30) {
                    check(Math.abs(mc.gameRenderer.mainCamera().getFov()-normalFov)<.2,"Release restores world FOV");
                    float yaw=mc.player.getYRot();
                    look(mc,60,0);
                    check(Math.abs(mc.player.getYRot()-yaw-9)<.001,"Native release restores normal sensitivity");
                    CubeonHudConfig.get().cameraMotionBlur=false;
                    stage=7; ticks=0;
                } else if(stage==7 && ticks>=5) {
                    check(fieldStatic(CameraBlurRenderer.class,"scratch")==null,"Off releases GPU textures");
                    check(!CameraBlur.INSTANCE.moving(),"Off clears motion");
                    System.out.println("CUBEON_263_NATIVE_PASS "+checks+" checks"); mc.stop(); stage=8;
                }
            } catch(Throwable error) {
                System.out.println("CUBEON_263_NATIVE_FAIL "+error); error.printStackTrace(); mc.stop(); stage=8;
            }
        });
    }
    static Object fieldStatic(Class<?> type,String name) throws Exception {
        Field f=type.getDeclaredField(name); f.setAccessible(true); return f.get(null);
    }
    static void look(Minecraft mc,double dx,double dy) throws Exception {
        for(Method m:mc.mouseHandler.getClass().getDeclaredMethods()) {
            if(m.getName().contains("cubeon$freelookLook")) {
                m.setAccessible(true); m.invoke(mc.mouseHandler,mc.player,dx,dy); return;
            }
        }
        throw new AssertionError("Native mouse-look redirect is missing");
    }
}
'''

LEGACY_PROBE = r'''
package probe;
import com.cubeon.client.hud.CameraBlur;
import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.blur.CameraBlurRenderer;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.event.Event;
import java.lang.reflect.*;
import java.nio.*;
import org.lwjgl.opengl.GL11;
import org.lwjgl.opengl.GL15;
import org.lwjgl.opengl.GL21;

/** Intermediary reflection keeps this probe usable in an actual packaged 1.20. */
public class ClientProbe implements ClientModInitializer {
    int ticks;
    boolean done;
    public void onInitializeClient() {
        try {
            Class<?> lifecycle=Class.forName("net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents");
            Class<?> callback=Class.forName(lifecycle.getName()+"$EndTick");
            Object listener=Proxy.newProxyInstance(callback.getClassLoader(),new Class[]{callback},(proxy,method,args)->{
                if(method.getName().equals("onEndTick")) tick(args[0]); return null;
            });
            ((Event)lifecycle.getField("END_CLIENT_TICK").get(null)).register(listener);
        } catch(Exception error) { throw new RuntimeException(error); }
    }
    void tick(Object mc) throws Exception {
        if(done || mc.getClass().getField("field_1687").get(mc)==null || ++ticks<40) return;
        done=true;
        try {
            Object frame=mc.getClass().getMethod("method_1522").invoke(mc);
            int width=frame.getClass().getField("field_1482").getInt(frame);
            int height=frame.getClass().getField("field_1481").getInt(frame);
            int texture=(int)frame.getClass().getMethod("method_30277").invoke(frame);
            ByteBuffer sky=ByteBuffer.allocateDirect(width*height*4);
            for(int i=0;i<width*height;i++) sky.put((byte)37).put((byte)126).put((byte)220).put((byte)0);
            sky.flip();
            GL15.glBindBuffer(GL21.GL_PIXEL_UNPACK_BUFFER,0);
            GL11.glPixelStorei(GL11.GL_UNPACK_ROW_LENGTH,0);
            GL11.glPixelStorei(GL11.GL_UNPACK_SKIP_PIXELS,0);
            GL11.glPixelStorei(GL11.GL_UNPACK_SKIP_ROWS,0);
            GL11.glBindTexture(GL11.GL_TEXTURE_2D,texture);
            GL11.glTexSubImage2D(GL11.GL_TEXTURE_2D,0,0,0,width,height,GL11.GL_RGBA,GL11.GL_UNSIGNED_BYTE,sky);
            CubeonHudConfig.get().cameraMotionBlur=true;
            CameraBlurRenderer.reset(); CameraBlurRenderer.beginFrame();
            Method render=null;
            for(Method m:CameraBlurRenderer.class.getMethods()) if(m.getName().equals("render")) render=m;
            Object renderer=null;
            for(Field f:mc.getClass().getFields()) if(f.getType()==render.getParameterTypes()[0]) renderer=f.get(mc);
            Object camera=renderer.getClass().getMethod("method_19418").invoke(renderer);
            float yaw=(float)camera.getClass().getMethod("method_19330").invoke(camera);
            float pitch=(float)camera.getClass().getMethod("method_19329").invoke(camera);
            Object world=mc.getClass().getField("field_1687").get(mc);
            CameraBlur.INSTANCE.update(System.nanoTime()-16_000_000L,yaw-2,pitch,CameraBlurRenderer.fov,
                    (double)width/height,world,true);
            render.invoke(null,renderer);
            ByteBuffer result=ByteBuffer.allocateDirect(4);
            GL15.glBindBuffer(GL21.GL_PIXEL_PACK_BUFFER,0);
            GL11.glReadPixels(width/2,height/2,1,1,GL11.GL_RGBA,GL11.GL_UNSIGNED_BYTE,result);
            int r=result.get(0)&255,g=result.get(1)&255,b=result.get(2)&255,a=result.get(3)&255;
            if(Math.abs(r-37)>1 || Math.abs(g-126)>1 || Math.abs(b-220)>1 || a!=255)
                throw new AssertionError("Zero-alpha sky became "+r+","+g+","+b+","+a);
            CameraBlurRenderer.shutdown();
            System.out.println("CUBEON_263_NATIVE_PASS legacy real post-processing preserves zero-alpha sky RGB");
        } catch(Throwable error) {
            System.out.println("CUBEON_263_NATIVE_FAIL "+error); error.printStackTrace();
        } finally { mc.getClass().getMethod("method_1592").invoke(mc); }
    }
}
'''


def main():
    legacy = '--legacy-blur' in __import__('sys').argv
    version = '1.20' if legacy else '26.3'
    profile = 'fabric-loader-0.20.1-' + version
    java = Path('/usr/lib/jvm/java-17-openjdk/bin') if legacy else JAVA
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cubeon-263-native-') as temporary:
        work = Path(temporary)
        mods = work / 'mods'
        mods.mkdir()
        client = ROOT / f'assets/jars/cubeon-client-1.0.0+mc{version}.jar'
        api = (Path.home() / '.cubeon_launcher/mod_profiles/1.20-fabric/fabric-api-0.83.0+1.20.jar'
               if legacy else PROFILE / 'fabric-api-0.163.0+26.3.jar')
        for jar in [client, api]:
            shutil.copyfile(jar, mods / jar.name)
        # Optional renderer compatibility run includes the user's installed Sodium/Iris.
        if '--renderer-mods' in __import__('sys').argv:
            for pattern in ('sodium-*.jar', 'iris-*.jar'):
                for jar in PROFILE.glob(pattern):
                    shutil.copyfile(jar, mods / jar.name)
        world = GAME / f'instances/{profile}/saves/New World'
        shutil.copytree(world, work / 'saves/Client probe', ignore=shutil.ignore_patterns('session.lock'))
        source = work / 'ClientProbe.java'
        source.write_text(LEGACY_PROBE if legacy else PROBE)
        classes = work / 'classes'
        classes.mkdir()
        api_classes = work / 'api'
        api_classes.mkdir()
        with zipfile.ZipFile(api) as bundle:
            for name in bundle.namelist():
                if name.endswith('.jar'):
                    (api_classes / Path(name).name).write_bytes(bundle.read(name))
        cp = os.pathsep.join(map(str, [GAME / f'versions/{version}/{version}.jar', client,
                                      *sorted((GAME / 'libraries').rglob('*.jar')),
                                      *api_classes.glob('*.jar')]))
        subprocess.run([str(JAVA / 'javac'), '-proc:none', '--release', '17', '-cp', cp,
                        '-d', str(classes), str(source)], check=True, timeout=60)
        with zipfile.ZipFile(mods / 'client-probe.jar', 'w') as jar:
            for file in classes.rglob('*.class'):
                jar.write(file, file.relative_to(classes).as_posix())
            jar.writestr('fabric.mod.json', json.dumps({
                'schemaVersion': 1, 'id': 'client_probe', 'version': '1.0',
                'environment': 'client', 'entrypoints': {'client': ['probe.ClientProbe']}}))
        (work / 'options.txt').write_text('maxFps:60\nenableVsync:false\nonboardAccessibility:false\ninactivityFpsLimit:minimized\n')
        command = get_minecraft_command(profile, str(GAME), {
            'username': 'ClientProbe', 'uuid': '5f5e020167373e67b59baa2682e55583',
            'token': '0', 'executablePath': str(java / 'java'), 'gameDirectory': str(work),
            'jvmArguments': ['-Xmx1536M', '-Xms256M'],
            'launcherName': 'CubeonClientProbe', 'launcherVersion': '1'})
        command += ['--quickPlaySingleplayer', 'Client probe']
        env = dict(os.environ)
        for key in ('LIBGL_ALWAYS_SOFTWARE', 'MESA_LOADER_DRIVER_OVERRIDE', 'GALLIUM_DRIVER'):
            env.pop(key, None)
        log = OUT / ('legacy-blur.log' if legacy else 'renderer-mods.log' if '--renderer-mods' in __import__('sys').argv else 'native.log')
        with log.open('w') as output:
            process = subprocess.Popen(command, cwd=work, env=env, stdout=output, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 120
            typed = False
            try:
                while process.poll() is None and time.monotonic() < deadline:
                    text = log.read_text()
                    if not typed and 'CUBEON_263_SEARCH_READY' in text:
                        windows = subprocess.check_output(['xdotool', 'search', '--pid', str(process.pid)], text=True).split()
                        window = windows[-1]
                        subprocess.run(['xdotool', 'windowactivate', '--sync', window], check=True)
                        subprocess.run(['xdotool', 'type', '--clearmodifiers', '--delay', '150', 'blur'], check=True)
                        typed = True
                    time.sleep(.2)
                if process.poll() is None:
                    raise RuntimeError(f'Native probe timed out: {log}')
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=20)
        for crash in work.glob('hs_err_pid*.log'):
            shutil.copyfile(crash, OUT / crash.name)
        text = log.read_text()
        assert process.returncode == 0 and 'CUBEON_263_NATIVE_PASS' in text and 'CUBEON_263_NATIVE_FAIL' not in text, log
        print(next(line for line in text.splitlines() if 'CUBEON_263_NATIVE_PASS' in line))


if __name__ == '__main__':
    main()
