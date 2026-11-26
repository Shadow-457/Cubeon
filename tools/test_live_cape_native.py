"""Verify real cape/Elytra texture selection with CSL in isolated cached Fabric games.

Defaults to 1.21.11 and 26.3. Requires their installed runtime, Fabric API,
CustomSkinLoader, a cached New World, and a graphical desktop. Copies worlds;
all options, skin caches, and probe mods stay in temporary game directories.
Use --skins-only to verify skin/cape upload and selection without lighting checks.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from minecraft_launcher_lib.command import get_minecraft_command

ROOT = Path(__file__).resolve().parents[1]
GAME = Path.home() / '.cubeon_minecraft'
RUNTIME = GAME / 'instances/.runtime'
JAVA = Path.home() / 'jdks/jdk-25.0.4.1+1/bin'
OUT = ROOT / 'build/cape-native-verification'

PROBE = r'''
package probe;
import com.cubeon.client.Json;
import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.FullBright;
import com.cubeon.client.skins.CapeAnimation;
import com.cubeon.client.skins.LiveSkin;
import net.fabricmc.api.ClientModInitializer;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

public class CapeProbe implements ClientModInitializer {
    static Map<String,Object> names;
    static int checks;
    boolean finished;
    static String name(String key) { return (String)names.get(key); }
    static Class<?> type(String key) throws Exception { return Class.forName(name(key)); }
    static Object field(Object owner,String key) throws Exception {
        return owner.getClass().getField(name(key)).get(owner);
    }
    static Object call(Object owner,String key) throws Exception {
        return owner.getClass().getMethod(name(key)).invoke(owner);
    }
    static void check(boolean ok,String message) {
        checks++; if(!ok) throw new AssertionError(message);
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
            Object player=field(client,"player");
            if(player==null) return;
            finished=true;
            Object options=field(client,"options");
            byte[] skinPng=Files.readAllBytes(Path.of(System.getProperty("cubeon.probe.skin")));
            var peerSkin=new com.cubeon.client.skins.RemoteSkins.Skin(skinPng,false,"native-peer-probe");
            Object peerTexture=Class.forName("com.cubeon.client.skins.RemoteSkinTexture")
                    .getMethod("texture",String.class,com.cubeon.client.skins.RemoteSkins.Skin.class)
                    .invoke(null,"NativePeer",peerSkin);
            check(peerTexture!=null && peerTexture.toString().equals("cubeon-client:peer_skin/nativepeer"),
                    "Real native image upload registers a peer skin texture");
            var before=call(call(call(player,"getSkin"),"body"),"texturePath");
            LiveSkin.accept(Map.of("ok",true,"skin",Map.of("mode","managed","applied",Map.of(
                "id","chosen", "name","Chosen", "hash","native-probe",
                "png",Base64.getEncoder().encodeToString(skinPng), "slim",false, "model","classic"))));
            var body=call(call(call(player,"getSkin"),"body"),"texturePath");
            check(body.toString().equals("cubeon-client:live_skin"),"Selected Cubeon skin reaches the real player getter with CSL loaded");
            LiveSkin.accept(Map.of("ok",true,"skin",Map.of("mode","disabled")));
            check(call(call(call(player,"getSkin"),"body"),"texturePath").equals(before),
                    "Disabling the managed override exposes CSL or Minecraft's original skin");
            Object capePart=type("part").getField(name("capePart")).get(null);
            Method set=options.getClass().getMethod(name("setPart"),type("part"),boolean.class);
            byte[] png=Files.readAllBytes(Path.of(System.getProperty("cubeon.probe.cape")));
            set.invoke(options,capePart,true);
            CapeAnimation.apply(png,false,null,"native-still");
            check((Boolean)Class.forName("com.cubeon.client.hud.screen.SkinNative").getMethod("capeVisible").invoke(null),"Native cape option enabled");
            Object skin=call(player,"getSkin");
            Object cape=call(skin,"cape");
            check(cape!=null,"Real local skin getter returns live cape");
            Object wings=call(skin,"elytra");
            check(wings!=null,"Real local skin getter retains visible Elytra texture");
            check(!call(wings,"texturePath").equals(call(cape,"texturePath")),"Elytra never samples raw cape artwork");
            Object state=type("state").getConstructor().newInstance();
            state.getClass().getField(name("skinTextures")).set(state,skin);
            state.getClass().getField(name("capeVisible")).setBoolean(state,true);
            Method pick=null;
            for(Method candidate:type("wingsLayer").getDeclaredMethods()) {
                if(candidate.getName().equals(name("getTexture")) && Modifier.isStatic(candidate.getModifiers())) pick=candidate;
            }
            if(pick==null) throw new AssertionError("Missing concrete vanilla Elytra texture selector");
            pick.setAccessible(true);
            check(pick.invoke(null,state).equals(call(wings,"texturePath")),"Actual vanilla wing layer selects independent Elytra artwork");
            set.invoke(options,capePart,false);
            check(!(Boolean)Class.forName("com.cubeon.client.hud.screen.SkinNative").getMethod("capeVisible").invoke(null),"Native cape option disabled");
            check(call(call(player,"getSkin"),"cape")==null,"Own cape stays hidden even with server cape flags enabled");
            CapeAnimation.apply(png,false,null,"native-refresh");
            check(call(call(player,"getSkin"),"cape")==null,"Live refresh preserves disabled local cape");
            set.invoke(options,capePart,true);
            CapeAnimation.apply(png,true,null,"__none__");
            skin=call(player,"getSkin");
            check(call(skin,"cape")==null,"No Cape selection hides local cape");
            state.getClass().getField(name("skinTextures")).set(state,skin);
            check(pick.invoke(null,state)!=null,"No Cape preserves concrete vanilla Elytra texture selection");
            CapeAnimation.accept(Map.of("ok",true,"enabled",false,"revision","disabled"));
            set.invoke(options,capePart,false);
            check(call(call(player,"getSkin"),"cape")==null,"Local visibility applies before or after bridge clears selection");

            // 1.21.11 caches the lightmap aggressively. The mixin must notice
            // both setting edges before vanilla's !dirty early return, while
            // the gamma option override remains scoped to lightmap work.
            if(!Boolean.getBoolean("cubeon.probe.skinsOnly")) {
            Object renderer=field(client,"gameRenderer");
            Object lightmap=call(renderer,"getLightmap");
            Field enabled=lightmap.getClass().getDeclaredField("cubeon$fullBright"); enabled.setAccessible(true);
            Method update=lightmap.getClass().getMethod(name("update"),float.class);
            CubeonHudConfig.get().fullBright=false; update.invoke(lightmap,0f);
            check(!enabled.getBoolean(lightmap),"Full Bright disable edge reaches the real lightmap");
            CubeonHudConfig.get().fullBright=true; update.invoke(lightmap,0f);
            check(enabled.getBoolean(lightmap),"Full Bright enable edge forces the real lightmap rebuild");
            Object gamma=call(options,"getGamma");
            FullBright.beginLightmap(); Object boosted=call(gamma,"getValue"); FullBright.endLightmap();
            check(boosted instanceof Double && ((Double)boosted)==FullBright.GAMMA,
                    "Real gamma option receives the scoped Full Bright value");
            }
            System.out.println("CUBEON_CAPE_NATIVE_PASS "+checks+" checks with CustomSkinLoader");
        } catch(Throwable error) {
            finished=true;System.out.println("CUBEON_CAPE_NATIVE_FAIL "+error);error.printStackTrace();
        } finally {
            if(finished) try { call(client,"stop"); } catch(Exception error) { throw new RuntimeException(error); }
        }
    }
}
'''


def names_for(version):
    if version.startswith('26.'):
        return dict(part='net.minecraft.world.entity.player.PlayerModelPart', capePart='CAPE',
                    player='player', options='options', gameRenderer='gameRenderer',
                    setPart='setModelPart', getSkin='getSkin', getLightmap='getLightmapTextureManager',
                    getGamma='getGamma', getValue='get', update='extractRenderState',
                    body='body', cape='cape', elytra='elytra', texturePath='texturePath',
                    state='net.minecraft.client.renderer.entity.state.AvatarRenderState',
                    skinTextures='skin', capeVisible='showCape',
                    wingsLayer='net.minecraft.client.renderer.entity.layers.WingsLayer',
                    getTexture='getPlayerElytraTexture', stop='stop')
    mapping = next((Path.home() / '.gradle/caches/fabric-loom' / version).glob('net.fabricmc.yarn*/mappings.tiny'))
    classes, members = {}, {}
    for line in mapping.read_text().splitlines():
        columns = line.split('\t')
        if columns[0] == 'c':
            classes[columns[-1]] = columns[-2].replace('/', '.')
        elif len(columns) > 4 and columns[1] in ('m', 'f'):
            members[columns[-1]] = columns[-2]
    result = {key: members[value] for key, value in dict(
        capePart='CAPE', player='player', options='options', gameRenderer='gameRenderer',
        setPart='setPlayerModelPart', getLightmap='getLightmapTextureManager', getGamma='getGamma',
        getValue='getValue', update='update',
        getSkin='getSkin', body='body', cape='cape', elytra='elytra', texturePath='texturePath',
        skinTextures='skinTextures', capeVisible='capeVisible', getTexture='getTexture', stop='scheduleStop').items()}
    # Names repeated on unrelated classes need the concrete owner below.
    owners = dict(part='net/minecraft/entity/player/PlayerModelPart',
                  renderer='net/minecraft/client/render/GameRenderer',
                  lightmap='net/minecraft/client/render/LightmapTextureManager',
                  option='net/minecraft/client/option/SimpleOption',
                  state='net/minecraft/client/render/entity/state/PlayerEntityRenderState',
                  wingsLayer='net/minecraft/client/render/entity/feature/ElytraFeatureRenderer')
    result.update({key: classes[value] for key, value in owners.items()})
    owner = None
    wanted = {'net/minecraft/client/MinecraftClient': {'player', 'options', 'scheduleStop'},
              'net/minecraft/client/option/GameOptions': {'setPlayerModelPart', 'getGamma'},
              owners['renderer']: {'getLightmapTextureManager'}, owners['lightmap']: {'update'},
              owners['option']: {'getValue'},
              'net/minecraft/entity/player/SkinTextures': {'body', 'cape', 'elytra'},
              owners['part']: {'CAPE'},
              owners['state']: {'skinTextures', 'capeVisible'}, owners['wingsLayer']: {'getTexture'}}
    for line in mapping.read_text().splitlines():
        columns = line.split('\t')
        if columns[0] == 'c': owner = columns[-1]
        elif len(columns) > 4 and columns[1] in ('m', 'f') and columns[-1] in wanted.get(owner, set()):
            key = {'scheduleStop': 'stop', 'CAPE': 'capePart', 'setPlayerModelPart': 'setPart'}.get(columns[-1], columns[-1])
            result[key] = columns[-2]
    return result


def verify(version, *, skins_only=False):
    profiles = GAME / 'instances' / f'{version}-Fabric'
    game = profiles / 'minecraft' if (profiles / 'minecraft').is_dir() else profiles
    loader = next((RUNTIME / 'versions').glob(f'fabric-loader-*-{version}')).name
    client = ROOT / 'assets/jars' / f'cubeon-client-1.0.0+mc{version}.jar'
    api = next((game / 'mods').glob('fabric-api-*.jar'))
    csl = next((game / 'mods').glob('CustomSkinLoader*.jar'))
    with tempfile.TemporaryDirectory(prefix=f'cubeon-cape-native-{version}-') as temporary:
        work = Path(temporary)
        mods = work / 'mods'; mods.mkdir()
        for artifact in (client, api, csl): shutil.copyfile(artifact, mods / artifact.name)
        shutil.copytree(game / 'saves/New World', work / 'saves/Cape probe',
                        ignore=shutil.ignore_patterns('session.lock'))
        classes = work / 'classes'; classes.mkdir()
        source = work / 'CapeProbe.java'; source.write_text(PROBE)
        cp = os.pathsep.join(map(str, [client, *sorted((RUNTIME / 'libraries/net/fabricmc/fabric-loader').rglob('*.jar'))]))
        subprocess.run([str(JAVA / 'javac'), '-proc:none', '--release', '17', '-cp', cp,
                        '-d', str(classes), str(source)], check=True, timeout=60)
        with zipfile.ZipFile(mods / 'cape-probe.jar', 'w') as jar:
            for file in classes.rglob('*.class'): jar.write(file, file.relative_to(classes).as_posix())
            jar.writestr('fabric.mod.json', json.dumps(dict(schemaVersion=1, id='cape_probe', version='1.0',
                environment='client', entrypoints={'client': ['probe.CapeProbe']})))
        names = work / 'names.json'; names.write_text(json.dumps(names_for(version)))
        (work / 'options.txt').write_text('maxFps:60\nenableVsync:false\nonboardAccessibility:false\n')
        command = get_minecraft_command(loader, str(RUNTIME), dict(
            username='CapeProbe', uuid='5f5e020167373e67b59baa2682e55583', token='0',
            executablePath=str(JAVA / 'java'), gameDirectory=str(work),
            jvmArguments=['-Xmx1536M', '-Xms256M', f'-Dcubeon.probe.names={names}',
                          f'-Dcubeon.probe.skinsOnly={str(skins_only).lower()}',
                          f'-Dcubeon.probe.skin={ROOT / "assets/skins/steve.png"}',
                          f'-Dcubeon.probe.cape={ROOT / "assets/capes/cubeon_cape.png"}'],
            launcherName='CubeonCapeProbe', launcherVersion='1'))
        command += ['--quickPlaySingleplayer', 'Cape probe']
        log = OUT / f'{version}.log'
        with log.open('w') as output:
            process = subprocess.Popen(command, cwd=work, stdout=output, stderr=subprocess.STDOUT)
            try: result = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.terminate(); process.wait(timeout=15)
                raise RuntimeError(f'Owned native probe timed out: {log}')
        text = log.read_text()
        assert result == 0 and 'CUBEON_CAPE_NATIVE_PASS' in text and 'CUBEON_CAPE_NATIVE_FAIL' not in text, log
        print(version, next(line for line in text.splitlines() if 'CUBEON_CAPE_NATIVE_PASS' in line))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('versions', nargs='*', default=['1.21.11', '26.3'])
    parser.add_argument('--skins-only', action='store_true', help='Skip unrelated lightmap checks')
    OUT.mkdir(parents=True, exist_ok=True)
    args = parser.parse_args()
    for version in args.versions: verify(version, skins_only=args.skins_only)
