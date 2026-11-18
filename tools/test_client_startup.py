"""Exercise boot artwork and key migration; --native boots isolated cached Fabric 26.3."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "mod/src/main"
HARNESS = r'''
import com.cubeon.client.MenuKeyMigration;
import com.cubeon.client.ui.StartupUi;
import java.nio.file.*;
import java.util.*;
public class StartupTest {
    static void check(boolean ok,String why) { if(!ok) throw new AssertionError(why); }
    public static void main(String[] args) throws Exception {
        Path folder=Path.of(args[0]), options=folder.resolve("options.txt");
        MenuKeyMigration.migrate(folder.toFile());
        check(!Files.exists(options),"Missing options do not create a file");
        String original="guiScale:0\r\nkey_cubeon-client.open_menu:key.keyboard.k\r\nkey_other:key.keyboard.k\r\n";
        Files.writeString(options,original); MenuKeyMigration.migrate(folder.toFile());
        String migrated=Files.readString(options);
        check(migrated.equals(original.replace("open_menu:key.keyboard.k","open_menu:key.keyboard.right.shift")),"Only old menu default changes, preserving CRLF and GUI Auto");
        MenuKeyMigration.migrate(folder.toFile()); check(Files.readString(options).equals(migrated),"Migration is idempotent");
        for(String custom:List.of("key.keyboard.g","key.keyboard.unknown","key.mouse.4")) {
            Files.writeString(options,"key_cubeon-client.open_menu:"+custom+"\n");
            MenuKeyMigration.migrate(folder.toFile());
            check(Files.readString(options).equals("key_cubeon-client.open_menu:"+custom+"\n"),"Custom binding preserved");
        }
        check(StartupUi.opacity(0,-1)==1 && StartupUi.opacity(1000,0)==1,"Native loading and hold are fully visible");
        check(StartupUi.opacity(1500,0)==.5f && StartupUi.opacity(2000,0)==0,"Native fade timing preserved");
        for(int[] size:new int[][]{{32,48},{320,240},{480,320},{960,540}}) {
            List<int[]> quads=new ArrayList<>();
            StartupUi.Canvas canvas=(x0,y0,x1,y1,color)->{
                check(x0>=0&&y0>=0&&x1<=size[0]&&y1<=size[1]&&x0<=x1&&y0<=y1,"Boot artwork stays in bounds");
                quads.add(new int[]{x0,y0,x1,y1,color});
            };
            StartupUi.draw(canvas,size[0],size[1],.5f,1);
            check(quads.size()>32,"Real bundled logo decoded before resource packs");
            int[] track=quads.get(quads.size()-2), progress=quads.get(quads.size()-1);
            check(progress[0]==track[0]&&Math.abs((progress[2]-progress[0])*2-(track[2]-track[0]))<=1,"Bar tracks actual reload progress");
            quads.clear(); StartupUi.draw(canvas,size[0],size[1],Float.NaN,1);
            check((quads.get(quads.size()-1)[4]&0xFFFFFF)==0x293029,"Invalid progress stays empty");
            quads.clear(); StartupUi.draw(canvas,size[0],size[1],1,0);
            check(quads.isEmpty(),"Completed fade submits nothing");
        }
        System.out.println("Startup logo, progress, fade, bounds and safe key migration passed");
    }
}
'''


class StartupTests(unittest.TestCase):
    def test_production_artwork_and_migration(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "StartupTest.java"
            source.write_text(HARNESS)
            subprocess.run(["javac", "--release", "17", "-d", temporary,
                            str(MAIN / "java/com/cubeon/client/MenuKeyMigration.java"),
                            str(MAIN / "java/com/cubeon/client/ui/StartupUi.java"), str(source)],
                           check=True, capture_output=True, timeout=60)
            logo = folder / "assets/cubeon-client/textures/gui/startup-logo.png"
            logo.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "assets/icon_32.png", logo)
            result = subprocess.run(["java", "-cp", temporary, "StartupTest", temporary],
                                    check=True, capture_output=True, text=True, timeout=60)
            print(result.stdout.strip())

    def test_shipped_startup_assets_and_hooks(self):
        matrix = json.loads((ROOT / "mod/brackets.json").read_text())
        for bracket in matrix["brackets"]:
            with self.subTest(version=bracket["key"]):
                self.assertEqual(len([o for o in bracket["overlays"] if o.startswith("loading-")]), 1)
                with zipfile.ZipFile(ROOT / f"assets/jars/cubeon-client-1.0.0+mc{bracket['key']}.jar") as jar:
                    self.assertEqual(jar.read("assets/cubeon-client/textures/gui/startup-logo.png"),
                                     (ROOT / "assets/icon_32.png").read_bytes())
                    mixins = json.loads(jar.read("cubeon-client.mixins.json"))["client"]
                    self.assertIn("StartupLoadingMixin", mixins)
                    self.assertIn("GuiScaleDefaultMixin", mixins)


PROBE = r'''
package probe;
import com.cubeon.client.hud.screen.*;
import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.KeyMapping;
import java.lang.reflect.*;
public class StartupProbe implements ClientModInitializer {
    int stage,ticks;
    static void check(boolean ok,String why) { if(!ok) throw new AssertionError(why); }
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(mc -> {
            if(mc.gui.overlay()!=null || mc.gui.screen()==null) return;
            try {
                if(stage==0) {
                    check(mc.options.guiScale().get()==Integer.getInteger("probe.scale",2),"Saved/default GUI scale");
                    check(mc.options.cutoutLeaves().get()==Boolean.getBoolean("probe.leaves"),"Saved/default see-through leaves");
                    KeyMapping menu=KeyMapping.get("key.cubeon-client.open_menu");
                    check(menu!=null&&menu.getDefaultKey().getValue()==InputConstants.KEY_RSHIFT,"Right Shift default registered");
                    Field key=KeyMapping.class.getDeclaredField("key"); key.setAccessible(true);
                    check(((InputConstants.Key)key.get(menu)).getValue()==Integer.getInteger("probe.key",InputConstants.KEY_RSHIFT),"Actual loaded key binding");
                    // Saved choices survive a native reload of Options, too.
                    mc.options.guiScale().set(3); mc.options.cutoutLeaves().set(true); mc.options.save();
                    mc.options.guiScale().set(2); mc.options.cutoutLeaves().set(false); mc.options.load();
                    check(mc.options.guiScale().get()==3&&mc.options.cutoutLeaves().get(),"Player changes survive native save/load");
                    mc.options.guiScale().set(2);
                    mc.gui.setScreen(new CubeonHudMenuScreen());
                    System.out.println("CUBEON_NATIVE_MENU_READY"); stage=1;ticks=0;
                } else if(stage==1 && ++ticks>=60) {
                    mc.gui.setScreen(new FriendsChatScreen(mc.gui.screen()));
                    System.out.println("CUBEON_NATIVE_CHAT_READY");stage=2;ticks=0;
                } else if(stage==2 && ++ticks>=60) {
                    System.out.println("CUBEON_STARTUP_NATIVE_PASS");mc.stop();stage=3;
                }
            } catch(Throwable error) {
                System.out.println("CUBEON_STARTUP_NATIVE_FAIL "+error);error.printStackTrace();mc.stop();stage=3;
            }
        });
    }
}
'''
NATIVE_MIXIN = r'''
package probe.mixin;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.LoadingOverlay;
import org.spongepowered.asm.mixin.*;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(LoadingOverlay.class)
public abstract class LoadingProbe {
    @Shadow @Final private boolean fadeIn;
    @Unique private boolean probe$seen;
    @Inject(method="extractRenderState",at=@At("TAIL"),require=1)
    private void probe$startup(GuiGraphicsExtractor graphics,int x,int y,float delta,CallbackInfo ci) {
        if(!fadeIn&&!probe$seen) { probe$seen=true;System.out.println("CUBEON_NATIVE_STARTUP_FRAME"); }
    }
}
'''


def native(args):
    from minecraft_launcher_lib.command import get_minecraft_command
    from PIL import ImageGrab
    game = args.minecraft_dir
    api = args.fabric_api
    java = Path.home() / "jdks/jdk-25.0.4.1+1/bin"
    output = ROOT / "archive/ui-captures/client-pixel"
    output.mkdir(parents=True, exist_ok=True)
    display = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "1000x700x24", "-nolisten", "tcp"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    number = display.stdout.readline().strip()
    assert number.isdigit(), "Xvfb did not start"
    env = dict(os.environ, DISPLAY=":" + number, WAYLAND_DISPLAY="")
    try:
        with tempfile.TemporaryDirectory(prefix="cubeon-startup-native-") as temporary:
            base = Path(temporary)
            classes = base / "classes"
            classes.mkdir()
            api_classes = base / "api"
            api_classes.mkdir()
            with zipfile.ZipFile(api) as jar:
                for entry in jar.namelist():
                    if entry.endswith(".jar"):
                        (api_classes / Path(entry).name).write_bytes(jar.read(entry))
            client = ROOT / "assets/jars/cubeon-client-1.0.0+mc26.3.jar"
            cp = os.pathsep.join(map(str, [game / "versions/26.3/26.3.jar", client,
                                          *sorted((game / "libraries").rglob("*.jar")), *api_classes.glob("*.jar")]))
            sources = [base / "StartupProbe.java", base / "LoadingProbe.java"]
            sources[0].write_text(PROBE)
            sources[1].write_text(NATIVE_MIXIN)
            subprocess.run([str(java / "javac"), "-proc:none", "--release", "17", "-cp", cp,
                            "-d", str(classes), *map(str, sources)], check=True, timeout=60)
            probe = base / "startup-probe.jar"
            with zipfile.ZipFile(probe, "w") as jar:
                for file in classes.rglob("*.class"):
                    jar.write(file, file.relative_to(classes).as_posix())
                jar.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "startup_probe", "version": "1",
                              "environment": "client", "entrypoints": {"client": ["probe.StartupProbe"]},
                              "mixins": ["startup-probe.mixins.json"]}))
                jar.writestr("startup-probe.mixins.json", json.dumps({"required": True, "package": "probe.mixin",
                              "compatibilityLevel": "JAVA_17", "client": ["LoadingProbe"]}))
            cases = [("defaults", "key_cubeon-client.open_menu:key.keyboard.k\n", 2, False, None),
                     ("saved-auto", "guiScale:0\ncutoutLeaves:true\nkey_cubeon-client.open_menu:key.keyboard.g\n", 0, True, 10),
                     ("saved-scale", "guiScale:3\ncutoutLeaves:false\n", 3, False, None)]
            for name, saved, scale, leaves, key in cases:
                work = base / name
                mods = work / "mods"
                mods.mkdir(parents=True)
                for source in (client, api, probe):
                    shutil.copyfile(source, mods / source.name)
                sodium = Path.home() / ".cubeon_minecraft/cache/downloads/mods/sodium-fabric-0.9.3-beta.5+mc26.3.jar"
                if sodium.is_file():
                    shutil.copyfile(sodium, mods / sodium.name)
                (work / "options.txt").write_text(saved + "maxFps:60\nenableVsync:false\nonboardAccessibility:false\n")
                flags = ["-Xmx1536M", "-Xms256M", f"-Dprobe.scale={scale}", f"-Dprobe.leaves={str(leaves).lower()}"]
                if key is not None:
                    flags.append(f"-Dprobe.key={key}")
                command = get_minecraft_command("fabric-loader-0.20.1-26.3", str(game), {
                    "username": "StartupProbe", "uuid": "5f5e020167373e67b59baa2682e55583", "token": "0",
                    "executablePath": str(java / "java"), "gameDirectory": str(work), "jvmArguments": flags,
                    "customResolution": True, "resolutionWidth": "960", "resolutionHeight": "640"})
                log = output / f"{name}.log"
                with log.open("w") as stream:
                    process = subprocess.Popen(command, cwd=work, env=env, stdout=stream, stderr=subprocess.STDOUT)
                    deadline = time.monotonic() + 90
                    seen = set()
                    try:
                        while process.poll() is None and time.monotonic() < deadline:
                            content = log.read_text(errors="replace")
                            if name == "defaults":
                                for marker, image_name in [("CUBEON_NATIVE_STARTUP_FRAME", "startup"),
                                                           ("CUBEON_NATIVE_MENU_READY", "menu"),
                                                           ("CUBEON_NATIVE_CHAT_READY", "chat")]:
                                    if marker in content and marker not in seen:
                                        # Give menu extraction one frame; startup already has a native frame.
                                        if image_name != "startup":
                                            time.sleep(.25)
                                        ImageGrab.grab(xdisplay=env["DISPLAY"]).save(output / f"{image_name}.png")
                                        seen.add(marker)
                            time.sleep(.1)
                        assert process.poll() is not None, f"Native probe timed out: {log}"
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=10)
                content = log.read_text(errors="replace")
                assert process.returncode == 0 and "CUBEON_STARTUP_NATIVE_PASS" in content, f"Native probe failed: {log}"
                assert "CUBEON_NATIVE_STARTUP_FRAME" in content, f"No real startup frame: {log}"
                print(f"{name}: real Fabric + Sodium defaults, saved options, Right Shift, startup, menu and chat passed", flush=True)
    finally:
        display.terminate()
        display.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--minecraft-dir", type=Path, default=Path.home() / ".cubeon_minecraft/instances/.runtime")
    parser.add_argument("--fabric-api", type=Path, default=Path.home() / ".cubeon_minecraft/instances/26.3-Fabric/minecraft/mods/fabric-api-0.166.2+26.3.jar")
    args, rest = parser.parse_known_args()
    if args.native:
        native(args)
    else:
        unittest.main(argv=[__file__, *rest])
