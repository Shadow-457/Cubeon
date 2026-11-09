"""Boot an isolated installed Fabric 26.3 and verify real wing-layer mixins.

Uses cached game libraries/assets, a temporary game folder and an automatic exit.
Opens a temporary copy of a cached world; never changes player profiles. Requires a graphical desktop.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from minecraft_launcher_lib.command import get_minecraft_command

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path.home() / 'jdks/jdk-25.0.4.1+1/bin'
GAME = Path.home() / '.cubeon_minecraft/instances/.runtime'
PROFILE = Path.home() / '.cubeon_minecraft/instances/26.3-Fabric/mods'
OUT = ROOT / 'archive/ui-captures/elytra-wings-native'

PROBE = r'''
package probe;
import com.cubeon.client.cosmetics.*;
import com.cubeon.client.mixin.CosmeticLayersAccessor;
import com.mojang.blaze3d.vertex.PoseStack;
import java.lang.reflect.*;
import java.util.*;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.SubmitNodeCollector;
import net.minecraft.client.renderer.entity.layers.WingsLayer;
import net.minecraft.client.renderer.entity.state.HumanoidRenderState;
import net.minecraft.world.item.*;

public class ElytraProbe implements ClientModInitializer {
    boolean finished;
    static int checks;
    static void check(boolean ok,String message) {
        checks++; if(!ok) throw new AssertionError(message);
    }
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(mc -> {
            if(finished) return;
            try {
                Field field=mc.getEntityRenderDispatcher().getClass().getDeclaredField("playerRenderers");
                field.setAccessible(true);
                var renderers=(Map<?,?>)field.get(mc.getEntityRenderDispatcher());
                if(renderers==null || renderers.isEmpty() || mc.level==null || mc.player==null) return;
                finished=true;
                for(var renderer:renderers.values()) verify(renderer);
                System.out.println("CUBEON_ELYTRA_NATIVE_PASS "+checks+" checks; real vanilla fallback and cosmetic cancellation");
            } catch(Throwable error) {
                finished=true;
                System.out.println("CUBEON_ELYTRA_NATIVE_FAIL "+error);
                error.printStackTrace();
            } finally {
                if(finished) mc.stop();
            }
        });
    }
    static void verify(Object renderer) throws Exception {
        check(renderer instanceof CosmeticLayersAccessor,"Layer-list accessor applied to real avatar renderer");
        var layers=((CosmeticLayersAccessor)renderer).cubeon$getCosmeticLayers();
        int wing=-1,cosmetic=-1;
        for(int i=0;i<layers.size();i++) {
            if(layers.get(i) instanceof WingsLayer) wing=i;
            if(layers.get(i) instanceof CosmeticRenderLayer) cosmetic=i;
        }
        check(wing>=0 && cosmetic==wing-1,"Real registration draws Cubeon wings immediately before vanilla");
        var enabled=CosmeticRenderLayer.class.getDeclaredField("replacesElytra");
        enabled.setAccessible(true);
        check(enabled.getBoolean(layers.get(cosmetic)),"Successful registration enables replacement");
        Method submit=WingsLayer.class.getDeclaredMethod("submit",PoseStack.class,SubmitNodeCollector.class,
                int.class,HumanoidRenderState.class,float.class,float.class);
        var state=new HumanoidRenderState();
        state.chestEquipment=new ItemStack(Items.ELYTRA);
        ItemStack equipment=state.chestEquipment;
        int[] models={0};
        var collector=(SubmitNodeCollector)Proxy.newProxyInstance(SubmitNodeCollector.class.getClassLoader(),
                new Class[]{SubmitNodeCollector.class},(proxy,method,args)->{
                    if(method.getName().equals("order")) return proxy;
                    if(method.getName().equals("submitModel")) models[0]++;
                    return null;
                });
        var catalog=CosmeticCatalog.get();
        var giant=catalog.get("back_void_wings");
        for(var item:List.of(giant,giant.forWingDepth(false),catalog.get("back_void_wings_small"))) {
            CosmeticElytra.begin(state); CosmeticElytra.drawn(item); models[0]=0;
            submit.invoke(layers.get(wing),new PoseStack(),collector,15728880,state,0f,0f);
            check(models[0]==0,"Actual elytra mixin cancels only the vanilla model for ready wings");
            check(!CosmeticElytra.consume(state),"Real mixin consumed the draw marker");
        }
        for(int mode=0;mode<4;mode++) {
            CosmeticElytra.begin(state);
            if(mode==1) CosmeticElytra.drawn(catalog.get("back_gear_pack"));
            if(mode==2) CosmeticElytra.drawn(null);
            if(mode==3) {CosmeticElytra.drawn(giant); CosmeticElytra.begin(new Object());}
            models[0]=0;
            submit.invoke(layers.get(wing),new PoseStack(),collector,15728880,state,0f,0f);
            check(models[0]>0,"Actual vanilla elytra still submits with hidden/empty/non-wing selections");
        }
        check(state.chestEquipment==equipment && equipment.is(Items.ELYTRA),"Equipment unchanged");
        state.chestEquipment=ItemStack.EMPTY;
        CosmeticElytra.begin(state); models[0]=0;
        submit.invoke(layers.get(wing),new PoseStack(),collector,0,state,0f,0f);
        check(models[0]==0,"Cosmetics never grant equipment or flight");
    }
}
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cubeon-elytra-native-') as temporary:
        work = Path(temporary)
        mods = work / 'mods'
        mods.mkdir()
        client = ROOT / 'assets/jars/cubeon-client-1.0.0+mc26.3.jar'
        api = PROFILE / 'fabric-api-0.163.0+26.3.jar'
        shutil.copyfile(client, mods / client.name)
        shutil.copyfile(api, mods / api.name)
        world = Path.home() / '.cubeon_minecraft/instances/26.3-Fabric/saves/New World'
        shutil.copytree(world, work / 'saves/Elytra probe', ignore=shutil.ignore_patterns('session.lock'))
        source = work / 'ElytraProbe.java'
        source.write_text(PROBE)
        classes = work / 'classes'
        classes.mkdir()
        api_classes = work / 'api'
        api_classes.mkdir()
        with zipfile.ZipFile(api) as bundle:
            for name in bundle.namelist():
                if name.endswith('.jar'):
                    (api_classes / Path(name).name).write_bytes(bundle.read(name))
        cp = os.pathsep.join(map(str, [GAME / 'versions/26.3/26.3.jar', client,
                                      *sorted((GAME / 'libraries').rglob('*.jar')),
                                      *api_classes.glob('*.jar')]))
        subprocess.run([str(JAVA / 'javac'), '-proc:none', '--release', '17', '-cp', cp,
                        '-d', str(classes), str(source)], check=True, timeout=60)
        with zipfile.ZipFile(mods / 'elytra-probe.jar', 'w') as jar:
            for file in classes.rglob('*.class'):
                jar.write(file, file.relative_to(classes).as_posix())
            jar.writestr('fabric.mod.json', json.dumps({
                'schemaVersion': 1, 'id': 'elytra_probe', 'version': '1.0',
                'environment': 'client', 'entrypoints': {'client': ['probe.ElytraProbe']}}))
        (work / 'options.txt').write_text('maxFps:60\nenableVsync:false\nonboardAccessibility:false\n')
        command = get_minecraft_command('fabric-loader-0.20.1-26.3', str(GAME), {
            'username': 'ElytraProbe', 'uuid': '5f5e020167373e67b59baa2682e55583',
            'token': '0', 'executablePath': str(JAVA / 'java'), 'gameDirectory': str(work),
            'jvmArguments': ['-Xmx1536M', '-Xms256M'],
            'launcherName': 'CubeonElytraProbe', 'launcherVersion': '1'})
        command += ['--quickPlaySingleplayer', 'Elytra probe']
        env = dict(os.environ)
        for key in ('LIBGL_ALWAYS_SOFTWARE', 'MESA_LOADER_DRIVER_OVERRIDE', 'GALLIUM_DRIVER'):
            env.pop(key, None)
        log = OUT / 'startup.log'
        with log.open('w') as output:
            process = subprocess.Popen(command, cwd=work, env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                result = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=15)
                raise RuntimeError(f'Owned native probe timed out; inspect {log}')
        text = log.read_text()
        assert result == 0 and 'CUBEON_ELYTRA_NATIVE_PASS' in text and 'CUBEON_ELYTRA_NATIVE_FAIL' not in text, log
        print(next(line for line in text.splitlines() if 'CUBEON_ELYTRA_NATIVE_PASS' in line))
        print('Isolated Minecraft saved and exited; original world and player profiles untouched.')


if __name__ == '__main__':
    main()
