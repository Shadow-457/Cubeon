"""Load store models and verify fitted skin copies in an isolated Fabric game.

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
import com.cubeon.client.skins.*;
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
    Object body(Object player) throws Exception { return call(call(player,"skin"),"body"); }
    Object image(Object textures,Object id,Class<?> identifier) throws Exception {
        return call(textures.getClass().getMethod(name("texture"),identifier).invoke(textures,id),"image");
    }
    int color(Object image,int x,int y) throws Exception {
        return (Integer)image.getClass().getMethod(name("color"),int.class,int.class).invoke(image,x,y);
    }
    int polygons(Object mesh) throws Exception {
        int result=0;
        for(Class<?> type=mesh.getClass();type!=null;type=type.getSuperclass()) {
            for(Field field:type.getDeclaredFields()) {
                if(field.getName().equals("polygonAmount")) { field.setAccessible(true); result+=field.getInt(mesh); }
                if(field.getName().equals("cubes")) { field.setAccessible(true); result+=6*((List<?>)field.get(mesh)).size(); }
            }
        }
        return result;
    }
    int[] meshes(Object player,Object texture) throws Exception {
        if(!Boolean.TRUE.equals(names.get("skinlayers"))) return null;
        var settings=Class.forName("dev.tr7zw.skinlayers.accessor.PlayerSettings");
        Method setup=Arrays.stream(Class.forName("dev.tr7zw.skinlayers.SkinUtil").getMethods())
            .filter(method->method.getName().equals("setup3dLayers")&&method.getParameterCount()==3).findFirst().orElseThrow();
        check((Boolean)setup.invoke(null,player,player,false),"3D Skin Layers builds the real player mesh");
        check(settings.getMethod("getCurrentSkin").invoke(player).equals(texture),"3D Skin Layers uses the current fitted texture");
        var data=Class.forName("dev.tr7zw.skinlayers.api.PlayerData");
        int[] counts=new int[6];int index=0;
        for(String part:List.of("Head","Torso","RightArm","LeftArm","RightLeg","LeftLeg"))
            counts[index++]=polygons(data.getMethod("get"+part+"Mesh").invoke(player));
        return counts;
    }
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
                check(item!=null,"Real catalog loaded the downloaded model");
                if("back".equals(item.slot)) {
                    check(item.wingFlare,"Real catalog loaded the full wing model");
                    check(CosmeticElytra.ready(item),"Real resource pack qualifies downloaded wings for Elytra replacement");
                    CosmeticElytra.begin(client); CosmeticElytra.drawn(item);
                    check(CosmeticElytra.consume(client),"Downloaded wings mark the same replacement pass as bundled wings");
                    check(item.boxes.stream().allMatch(box -> box.pivotX==2 && box.pivotY==2 && box.pivotZ==2.25f),
                        "Downloaded collection uses the built-in Giant wing hinges");
                }
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
            Object player=client.getClass().getField(name("player")).get(client);
            Class<?> parts=Class.forName(name("playerParts"));
            Object hat=parts.getField(name("hatPart")).get(null);
            Object jacket=parts.getField(name("jacketPart")).get(null);
            Method visible=player.getClass().getMethod(name("partVisible"),parts);
            check((Boolean)visible.invoke(player,hat),"Horns preserve the actual game outer head layer");
            check((Boolean)visible.invoke(player,jacket),"Uncovered jacket layers remain visible");
            var aura=catalog.get("aura_butterfly");
            check(aura!=null && aura.emissiveTexture!=null && aura.boxes.size()<=48,"Lightweight glowing butterfly aura loaded");
            Path selection=net.fabricmc.loader.api.FabricLoader.getInstance().getConfigDir().resolve(CosmeticSelection.FILE_NAME);
            Files.writeString(selection,"{\"aura\":\"aura_butterfly\"}"); CosmeticSelection.bind(selection);
            check((Boolean)visible.invoke(player,hat),"Removing the wearable restores the player's original layer setting");
            var sheet=new java.awt.image.BufferedImage(64,64,java.awt.image.BufferedImage.TYPE_INT_ARGB);
            for(int y=0;y<64;y++)for(int x=0;x<64;x++)sheet.setRGB(x,y,0xFF000000|x*3<<16|y*3<<8|90);
            var bytes=new ByteArrayOutputStream();javax.imageio.ImageIO.write(sheet,"png",bytes);
            LiveSkin.apply(new SkinLibrary.Skin("probe","Probe",false,"classic",bytes.toByteArray(),
                sheet.getRGB(0,0,64,64,null,0,64),64,64,false,bytes.toByteArray(),null,null,null));
            Object source=Class.forName("com.cubeon.client.skins.LiveSkinTexture").getMethod("texture").invoke(null);
            check(call(body(player),"location").equals(source),"Unequipped body uses the original live skin");
            Object originalImage=image(textures,source,identifier);
            int[] originalMeshes=meshes(player,source);
            for(Object raw:(List<?>)names.get("wearables")) {
                Map<?,?> sample=(Map<?,?>)raw;
                String slot=(String)sample.get("slot"),id=(String)sample.get("id");
                Files.writeString(selection,Json.object(slot,id));CosmeticSelection.bind(selection);
                Object output=call(body(player),"location");
                Set<Integer> covered=new HashSet<>();
                for(Object texel:(List<?>)sample.get("pixels"))covered.add(((Number)texel).intValue());
                check(output.equals(source)==covered.isEmpty(),"Only fitted texels create a display texture: "+id);
                Object fittedImage=image(textures,output,identifier);
                boolean exact=true,unchanged=true;
                for(int y=0;y<64;y++)for(int x=0;x<64;x++) {
                    int original=sheet.getRGB(x,y),actual=color(fittedImage,x,y);
                    exact &= covered.contains(y*64+x)?actual>>>24==0:actual==original;
                    unchanged &= color(originalImage,x,y)==original;
                }
                check(exact,"Only covered outer texels change in Minecraft: "+id);
                check(unchanged,"The original skin and its colors remain intact: "+id);
                check(call(body(player),"location").equals(output),"Unchanged frames reuse the fitted texture: "+id);
                int[] fittedMeshes=meshes(player,output);
                if(fittedMeshes!=null) {
                    if("head".equals(slot)&&covered.size()<384)check(fittedMeshes[0]>0,"Exposed hair retains its 3D mesh: "+id);
                    check(fittedMeshes[1]==originalMeshes[1],"Uncovered 3D jacket remains intact: "+id);
                    check(fittedMeshes[2]==originalMeshes[2]&&fittedMeshes[3]==originalMeshes[3],"Uncovered 3D sleeves remain intact: "+id);
                    if("feet".equals(slot))check(fittedMeshes[4]>0&&fittedMeshes[5]>0,"Trousers above the shoes remain 3D");
                }
                Files.writeString(selection,"{}");CosmeticSelection.bind(selection);
                check(call(body(player),"location").equals(source),"Unequip restores the original texture: "+id);
                if(originalMeshes!=null)check(Arrays.equals(originalMeshes,meshes(player,source)),"Unequip restores all 3D meshes: "+id);
            }
            Field cache=CosmeticSkinTexture.class.getDeclaredField("CACHE");cache.setAccessible(true);
            check(((Map<?,?>)cache.get(null)).isEmpty(),"Unequipping releases all fitted display textures");
            System.out.println("CUBEON_STORE_NATIVE_PASS "+checks+" checks; compatible pack, GPU textures, precise skin coverage, preserved 3D meshes and restoration");
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
                    texture="getTexture", gpu="getTexture", stop="stop",skin="getSkin",body="body",location="texturePath",
                    image="getPixels",color="getPixel",
                    playerParts="net.minecraft.world.entity.player.PlayerModelPart",hatPart="HAT",jacketPart="JACKET",partVisible="isModelPartShown")
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
        "net/minecraft/client/texture/AbstractTexture": dict(getGlTexture="gpu"),
        "net/minecraft/client/network/ClientPlayerLikeEntity": dict(getSkin="skin"),
        "net/minecraft/entity/player/SkinTextures": dict(body="body"),
        "net/minecraft/util/AssetInfo$TextureAssetInfo": dict(texturePath="location"),
        "net/minecraft/client/texture/NativeImageBackedTexture": dict(getImage="image"),
        "net/minecraft/client/texture/NativeImage": dict(getColorArgb="color"),
        "net/minecraft/entity/PlayerLikeEntity": dict(isModelPartVisible="partVisible"),
        "net/minecraft/entity/player/PlayerModelPart": dict(HAT="hatPart",JACKET="jacketPart")}
    result, owner = {}, None
    for line in mapping.read_text().splitlines():
        columns = line.split("\t")
        if columns[0] == "c":
            owner = columns[-1]
            if owner == "net/minecraft/util/Identifier": result["identifier"] = columns[-2].replace("/", ".")
            if owner == "net/minecraft/entity/player/PlayerModelPart": result["playerParts"] = columns[-2].replace("/", ".")
        elif len(columns) > 4 and columns[1] in ("m", "f") and columns[-1] in wanted.get(owner, {}):
            result[wanted[owner][columns[-1]]] = columns[-2]
    return result


def verify(version):
    loader = next((RUNTIME / "versions").glob(f"fabric-loader-*-{version}")).name
    profile = Path(storage.game_dir(loader))
    api = next((profile / "mods").glob("fabric-api-*.jar"))
    client = ROOT / "assets/jars" / f"cubeon-client-1.0.0+mc{version}.jar"
    items = [item for item in cosmetic_packages.installed_items()
             if item["slot"] in ("head", "feet") or item.get("wing_flare") and item["slot"] == "back"]
    assert items, "Download a store wing before running the native probe"
    with tempfile.TemporaryDirectory(prefix=f"cubeon-store-native-{version}-") as temporary:
        work = Path(temporary)
        (work / "mods").mkdir()
        for artifact in (client, api): shutil.copyfile(artifact, work / "mods" / artifact.name)
        skinlayers = next((GAME / "cache/downloads/mods").glob(f"skinlayers3d-fabric-*-mc{version}.jar"), None)
        if skinlayers: shutil.copyfile(skinlayers, work / "mods" / skinlayers.name)
        shutil.copytree(profile / "saves/New World", work / "saves/Store probe", ignore=shutil.ignore_patterns("session.lock"))
        (work / "options.txt").write_text("maxFps:60\nenableVsync:false\nonboardAccessibility:false\n")
        all_models = []
        staged_textures = work / "staged-textures"
        staged_textures.mkdir()
        textures = work / "resourcepacks/cubeon-store/assets/cubeon-client/textures/cosmetics"
        for item in items:
            cosmetics.sync_to_game(dict(last_version=loader, **{f"active_{item['slot']}_item": item["id"]}), str(work), strict=True,
                                    mc_version=version, version_id=loader)
            all_models.extend(json.loads((work / "config/cubeon-store.json").read_text())["items"])
            # Normal sync prunes unequipped textures; this probe loads every
            # wing at once to audit the entire installed collection.
            for texture in textures.glob("*.png"):
                shutil.copyfile(texture, staged_textures / texture.name)
        for texture in staged_textures.glob("*.png"):
            shutil.copyfile(texture, textures / texture.name)
        (work / "config/cubeon-store.json").write_text(json.dumps(dict(items=all_models, anchors=cosmetics.ANCHORS)))
        selection=work / "config/cubeon-cosmetics.json"
        selected=json.loads(selection.read_text())
        selected.update(head="head_horns",feet=None,aura="aura_butterfly")
        selection.write_text(json.dumps(selected))
        expected = []
        for item in all_models:
            entries = []
            for name in (item["texture"], item.get("emissive_texture")):
                if name:
                    with Image.open(textures / name) as image:
                        entries.append(dict(name=name, width=image.width, height=image.height))
            expected.append(dict(id=item["id"], textures=entries))
        names = work / "names.json"
        wearables = [cosmetics.get("head_horns"), *[item for item in items if item['slot'] in ('head', 'feet')]]
        names.write_text(json.dumps({**names_for(version), "models": expected, "skinlayers": bool(skinlayers),
            "wearables": [dict(id=item['id'],slot=item['slot'],pixels=sorted(cosmetics.covered_skin_pixels(item))) for item in wearables]}))
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
