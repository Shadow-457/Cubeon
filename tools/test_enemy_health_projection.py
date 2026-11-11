"""Exercise the production 26.x projector against changing extracted camera states."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
JOML = next((Path.home() / '.gradle/caches/modules-2/files-2.1/org.joml/joml').glob('*/*/joml-*.jar'), None)

FIXTURES = {
    'net/minecraft/world/phys/Vec3.java': '''package net.minecraft.world.phys;
public class Vec3 { public final double x,y,z;
public Vec3(double x,double y,double z){this.x=x;this.y=y;this.z=z;} }''',
    'com/mojang/blaze3d/vertex/PoseStack.java': '''package com.mojang.blaze3d.vertex;
public class PoseStack { private final Pose pose=new Pose(); public Pose last(){return pose;}
public static class Pose { private final org.joml.Matrix4f matrix=new org.joml.Matrix4f();
public org.joml.Matrix4f pose(){return matrix;} } }''',
    'net/minecraft/client/renderer/state/level/CameraRenderState.java': '''package net.minecraft.client.renderer.state.level;
public class CameraRenderState { public boolean initialized=true;
public net.minecraft.world.phys.Vec3 pos=new net.minecraft.world.phys.Vec3(1,2,3);
public org.joml.Matrix4f projectionMatrix=new org.joml.Matrix4f().perspective((float)Math.PI/3,2,.05f,100);
public org.joml.Matrix4f viewRotationMatrix=new org.joml.Matrix4f().rotateY(.15f);
public org.joml.Quaternionf orientation=new org.joml.Quaternionf().rotateY(.15f); }''',
    'net/minecraft/client/renderer/state/GameRenderState.java': '''package net.minecraft.client.renderer.state;
public class GameRenderState { public final Level levelRenderState=new Level();
public final Options optionsRenderState=new Options();
public static class Level { public final net.minecraft.client.renderer.state.level.CameraRenderState cameraRenderState=new net.minecraft.client.renderer.state.level.CameraRenderState(); }
public static class Options { public boolean bobView=true; } }''',
    'com/cubeon/client/hud/mixin/EnemyHealthGameRendererAccessor.java': '''package com.cubeon.client.hud.mixin;
public interface EnemyHealthGameRendererAccessor {
net.minecraft.client.renderer.state.GameRenderState cubeon$healthRenderState();
void cubeon$healthHurt(net.minecraft.client.renderer.state.level.CameraRenderState camera,com.mojang.blaze3d.vertex.PoseStack matrices);
void cubeon$healthBob(net.minecraft.client.renderer.state.level.CameraRenderState camera,com.mojang.blaze3d.vertex.PoseStack matrices); }''',
    'net/minecraft/client/renderer/GameRenderer.java': '''package net.minecraft.client.renderer;
public class GameRenderer { public static class NativeRenderer extends GameRenderer implements com.cubeon.client.hud.mixin.EnemyHealthGameRendererAccessor {
public final net.minecraft.client.renderer.state.GameRenderState state=new net.minecraft.client.renderer.state.GameRenderState();
public int hurtCalls,bobCalls;
public net.minecraft.client.renderer.state.GameRenderState cubeon$healthRenderState(){return state;}
public void cubeon$healthHurt(net.minecraft.client.renderer.state.level.CameraRenderState camera,com.mojang.blaze3d.vertex.PoseStack matrices){hurtCalls++;matrices.last().pose().rotateZ(.2f);}
public void cubeon$healthBob(net.minecraft.client.renderer.state.level.CameraRenderState camera,com.mojang.blaze3d.vertex.PoseStack matrices){bobCalls++;matrices.last().pose().translate(.3f,-.1f,0);} } }''',
    'net/minecraft/client/Minecraft.java': '''package net.minecraft.client;
public class Minecraft { public Object level=new Object(),player=new Object();
public net.minecraft.client.renderer.GameRenderer gameRenderer=new net.minecraft.client.renderer.GameRenderer.NativeRenderer(); }''',
    'probe/Test.java': '''package probe;
import com.cubeon.client.hud.WorldHealthProjection;
import net.minecraft.world.phys.Vec3;
import org.joml.Matrix4f;
import org.joml.Vector4f;
public class Test {
static void check(boolean value,String label){if(!value)throw new AssertionError(label);}
static void close(double a,double b,String label){check(Math.abs(a-b)<1e-6,label);}
static Vec3 reference(net.minecraft.client.renderer.state.level.CameraRenderState camera,Vec3 point,boolean bob){
    var clip=new Vector4f((float)(point.x-camera.pos.x),(float)(point.y-camera.pos.y),(float)(point.z-camera.pos.z),1);
    camera.viewRotationMatrix.transform(clip);
    if(bob)new Matrix4f().translation(.3f,-.1f,0).transform(clip);
    new Matrix4f().rotateZ(.2f).transform(clip);
    camera.projectionMatrix.transform(clip);
    return new Vec3(clip.x/clip.w,clip.y/clip.w,clip.z/clip.w);
}
static void same(Vec3 a,Vec3 b,String label){close(a.x,b.x,label+" x");close(a.y,b.y,label+" y");close(a.z,b.z,label+" z");}
public static void main(String[]args){
    var client=new net.minecraft.client.Minecraft();
    var renderer=(net.minecraft.client.renderer.GameRenderer.NativeRenderer)client.gameRenderer;
    var camera=renderer.state.levelRenderState.cameraRenderState;
    var point=new Vec3(2,3,-7);
    var first=WorldHealthProjection.current(client);var initial=first.project(point);
    same(initial,reference(camera,point,true),"native hurt/bob projection order");
    check(renderer.hurtCalls==1&&renderer.bobCalls==1,"effects called once");
    camera.pos=new Vec3(2,2,3);camera.projectionMatrix.scale(1.4f,1.4f,1);
    camera.viewRotationMatrix.rotateY(.1f);camera.orientation.rotateY(.1f);
    var second=WorldHealthProjection.current(client);
    same(second.project(point),reference(camera,point,true),"current extracted camera");
    check(Math.abs(second.project(point).x-initial.x)>.01,"new frame uses new camera");
    same(first.project(point),initial,"prior snapshot retained");
    close(first.camera().x,1,"snapshot position");
    close(first.rotation().y(),Math.sin(.15f/2),"snapshot orientation");
    renderer.state.optionsRenderState.bobView=false;
    var noBob=WorldHealthProjection.current(client);
    same(noBob.project(point),reference(camera,point,false),"walking bob disabled");
    check(renderer.bobCalls==2&&renderer.hurtCalls==3,"hurt kept when walking bob disabled");
    check(second.project(new Vec3(2,2,8))==null,"behind camera clipped");
    camera.initialized=false;check(WorldHealthProjection.current(client)==null,"uninitialized skipped");
    client.level=null;check(WorldHealthProjection.current(client)==null,"no level skipped");
    client.level=new Object();client.player=null;check(WorldHealthProjection.current(client)==null,"no player skipped");
    client.player=new Object();client.gameRenderer=new net.minecraft.client.renderer.GameRenderer();
    check(WorldHealthProjection.current(client)==null,"missing optional accessor skipped");
    System.out.println("26.x current-frame health projection: PASS");
} }''',
}


@unittest.skipUnless(shutil.which('javac') and shutil.which('java') and JOML, 'Requires JDK and cached JOML')
class EnemyHealthProjectionTest(unittest.TestCase):
    def test_current_frame_native_motion_and_snapshot(self):
        source = ROOT / 'mod/src/main/java-overlay-api-mojang/com/cubeon/client/hud/WorldHealthProjection.java'
        with tempfile.TemporaryDirectory(prefix='cubeon-health-projection-') as tmp:
            base = Path(tmp)
            paths = []
            for name, body in FIXTURES.items():
                path = base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body)
                paths.append(path)
            classes = base / 'classes'
            result = subprocess.run(['javac', '-proc:none', '--release', '17', '-cp', str(JOML),
                                     '-d', str(classes), *map(str, paths), str(source)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run(['java', '-cp', str(classes) + os.pathsep + str(JOML), 'probe.Test'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
