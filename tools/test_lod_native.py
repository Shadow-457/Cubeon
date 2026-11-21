"""Exercise real 26.3 LOD drawing on a private copy of an installed world.

Read back offscreen depth and final scene colour on CPU and GPU paths, verify
nearby terrain occlusion and complete planted ground at the transition, switch
processing, freeze updates, and disable LOD. Does not edit installed profiles.
"""
import argparse
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
GAME = Path.home()/'.cubeon_minecraft/instances/.runtime'
JAVA = Path.home()/'jdks/jdk-25.0.4.1+1/bin'
PROBE = r'''
package probe;
import com.cubeon.client.lod.*;
import java.lang.reflect.*;
import java.nio.*;
import java.util.*;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import com.mojang.renderpearl.backend.opengl.GlTexture;
import org.lwjgl.opengl.GL11;
import org.lwjgl.opengl.GL45;
import org.lwjgl.system.MemoryUtil;

public class LodProbe implements ClientModInitializer {
 int ticks, stage;
 boolean finished;
 static Object field(Class<?> owner, String name) throws Exception {
  var f=owner.getDeclaredField(name);f.setAccessible(true);return f.get(null);
 }
 static void check(boolean ok,String why) {if(!ok)throw new AssertionError(why);}
 static void apply(LodOptions.Processing mode,boolean enabled,boolean updates) throws Exception {
  LodClient.options().commit(new LodOptions.Value(enabled,128,LodOptions.Detail.MAXIMUM_FPS,mode,updates,false,false,false));
  LodClient.applied();
 }
 static int compositePixels(net.minecraft.client.Minecraft mc, float nearDepth) throws Exception {
  var main=mc.gameRenderer.mainRenderTarget();
  var encoder=com.mojang.blaze3d.systems.RenderSystem.getDevice().createCommandEncoder();
  encoder.clearColorAndDepthTextures(main.getColorTexture(),new org.joml.Vector4f(1,0,1,1),main.getDepthTexture(),nearDepth);
  encoder.submit();
  LodRenderer.render(mc.gameRenderer);
  var texture=(GlTexture)main.getColorTexture();
  ByteBuffer pixels=MemoryUtil.memAlloc(texture.getWidth(0)*texture.getHeight(0)*4);
  try {
   GL45.glGetTextureImage(texture.glId(),0,GL11.GL_RGBA,GL11.GL_UNSIGNED_BYTE,pixels);
   int count=0;for(int i=0;i<pixels.capacity();i+=4)
    if((pixels.get(i)&255)!=255 || (pixels.get(i+1)&255)!=0 || (pixels.get(i+2)&255)!=255)count++;
   check(GL11.glGetError()==0,"Readback has no GL errors");
   return count;
  }finally{MemoryUtil.memFree(pixels);}
 }
 static void checkStatus(String expected) throws Exception {
  var component=(net.minecraft.network.chat.Component)field(SodiumLodOptions.class,"STATUS");
  StringBuilder text=new StringBuilder();
  component.getVisualOrderText().accept((i,s,c)->{text.appendCodePoint(c);return true;});
  check(text.toString().contains(expected),"Live formatted status: "+text);
 }
 static int depthPixels() throws Exception {
  Object value=field(LodRenderer.class,"farDepth");
  if(value==null)return 0;
  var texture=(GlTexture)value;
  FloatBuffer pixels=MemoryUtil.memAllocFloat(texture.getWidth(0)*texture.getHeight(0));
  try {
   GL45.glGetTextureImage(texture.glId(),0,GL11.GL_DEPTH_COMPONENT,GL11.GL_FLOAT,pixels);
   int count=0;for(int i=0;i<pixels.capacity();i++)if(pixels.get(i)>0 && Float.isFinite(pixels.get(i)))count++;
   return count;
  }finally{MemoryUtil.memFree(pixels);}
 }
 static float[] plantedGround(net.minecraft.client.Minecraft mc, boolean gpu) throws Exception {
  var camera=mc.gameRenderer.gameRenderState().levelRenderState.cameraRenderState;
  var position=camera.pos;var view=new org.joml.Matrix4f(camera.viewRotationMatrix);
  var projection=new org.joml.Matrix4f(camera.projectionMatrix);int near=mc.options.renderDistance().get();
  var worker=(TerrainWorker)field(LodClient.class,"worker");
  var published=TerrainWorker.class.getDeclaredField("frame");published.setAccessible(true);var previous=published.get(worker);
  try {
   camera.pos=new net.minecraft.world.phys.Vec3(0,90,0);
   camera.viewRotationMatrix.rotationX((float)Math.toRadians(30)).rotateY((float)Math.PI);
   camera.projectionMatrix.setPerspective((float)Math.toRadians(76),(float)mc.gameRenderer.mainRenderTarget().width/mc.gameRenderer.mainRenderTarget().height,
    2048,.05f,com.mojang.blaze3d.systems.RenderSystem.getDevice().getDeviceInfo().isZZeroToOne());
   mc.options.renderDistance().set(4);
   var catalog=new TextureCatalog();
   int stone=net.minecraft.world.level.block.Block.getId(net.minecraft.world.level.block.Blocks.STONE.defaultBlockState());
   int grass=net.minecraft.world.level.block.Block.getId(net.minecraft.world.level.block.Blocks.SHORT_GRASS.defaultBlockState());
   catalog.resolve(stone);catalog.resolve(grass);
   var ground=new com.cubeon.client.lod.core.Terrain.Material(stone,0xffffffff,0xf0,0);
   var plant=new com.cubeon.client.lod.core.Terrain.Material(grass,0xff00ff00,0xf0,com.cubeon.client.lod.core.Terrain.CUTOUT);
   var columns=new com.cubeon.client.lod.core.Terrain.Column[256];
   Arrays.fill(columns,new com.cubeon.client.lod.core.Terrain.Column(List.of(
    new com.cubeon.client.lod.core.Terrain.Span(0,80,ground),new com.cubeon.client.lod.core.Terrain.Span(80,81,plant))));
   var meshes=new ArrayList<PackedMesh>();long size=0;
   for(int z=2;z<=3;z++)for(int x=2;x<=3;x++) {
    var key=new com.cubeon.client.lod.core.TilePlan.Key(x,z,0);
    var mesh=com.cubeon.client.lod.core.TileMesh.build(key,columns);
    var packed=PackedMesh.pack(mesh,gpu,catalog,999,128L<<20);check(packed!=null,"Synthetic fixture packs");
    meshes.add(packed);size+=packed.bytes();
   }
   check(size<(2L<<20),"Fixture fits one bounded upload");
   var frame=new TerrainWorker.Frame(((TerrainWorker.Frame)previous).generation(),meshes,"planted ground fixture",size);
   published.set(worker,frame);LodRenderer.shutdown();LodRenderer.render(mc.gameRenderer);
   var texture=(GlTexture)field(LodRenderer.class,"farDepth");check(texture!=null,"Synthetic terrain renders");
   FloatBuffer depth=MemoryUtil.memAllocFloat(texture.getWidth(0)*texture.getHeight(0));
   try {
    GL45.glGetTextureImage(texture.glId(),0,GL11.GL_DEPTH_COMPONENT,GL11.GL_FLOAT,depth);
    float[] result=new float[depth.capacity()];depth.get(result);
    var inverse=new org.joml.Matrix4f(camera.projectionMatrix).invert();
    var rotation=new org.joml.Matrix4f(camera.viewRotationMatrix).invert();
    int expected=0,covered=0;
    for(int y=0;y<texture.getHeight(0);y++)for(int x=0;x<texture.getWidth(0);x++) {
     var ray=new org.joml.Vector4f(2*(x+.5f)/texture.getWidth(0)-1,2*(y+.5f)/texture.getHeight(0)-1,.5f,1);
     inverse.transform(ray);ray.div(ray.w);
     var direction=new org.joml.Vector3f(ray.x,ray.y,ray.z).mulDirection(rotation);
     if(direction.y>=0)continue;
     float t=-10/direction.y;var hit=new org.joml.Vector3f(direction).mul(t);
     float eye=-new org.joml.Vector3f(hit).mulDirection(camera.viewRotationMatrix).z;
     if(hit.x>33 && hit.x<63 && hit.z>33 && hit.z<63 && hit.x*hit.x+hit.z*hit.z>2500 && eye<47) {
      expected++;if(result[y*texture.getWidth(0)+x]>0)covered++;
     }
    }
    check(expected>100,"Camera-space transition fixture has visible ground");
    check(covered==expected,"Ground under plants and inside old clipping plane: "+covered+"/"+expected);
    System.out.println("LOD_PROBE_GROUND "+(gpu?"GPU":"CPU")+" covered="+covered+" expected="+expected);
    return result;
   }finally{MemoryUtil.memFree(depth);}
  }finally {
   published.set(worker,previous);camera.pos=position;camera.viewRotationMatrix.set(view);camera.projectionMatrix.set(projection);
   mc.options.renderDistance().set(near);LodRenderer.shutdown();
  }
 }
 public void onInitializeClient() {
  ClientTickEvents.END_CLIENT_TICK.register(mc->{
   if(finished || mc.level==null || mc.player==null)return;
   try {
    ticks++;
    if(!net.fabricmc.loader.api.FabricLoader.getInstance().isModLoaded("sodium")) {
     if(ticks==1)apply(LodOptions.Processing.CPU,true,true);
     if(ticks>=20) {
      check(!LodClient.enabled() && LodClient.status().contains("requires Sodium"),"Absent Sodium keeps LOD inactive");
      check(LodClient.frame()==null && field(LodRenderer.class,"farDepth")==null,"Absent Sodium allocates no LOD targets");
      System.out.println("LOD_PROBE_PASS optional Sodium absence and normal world startup");finished=true;mc.stop();
     }
     return;
    }
    mc.player.setXRot(65);mc.player.setYRot(0);
    if(stage==0) {
     if(ticks==1) {checkStatus("off");mc.options.renderDistance().set(8);apply(LodOptions.Processing.CPU,true,true);}
     if(ticks>=100) {mc.options.renderDistance().set(2);stage=1;ticks=0;}
     return;
    }
    check(!(boolean)field(LodRenderer.class,"failed"),"Production renderer failed: "+LodRenderer.reason());
    if(ticks%20!=0)return;
    System.out.println("LOD_PROBE_PROGRESS stage="+stage+" "+LodClient.status());
    var frame=LodClient.frame();
    boolean gpu=stage==2;
    if(stage<=2) {
     if(frame==null || frame.meshes().isEmpty() || frame.meshes().stream().anyMatch(m->m.gpu()!=gpu))return;
     int pixels=depthPixels();
     if(pixels<100)return;
     checkStatus(gpu?"GPU geometry":"CPU geometry");
     var fog=mc.gameRenderer.gameRenderState().levelRenderState.cameraRenderState.fogData;
     check(fog!=null && fog.renderDistanceEnd==128*16 && fog.renderDistanceStart==128*16*.6f,"Full-detail and LOD distance fog agree");
     int composed=compositePixels(mc,0);check(composed>100,"Far terrain reaches main scene: "+composed+" pixels");
     check(compositePixels(mc,1)==0,"Nearby opaque terrain occludes LOD");
     var uniform=(ByteBuffer)field(LodRenderer.class,"UNIFORMS");
     check(uniform.getFloat(244)==fog.environmentalStart && uniform.getFloat(248)==fog.environmentalEnd,
      "LOD retains the main scene's weather and environmental fog");
     System.out.println("LOD_PROBE_RENDER "+(gpu?"GPU":"CPU")+" depthPixels="+pixels+" scenePixels="+composed+" tiles="+frame.meshes().size());
     if(stage==1) {apply(LodOptions.Processing.GPU,true,true);stage=2;ticks=0;}
     else {check(!LodRenderer.reason().contains("failed"),"GPU path did not fall back");apply(LodOptions.Processing.GPU,true,false);stage=3;ticks=0;}
    } else if(stage==3) {
     check(depthPixels()>100,"Frozen terrain keeps rendering");
     float[] cpu=plantedGround(mc,false),gpuDepth=plantedGround(mc,true);
     check(Arrays.equals(cpu,gpuDepth),"CPU/GPU complete planted terrain depth parity");
     apply(LodOptions.Processing.GPU,false,false);stage=4;ticks=0;
    } else {
     checkStatus("off");
     var fog=mc.gameRenderer.gameRenderState().levelRenderState.cameraRenderState.fogData;
     check(fog!=null && fog.renderDistanceEnd==mc.options.renderDistance().get()*16,"Disable restores normal distance fog");
     check(LodClient.frame()==null && field(LodRenderer.class,"farDepth")==null,"Disable releases worker and GPU targets");
     System.out.println("LOD_PROBE_PASS CPU/GPU real pixels, composition and near occlusion, live status, freeze, disable");finished=true;mc.stop();
    }
   }catch(Throwable ex){System.out.println("LOD_PROBE_FAIL "+ex);ex.printStackTrace();finished=true;mc.stop();}
  });
 }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,default=GAME)
    parser.add_argument('--java-home',type=Path,default=JAVA.parent)
    parser.add_argument('--world',default='New World')
    parser.add_argument('--profile',type=Path,default=Path.home()/'.cubeon_minecraft/instances/26.3-Fabric/minecraft')
    parser.add_argument('--no-sodium',action='store_true',help='Verify world startup and inactive LOD without Sodium')
    parser.add_argument('--sodium',type=Path,default=ROOT/'build/lod-deps/sodium-fabric-0.9.2+mc26.3.jar')
    parser.add_argument('--client',type=Path,default=ROOT/'mod/build/libs/cubeon-client-1.0.0+mc26.3.jar')
    args=parser.parse_args()
    out=ROOT/'build/lod-deps';out.mkdir(parents=True,exist_ok=True)
    log=out/('native-'+('no-sodium' if args.no_sodium else args.sodium.stem)+'.log')
    with tempfile.TemporaryDirectory(prefix='cubeon-lod-native-') as name:
        work=Path(name);mods=work/'mods';mods.mkdir()
        api=next((args.profile/'mods').glob('fabric-api-*.jar'))
        for jar in (args.client,api,*(() if args.no_sodium else (args.sodium,))):shutil.copyfile(jar,mods/jar.name)
        shutil.copytree(args.profile/'saves'/args.world,work/'saves/LOD probe',ignore=shutil.ignore_patterns('session.lock'))
        source=work/'LodProbe.java';source.write_text(PROBE)
        classes=work/'classes';classes.mkdir()
        api_classes=work/'api';api_classes.mkdir()
        with zipfile.ZipFile(api) as bundle:
            for entry in bundle.namelist():
                if entry.endswith('.jar'):(api_classes/Path(entry).name).write_bytes(bundle.read(entry))
        cp=os.pathsep.join(map(str,[args.runtime/'versions/26.3/26.3.jar',args.client,*sorted(p for p in (args.runtime/'libraries').rglob('*.jar') if '/org/lwjgl/' not in str(p) or '/3.4.3/' in str(p)),*api_classes.glob('*.jar')]))
        subprocess.run([str(args.java_home/'bin/javac'),'-proc:none','--release','17','-cp',cp,'-d',str(classes),str(source)],check=True,timeout=60)
        with zipfile.ZipFile(mods/'lod-probe.jar','w') as jar:
            for file in classes.rglob('*.class'):jar.write(file,file.relative_to(classes).as_posix())
            jar.writestr('fabric.mod.json',json.dumps(dict(schemaVersion=1,id='lod_probe',version='1.0',environment='client',entrypoints={'client':['probe.LodProbe']})))
        (work/'options.txt').write_text('maxFps:60\nenableVsync:false\nonboardAccessibility:false\ninactivityFpsLimit:"minimized"\nrenderDistance:8\nsimulationDistance:5\npauseOnLostFocus:false\n')
        command=get_minecraft_command('fabric-loader-0.20.1-26.3',str(args.runtime),dict(username='LODProbe',uuid='5f5e020167373e67b59baa2682e55583',token='0',executablePath=str(args.java_home/'bin/java'),gameDirectory=str(work),jvmArguments=['-Xmx1536M','-Xms256M'],launcherName='CubeonLODProbe',launcherVersion='1'))
        command += ['--quickPlaySingleplayer','LOD probe','--width','640','--height','360']
        env=dict(os.environ)
        for key in ('LIBGL_ALWAYS_SOFTWARE','MESA_LOADER_DRIVER_OVERRIDE','GALLIUM_DRIVER'):env.pop(key,None)
        with log.open('w') as output:
            process=subprocess.Popen(command,cwd=work,env=env,stdout=output,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+180
            try:
                while process.poll() is None and time.monotonic()<deadline:time.sleep(.5)
                if process.poll() is None:raise RuntimeError(f'Native LOD probe timed out: {log}')
            finally:
                if process.poll() is None:process.terminate()
                process.wait(timeout=20)
        content=log.read_text()
        for line in content.splitlines():
            if 'LOD_PROBE_' in line:print(line)
        assert process.returncode==0 and 'LOD_PROBE_PASS' in content and 'LOD_PROBE_FAIL' not in content,log
        print('Native LOD passed:',log)


if __name__=='__main__':main()
