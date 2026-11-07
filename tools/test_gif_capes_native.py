"""Verify GIF cape GPU uploads and cleanup in isolated cached Fabric Minecraft 26.3.

Requires a graphical desktop, installed Fabric 26.3 and JDK 25. Uses a temporary
game directory, never edits player worlds or instance profiles, and exits itself.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

from PIL import Image
from minecraft_launcher_lib.command import get_minecraft_command

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon import paths
from cubeon.storage import runtime_dir
GAME = Path(runtime_dir())
PROFILE = Path(paths.game_dir_for("fabric-loader-0.20.1-26.3", create=False)) / "mods"
JAVA = Path.home() / "jdks/jdk-25.0.4.1+1/bin"
MAPPED = Path.home() / ".gradle/caches/fabric-loom/minecraftMaven/net/minecraft"
OUT = ROOT / "archive/ui-captures/gif-capes-native"

PROBE = r'''
package probe;
import com.cubeon.client.Json;
import com.cubeon.client.skins.*;
import com.mojang.blaze3d.platform.NativeImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.texture.DynamicTexture;

public final class GifCapeProbe implements ClientModInitializer {
 boolean finished;
 CompletableFuture<Void> loading;
 static int checks;
 static void check(boolean ok,String why) { checks++; if(!ok) throw new AssertionError(why); }
 public void onInitializeClient() {
  ClientTickEvents.END_CLIENT_TICK.register(mc -> {
   if(finished || !mc.isGameLoadFinished()) return;
   if(loading==null) {
    loading=CompletableFuture.runAsync(()->{
     try { CapeAnimation.accept(Json.parseObject(Files.readString(Path.of("cape.json")))); }
     catch(Exception error) { throw new CompletionException(error); }
    });
    return;
   }
   if(!loading.isDone()) return;
   finished=true;
   try {
    loading.join();verify(mc);
    System.out.println("CUBEON_GIF_NATIVE_PASS "+checks+" checks; real GPU animation, HD switches and cleanup");
   } catch(Throwable error) {
    System.out.println("CUBEON_GIF_NATIVE_FAIL "+error);error.printStackTrace();
   } finally { mc.stop(); }
  });
 }
 static void forceFrame(int index) throws Exception {
  var applied=CapeAnimation.get();
  long offset=switch(index) {case 0->100;case 1->600;default->1600;};
  var field=CapeAnimation.class.getDeclaredField("applied");field.setAccessible(true);
  field.set(null,new CapeAnimation.Applied(applied.png(),false,applied.revision(),applied.frames(),
   System.nanoTime()-offset*1_000_000L,applied.id()));
 }
 static DynamicTexture current(Minecraft mc) {
  var id=LiveCapeTexture.texture();check(id!=null,"Cape uploads successfully on real game GPU");
  var texture=mc.getTextureManager().getTexture(id);
  check(texture instanceof DynamicTexture,"Texture manager owns selected dynamic cape");
  return (DynamicTexture)texture;
 }
 static void verify(Minecraft mc) throws Exception {
  check(CapeAnimation.get()!=null && CapeAnimation.get().frames()!=null,"Background startup decoded GIF");
  forceFrame(0);var texture=current(mc);var previous=texture.getPixels();
  check(previous.getWidth()==128 && previous.getHeight()==64,"Initial cape GPU dimensions");
  int color=previous.getPixel(5,5);
  for(int i=1;i<16;i++) {
   forceFrame(i%3);var next=current(mc);
   check(next==texture,"Animation retains one GPU registration");
   check(previous.isClosed(),"Previous native frame is released");
   previous=next.getPixels();
   check(previous.getPixel(5,5)!=color,"Displayed frame pixels change");
   color=previous.getPixel(5,5);
  }
  byte[] hd=Files.readAllBytes(Path.of("hd.png"));
  CapeAnimation.apply(hd,false,null,"hd");var larger=current(mc);
  check(larger!=texture && previous.isClosed(),"HD selection releases the old cape allocation");
  check(larger.getPixels().getWidth()==1024,"Switch to HD reallocates before upload");
  var hdPixels=larger.getPixels();
  byte[] small=Files.readAllBytes(Path.of("small.png"));
  CapeAnimation.apply(small,false,null,"small");var smaller=current(mc);
  check(hdPixels.isClosed() && smaller.getPixels().getWidth()==64,"HD to vanilla switch releases native memory");
  var last=smaller.getPixels();
  CapeAnimation.apply(small,true,null,"__none__");
  check(LiveCapeTexture.texture()==null && last.isClosed(),"Hide destroys the owned texture");
  CapeAnimation.apply(small,false,null,"restored");var restored=current(mc);last=restored.getPixels();
  CapeAnimation.accept(Map.of("ok",true,"enabled",false,"revision","disabled"));
  check(LiveCapeTexture.texture()==null && last.isClosed(),"Disable destroys the owned texture");
  check(LiveCapeTexture.texture()==null,"Repeated cleanup is safe");
 }
}
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cubeon-gif-native-") as temporary:
        work = Path(temporary)
        mods = work / "mods"
        mods.mkdir()
        client = ROOT / "assets/jars/cubeon-client-1.0.0+mc26.3.jar"
        api = PROFILE / "fabric-api-0.163.0+26.3.jar"
        shutil.copyfile(client, mods / client.name)
        shutil.copyfile(api, mods / api.name)
        atlas = Image.new("RGBA", (128, 192))
        for index, color in enumerate(("red", "green", "blue")):
            atlas.paste(color, (0, index*64, 128, (index+1)*64))
        atlas.save(work / "atlas.png")
        atlas.crop((0, 0, 128, 64)).save(work / "cape.png")
        Image.new("RGBA", (1024, 512), "yellow").save(work / "hd.png")
        Image.new("RGBA", (64, 32), "cyan").save(work / "small.png")
        (work / "cape.json").write_text(json.dumps({"ok": True, "enabled": True, "revision": "native",
            "applied": {"id": "probe", "texture_path": str(work / "cape.png"), "hidden": False,
                        "animation": {"schema": 1, "count": 3, "width": 128, "height": 64,
                                      "durations": [400, 1000, 2000], "loop": 0,
                                      "path": str(work / "atlas.png"), "key": "native"}}}))
        source = work / "GifCapeProbe.java"
        source.write_text(PROBE)
        classes = work / "classes"
        classes.mkdir()
        api_classes = work / "api"
        api_classes.mkdir()
        with zipfile.ZipFile(api) as bundle:
            for name in bundle.namelist():
                if name.endswith(".jar"):
                    (api_classes / Path(name).name).write_bytes(bundle.read(name))
        mapped = [MAPPED / "minecraft-clientonly-deobf/26.3/minecraft-clientonly-deobf-26.3.jar",
                  MAPPED / "minecraft-common-deobf/26.3/minecraft-common-deobf-26.3.jar"]
        cp = os.pathsep.join(map(str, [*mapped, client, *sorted((GAME / "libraries").rglob("*.jar")),
                                      *api_classes.glob("*.jar")]))
        compiled = subprocess.run([str(JAVA / "javac"), "-proc:none", "--release", "17", "-cp", cp,
                                   "-d", str(classes), str(source)], timeout=60)
        if compiled.returncode:
            raise RuntimeError("GIF cape native probe did not compile; inspect javac output above.")
        with zipfile.ZipFile(mods / "gif-cape-probe.jar", "w") as jar:
            for file in classes.rglob("*.class"):
                jar.write(file, file.relative_to(classes).as_posix())
            jar.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "gif_cape_probe", "version": "1.0",
                "environment": "client", "entrypoints": {"client": ["probe.GifCapeProbe"]}}))
        (work / "options.txt").write_text("maxFps:60\nenableVsync:false\nonboardAccessibility:false\n")
        command = get_minecraft_command("fabric-loader-0.20.1-26.3", str(GAME), {
            "username": "GifCapeProbe", "uuid": "5f5e020167373e67b59baa2682e55583", "token": "0",
            "executablePath": str(JAVA / "java"), "gameDirectory": str(work),
            "jvmArguments": ["-Xmx1536M", "-Xms256M"], "launcherName": "CubeonGifCapeProbe", "launcherVersion": "1"})
        env = dict(os.environ)
        for key in ("LIBGL_ALWAYS_SOFTWARE", "MESA_LOADER_DRIVER_OVERRIDE", "GALLIUM_DRIVER"):
            env.pop(key, None)
        log = OUT / "startup.log"
        with log.open("w") as output:
            process = subprocess.Popen(command, cwd=work, env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                result = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=15)
                raise RuntimeError(f"Owned GIF cape probe timed out; inspect {log}")
        text = log.read_text()
        assert result == 0 and "CUBEON_GIF_NATIVE_PASS" in text and "CUBEON_GIF_NATIVE_FAIL" not in text, log
        print(next(line for line in text.splitlines() if "CUBEON_GIF_NATIVE_PASS" in line))


if __name__ == "__main__":
    main()
