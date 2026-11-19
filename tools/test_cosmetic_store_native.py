"""Load installed store wings/textures in an isolated cached Fabric game.

Requires the selected game's runtime, Fabric API, New World and a desktop.
Copies the world; never changes user options, installed mods or player data.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from minecraft_launcher_lib.command import get_minecraft_command
from cubeon import cosmetic_packages, cosmetics, packformat, storage
from cubeon.launch import _normalize_inherited_client_jar

ROOT = Path(__file__).resolve().parents[1]
GAME = Path.home() / ".cubeon_minecraft"
RUNTIME = Path(storage.runtime_dir(str(GAME)))
JAVA = Path.home() / "jdks/jdk-25.0.4.1+1/bin"
OUT = ROOT / "build/store-native-verification"

PROBE = r'''
package probe;
import com.cubeon.client.Json;
import com.cubeon.client.cosmetics.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.io.*;
import java.util.*;
import net.fabricmc.api.ClientModInitializer;

public class StoreProbe implements ClientModInitializer {
    Map<String,Object> names;
    boolean finished;
    int ticks,checks;
    String name(String key) { return (String)names.get(key); }
    Object call(Object owner,String key) throws Exception {
        return owner.getClass().getMethod(name(key)).invoke(owner);
    }
    void check(boolean ok,String message) { checks++; if(!ok) throw new AssertionError(message); }
    public void onInitializeClient() {
        try {
            names=Json.parseObject(Files.readString(Path.of(System.getProperty("cubeon.probe.names"))));
            Class<?> ticks=Class.forName("net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents");
            Class<?> callback=Class.forName(ticks.getName()+"$EndTick");
            Object event=ticks.getField("END_CLIENT_TICK").get(null);
            Object listener=Proxy.newProxyInstance(callback.getClassLoader(),new Class[]{callback},(proxy,method,args)-> {
                if(method.getName().equals("onEndTick")) tick(args[0]);
                return null;
            });
            Class.forName("net.fabricmc.fabric.api.event.Event").getMethod("register",Object.class).invoke(event,listener);
        } catch(Exception error) { throw new RuntimeException(error); }
    }
    void tick(Object client) {
        if(finished) return;
        try {
            if(client.getClass().getField(name("player")).get(client)==null || ++ticks<30) return;
            finished=true;
            Object packs=call(client,"packs");
            check(((Collection<?>)call(packs,"enabled")).contains("file/cubeon-store"),"Minecraft retained the store pack");
            for(Object profile:(Collection<?>)call(packs,"profiles")) {
                if(call(profile,"id").equals("file/cubeon-store"))
                    check((Boolean)call(call(profile,"compatibility"),"compatible"),"Minecraft accepts the pack format");
            }
            Object resources=call(client,"resources"),textures=call(client,"textures");
            Class<?> identifier=Class.forName(name("identifier"));
            Method of=identifier.getMethod(name("of"),String.class,String.class);
            var catalog=CosmeticCatalog.get();
            check(catalog!=null,"Real client loaded the catalog");
            for(Object raw:(List<?>)names.get("models")) {
                Map<?,?> expected=(Map<?,?>)raw;
                var item=catalog.get((String)expected.get("id"));
                check(item!=null && item.wingFlare,"Real catalog loaded each full wing model");
                check(CosmeticElytra.ready(item),"Real resource pack qualifies downloaded wings for Elytra replacement");
                CosmeticElytra.begin(client); CosmeticElytra.drawn(item);
                check(CosmeticElytra.consume(client),"Downloaded wings mark the same replacement pass as bundled wings");
                check(item.boxes.stream().allMatch(box -> box.pivotX==2 && box.pivotY==2 && box.pivotZ==2.25f),
                    "Downloaded collection uses the built-in Giant wing hinges");
                for(Object rawTexture:(List<?>)expected.get("textures")) {
                    Map<?,?> expectedTexture=(Map<?,?>)rawTexture;
                    String filename=(String)expectedTexture.get("name");
                    Object id=of.invoke(null,"cubeon-client","textures/cosmetics/"+filename);
                    Optional<?> found=(Optional<?>)resources.getClass().getMethod(name("resource"),identifier).invoke(resources,id);
                    check(found.isPresent(),"Resource manager found "+filename);
                    Object resource=found.get();
                    check(call(resource,"packId").equals("file/cubeon-store"),"Texture comes from the downloaded pack");
                    try(InputStream input=(InputStream)call(resource,"input")) {
                        check(input.readNBytes(8)[0]==(byte)137,"PNG resource decodes from the actual game pack");
                    }
                    Object texture=textures.getClass().getMethod(name("texture"),identifier).invoke(textures,id);
                    Object gpu=call(texture,"gpu");
                    int width=(Integer)gpu.getClass().getMethod("getWidth",int.class).invoke(gpu,0);
                    int height=(Integer)gpu.getClass().getMethod("getHeight",int.class).invoke(gpu,0);
                    check(width==((Number)expectedTexture.get("width")).intValue()
                        && height==((Number)expectedTexture.get("height")).intValue(),"GPU loaded the atlas, not the missing-texture image");
                }
            }
            System.out.println("CUBEON_STORE_NATIVE_PASS "+checks+" checks; compatible pack and real base/glow GPU textures");
        } catch(Throwable error) {
            finished=true; System.out.println("CUBEON_STORE_NATIVE_FAIL "+error); error.printStackTrace();
        } finally {
            if(finished) try { call(client,"stop"); } catch(Exception error) { throw new RuntimeException(error); }
        }
    }
}
'''


def names_for(version):
    if version.startswith("26."):
        return dict(player="player", packs="getResourcePackRepository", enabled="getSelectedIds",
                    profiles="getSelectedPacks", id="getId", compatibility="getCompatibility", compatible="isCompatible",
                    resources="getResourceManager", textures="getTextureManager", identifier="net.minecraft.resources.Identifier",
                    of="fromNamespaceAndPath", resource="getResource", packId="sourcePackId", input="open",
                    texture="getTexture", gpu="getTexture", stop="stop")
    mapping = next((Path.home() / ".gradle/caches/fabric-loom" / version).glob("net.fabricmc.yarn*/mappings.tiny"))
    wanted = {
        "net/minecraft/client/MinecraftClient": dict(player="player", getResourcePackManager="packs", getResourceManager="resources",
            getTextureManager="textures", scheduleStop="stop"),
        "net/minecraft/resource/ResourcePackManager": dict(getEnabledIds="enabled", getEnabledProfiles="profiles"),
        "net/minecraft/resource/ResourcePackProfile": dict(getId="id", getCompatibility="compatibility"),
        "net/minecraft/resource/ResourcePackCompatibility": dict(isCompatible="compatible"),
        "net/minecraft/util/Identifier": dict(of="of"),
        "net/minecraft/resource/ResourceFactory": dict(getResource="resource"),
        "net/minecraft/resource/Resource": dict(getPackId="packId", getInputStream="input"),
        "net/minecraft/client/texture/TextureManager": dict(getTexture="texture"),
        "net/minecraft/client/texture/AbstractTexture": dict(getGlTexture="gpu")}
    result, owner = {}, None
    for line in mapping.read_text().splitlines():
        columns = line.split("\t")
        if columns[0] == "c":
            owner = columns[-1]
            if owner == "net/minecraft/util/Identifier": result["identifier"] = columns[-2].replace("/", ".")
        elif len(columns) > 4 and columns[1] in ("m", "f") and columns[-1] in wanted.get(owner, {}):
            result[wanted[owner][columns[-1]]] = columns[-2]
    return result


def verify(version):
    loader = next((RUNTIME / "versions").glob(f"fabric-loader-*-{version}")).name
    profile = Path(storage.game_dir(loader))
    api = next((profile / "mods").glob("fabric-api-*.jar"))
    client = ROOT / "assets/jars" / f"cubeon-client-1.0.0+mc{version}.jar"
    items = [item for item in cosmetic_packages.installed_items() if item.get("wing_flare") and item["slot"] == "back"]
    assert items, "Download a store wing before running the native probe"
    with tempfile.TemporaryDirectory(prefix=f"cubeon-store-native-{version}-") as temporary:
        work = Path(temporary)
        (work / "mods").mkdir()
        for artifact in (client, api): shutil.copyfile(artifact, work / "mods" / artifact.name)
        shutil.copytree(profile / "saves/New World", work / "saves/Store probe", ignore=shutil.ignore_patterns("session.lock"))
        (work / "options.txt").write_text("maxFps:60\nenableVsync:false\nonboardAccessibility:false\n")
        all_models = []
        staged_textures = work / "staged-textures"
        staged_textures.mkdir()
        textures = work / "resourcepacks/cubeon-store/assets/cubeon-client/textures/cosmetics"
        for item in items:
            cosmetics.sync_to_game(dict(last_version=loader, active_back_item=item["id"]), str(work), strict=True,
                                    mc_version=version, version_id=loader)
            all_models.extend(json.loads((work / "config/cubeon-store.json").read_text())["items"])
            # Normal sync prunes unequipped textures; this probe loads every
            # wing at once to audit the entire installed collection.
            for texture in textures.glob("*.png"):
                shutil.copyfile(texture, staged_textures / texture.name)
        for texture in staged_textures.glob("*.png"):
            shutil.copyfile(texture, textures / texture.name)
        (work / "config/cubeon-store.json").write_text(json.dumps(dict(items=all_models, anchors=cosmetics.ANCHORS)))
        expected = []
        for item in all_models:
            entries = []
            for name in (item["texture"], item.get("emissive_texture")):
                if name:
                    with Image.open(textures / name) as image:
                        entries.append(dict(name=name, width=image.width, height=image.height))
            expected.append(dict(id=item["id"], textures=entries))
        names = work / "names.json"
        names.write_text(json.dumps({**names_for(version), "models": expected}))
        source = work / "StoreProbe.java"; source.write_text(PROBE)
        classes = work / "classes"; classes.mkdir()
        cp = os.pathsep.join(map(str, [client, *sorted((RUNTIME / "libraries/net/fabricmc/fabric-loader").rglob("*.jar"))]))
        subprocess.run([str(JAVA / "javac"), "-proc:none", "--release", "17", "-cp", cp, "-d", str(classes), str(source)], check=True, timeout=60)
        with zipfile.ZipFile(work / "mods/store-probe.jar", "w") as jar:
            for file in classes.rglob("*.class"): jar.write(file, file.relative_to(classes).as_posix())
            jar.writestr("fabric.mod.json", json.dumps(dict(schemaVersion=1, id="store_probe", version="1.0",
                environment="client", entrypoints={"client": ["probe.StoreProbe"]})))
        command = get_minecraft_command(loader, str(RUNTIME), dict(username="StoreProbe",
            uuid="5f5e020167373e67b59baa2682e55583", token="0", executablePath=str(JAVA / "java"), gameDirectory=str(work),
            jvmArguments=["-Xmx1536M", "-Xms256M", f"-Dcubeon.probe.names={names}"], launcherName="CubeonStoreProbe", launcherVersion="1"))
        command = _normalize_inherited_client_jar(command, loader) + ["--quickPlaySingleplayer", "Store probe"]
        OUT.mkdir(parents=True, exist_ok=True)
        log = OUT / f"{version}.log"
        with log.open("w") as output:
            process = subprocess.Popen(command, cwd=work, stdout=output, stderr=subprocess.STDOUT)
            try: result = process.wait(timeout=150)
            except subprocess.TimeoutExpired:
                process.terminate(); process.wait(timeout=15)
                raise RuntimeError(f"Owned native probe timed out: {log}")
        text = log.read_text()
        assert result == 0 and "CUBEON_STORE_NATIVE_PASS" in text and "CUBEON_STORE_NATIVE_FAIL" not in text, log
        print(version, next(line for line in text.splitlines() if "CUBEON_STORE_NATIVE_PASS" in line))
        assert "Removed resource pack file/cubeon-store" not in text, log
        print(f"Verified {len(items)} store wings with resource format {packformat.resource_format_for(version, loader)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("versions", nargs="*", default=["1.21.11"])
    for version in parser.parse_args().versions: verify(version)
