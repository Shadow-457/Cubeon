"""Run production emote injection bodies on local/remote recorded model fixtures.

Only the mixin's synthetic class inheritance is supplied by this harness;
Gradle separately verifies the real target APIs and remaps all 24 jars.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
ANNOTATIONS={
 'org/spongepowered/asm/mixin/Mixin.java':'package org.spongepowered.asm.mixin; public @interface Mixin { Class<?>[] value(); }',
 'org/spongepowered/asm/mixin/Unique.java':'package org.spongepowered.asm.mixin; public @interface Unique {}',
 'org/spongepowered/asm/mixin/injection/At.java':'package org.spongepowered.asm.mixin.injection; public @interface At { String value(); }',
 'org/spongepowered/asm/mixin/injection/Inject.java':'package org.spongepowered.asm.mixin.injection; public @interface Inject { String method(); At at(); }',
 'org/spongepowered/asm/mixin/injection/callback/CallbackInfo.java':'package org.spongepowered.asm.mixin.injection.callback; public class CallbackInfo {}',
 'com/cubeon/client/hud/CubeonHudConfig.java':'''package com.cubeon.client.hud;
 public class CubeonHudConfig { public boolean showEmotes=true; private static final CubeonHudConfig C=new CubeonHudConfig(); public static CubeonHudConfig get(){return C;} }'''
}

@unittest.skipUnless(shutil.which('javac') and shutil.which('java'),'JDK required')
class ModelTests(unittest.TestCase):
 def test_remote_model_hooks(self):
  for era in ('entity','state','origin','mojang'):
   with self.subTest(era=era),tempfile.TemporaryDirectory() as temp:
    folder=Path(temp); fixtures=dict(ANNOTATIONS);mojang=era=='mojang'
    client='net.minecraft.client.Minecraft' if mojang else 'net.minecraft.client.MinecraftClient'
    player='net.minecraft.world.entity.player.Player' if mojang else 'net.minecraft.entity.player.PlayerEntity'
    part='net.minecraft.client.model.geom.ModelPart' if mojang else 'net.minecraft.client.model.ModelPart'
    model='net.minecraft.client.model.HumanoidModel' if mojang else 'net.minecraft.client.render.entity.model.BipedEntityModel'
    state='net.minecraft.client.renderer.entity.state.HumanoidRenderState' if mojang else 'net.minecraft.client.render.entity.state.BipedEntityRenderState'
    avatar='net.minecraft.client.renderer.entity.state.AvatarRenderState' if mojang else 'net.minecraft.client.render.entity.state.PlayerEntityRenderState'
    angles=('xRot','yRot','zRot') if mojang else ('pitch','yaw','roll')
    def add(cls,body):
     package,name=cls.rsplit('.',1)
     fixtures[cls.replace('.','/')+'.java']=f'package {package}; public class {name} '+body
    positions=('x','y','z') if mojang else tuple(('origin' if era=='origin' else 'pivot')+a for a in 'XYZ')
    position=positions[1]
    add(part,'{ public float '+','.join((*angles,*positions))+'; public void copyTransform(ModelPart other) {'+' '.join(f'{a}=other.{a};' for a in (*angles,*positions))+'} }')
    superclass='net.minecraft.entity.LivingEntity' if era=='entity' else 'Object'
    if era=='entity':add(superclass,'{}')
    add(player,f'''extends {superclass} {{
     public java.util.UUID uuid=java.util.UUID.randomUUID(); public String name="BlueFox";
     public boolean alive=true, riding, swimming, sleeping;
     public java.util.UUID {'getUUID' if mojang else 'getUuid'}(){{return uuid;}}
     public Name getName(){{return new Name(name);}}
     public record Name(String value){{public String getString(){{return value;}}}}
     public boolean isAlive(){{return alive;}} public boolean {'isPassenger' if mojang else 'hasVehicle'}(){{return riding;}}
     public boolean isFallFlying(){{return false;}} public boolean isSwimming(){{return swimming;}} public boolean isSleeping(){{return sleeping;}}
    }}''')
    add(client,'{ private static final '+client.split('.')[-1]+' C=new '+client.split('.')[-1]+'(); public static '+client.split('.')[-1]+' getInstance(){return C;} public World '+('level' if mojang else 'world')+'=new World(); public static class World { public '+player+' player=new '+player+'(); public Object '+('getEntity' if mojang else 'getEntityById')+'(int id){return id==42?player:null;} } }')
    add(state,'{ public float '+('ageInTicks' if mojang else 'age')+'=.5f; public boolean '+('isFallFlying' if mojang else 'isGliding')+'; }')
    add(avatar,'extends '+state+' { public int id=42; }')
    fields=', '.join(name+'=new '+part+'()' for name in ('head','hat','body','rightArm','leftArm','rightLeg','leftLeg'))
    add(model,'<T> { public final '+part+' '+fields+'; }')
    source=(ROOT/f'mod/src/main/java-overlay-cubeon-emote-{era}/com/cubeon/client/mixin/EmoteModelMixin.java').read_text()
    source=source.replace('public abstract class EmoteModelMixin {',f'public class EmoteModelMixin extends {model}<Object> {{')
    fixtures['com/cubeon/client/mixin/EmoteModelMixin.java']=source
    call='method.invoke(m, player, 0f, 0f, .5f, 0f, 0f, new org.spongepowered.asm.mixin.injection.callback.CallbackInfo());' if era=='entity' else 'method.invoke(m, renderState, new org.spongepowered.asm.mixin.injection.callback.CallbackInfo());'
    actor='new '+player+'()' if era=='entity' else client+'.getInstance().'+('level' if mojang else 'world')+'.player'
    fixtures['ModelTest.java']='''import com.cubeon.client.emotes.*;
import com.cubeon.client.Bridge;
import com.cubeon.client.mixin.EmoteModelMixin;
public class ModelTest {
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static void near(double a,double b,String why){check(Math.abs(a-b)<0.00002,why+": "+a+" != "+b);}
 static float[] rotate(float x,float y,float z,float pitch,float yaw,float roll){
  float cp=(float)Math.cos(pitch),sp=(float)Math.sin(pitch),cy=(float)Math.cos(yaw),sy=(float)Math.sin(yaw);
  float cr=(float)Math.cos(roll),sr=(float)Math.sin(roll),py=cp*y-sp*z,pz=sp*y+cp*z;
  float yx=cy*x+sy*pz,yz=-sy*x+cy*pz;
  return new float[]{cr*yx-sr*py,sr*yx+cr*py,yz};
 }
 public static void main(String[] args)throws Exception{
  var player=ACTOR; var renderState=new AVATAR();
  var method=java.util.Arrays.stream(EmoteModelMixin.class.getDeclaredMethods())
    .filter(x->x.getName().equals("cubeon$emote")).findFirst().orElseThrow(); method.setAccessible(true);
  EmoteState.sync(java.util.List.of(new Bridge.EmoteEvent(player.UUID().toString(),"BlueFox","wave",10,1)));
  var m=new EmoteModelMixin(); CALL
  check(Math.abs(m.rightArm.PITCH)>2,"Remote player performs wave");
  HAT_CHECK
  RESET
  player.name="Unrelated"; m=new EmoteModelMixin(); CALL
  check(m.rightArm.PITCH==0,"Same UUID with unrelated name is rejected");
  player.name="BlueFox";
  EmoteState.reset(); EmoteState.sync(java.util.List.of(new Bridge.EmoteEvent(player.UUID().toString(),"BlueFox","sit",22,1)));
  m=new EmoteModelMixin(); CALL
  check(m.body.POSITION==10&&m.head.POSITION==10&&m.rightArm.POSITION==10,"Sit lowers torso, head and arms together");
  check(m.rightLeg.PITCH < -1.5f,"Sit extends legs from lowered hips");
  HAT_SIT
  SIT_RESET
  EmoteState.reset(); EmoteState.sync(java.util.List.of(new Bridge.EmoteEvent(player.UUID().toString(),"BlueFox","bow",22,1)));
  m=new EmoteModelMixin(); m.rightArm.POSITION=2; m.leftArm.POSITION=2;
  m.rightArm.PX=-5; m.leftArm.PX=5; m.rightLeg.POSITION=12; m.leftLeg.POSITION=12;
  CALL
  near(m.body.POSITION+12*Math.cos(m.body.PITCH),12,"Bow torso bottom stays at hips");
  near(m.body.PZ+12*Math.sin(m.body.PITCH),0,"Bow cannot open a depth gap at waist");
  near(m.head.POSITION,m.body.POSITION,"Bow head follows the neck");
  near(m.head.PZ,m.body.PZ,"Bow head depth follows neck");
  near(m.rightArm.POSITION,m.body.POSITION+2*Math.cos(m.body.PITCH),"Bow shoulder stays on torso");
  near(m.rightArm.PZ,m.body.PZ+2*Math.sin(m.body.PITCH),"Bow shoulder depth stays on torso");
  near(m.rightLeg.POSITION,12,"Bow keeps legs planted"); near(m.rightLeg.PZ,0,"Bow keeps leg depth");
  BOW_RESET
  // Sweep the complete entrance/hold/exit with standing and crouched base angles.
  for(float basePitch:new float[]{0,.5f})for(float yaw:new float[]{-.7f,.2f})for(float roll:new float[]{-.15f,.1f})
  for(int frame=0;frame<=60;frame++){
   var pose=EmotePose.sample(2,frame/20f,3);pose.anchorBody(1,2,3,basePitch,yaw,roll);
   pose.position(1,1,2,3);
   float[] hip=rotate(0,12,0,basePitch,yaw,roll);
   float[] bent=rotate(0,12,0,pose.blend(1,0,basePitch),yaw,roll);
   for(int axis=0;axis<3;axis++)near(pose.offsets[3+axis]+bent[axis],hip[axis],"Hip anchor across animation and vanilla orientation");
   for(float shoulderY:new float[]{2,2.5f}){
    float[] shoulder=rotate(5,shoulderY,0,basePitch,yaw,roll);
    pose.position(3,1+shoulder[0],2+shoulder[1],3+shoulder[2]);
    float[] expected=rotate(5,shoulderY,0,pose.blend(1,0,basePitch),yaw,roll);
    for(int axis=0;axis<3;axis++)near(shoulder[axis]+pose.offsets[9+axis],expected[axis]+pose.offsets[3+axis],"Slim/classic shoulder connection");
   }
   pose.position(4,-2,12,0);
   for(int axis=0;axis<3;axis++)near(pose.offsets[12+axis],0,"Bow never translates feet");
  }
  EmoteState.reset(); EmoteState.sync(java.util.List.of(new Bridge.EmoteEvent(player.UUID().toString(),"BlueFox","wave",23,1)));
  player.riding=true;m=new EmoteModelMixin();CALL
  check(m.rightArm.PITCH==0,"Riding pose remains vanilla");
  player.riding=false;player.swimming=true;m=new EmoteModelMixin();CALL
  check(m.rightArm.PITCH==0,"Swimming pose remains vanilla");
  player.swimming=false;com.cubeon.client.hud.CubeonHudConfig.get().showEmotes=false;
  m=new EmoteModelMixin();CALL
  check(m.rightArm.PITCH==0,"Display off skips emote pose");
  System.out.println("Bow hip/neck/shoulder seams, animation sweep, remote identity, hats, sit and eligibility passed.");
 }
}'''.replace('BOW_RESET', '''reset.invoke(m,new org.spongepowered.asm.mixin.injection.callback.CallbackInfo());
  near(m.body.POSITION,0,"Leaving bow restores torso origin");near(m.head.PZ,0,"Leaving bow restores head depth");
  near(m.rightArm.POSITION,2,"Leaving bow restores shoulder origin");near(m.rightArm.PZ,0,"Leaving bow restores shoulder depth");
  near(m.hat.POSITION,0,"Leaving bow restores detached hat");''' if era=='entity' else '').replace('PX',positions[0]).replace('PZ',positions[2]).replace('HAT_CHECK', '''check(m.hat.ROLL==m.head.ROLL,"Detached legacy hat follows posed head");''' if era=='entity' else '''check(m.hat.ROLL==0&&m.hat.PITCH==0,"Nested hat and injected 3D mesh retain local identity, inheriting head exactly once");
  for(int pose=0;pose<EmoteState.NAMES.length;pose++){
   EmoteState.reset();EmoteState.sync(java.util.List.of(new Bridge.EmoteEvent(player.UUID().toString(),"BlueFox",EmoteState.NAMES[pose],10,1)));
   m=new EmoteModelMixin();CALL
   check(m.hat.ROLL==0&&m.hat.PITCH==0,"Every emote preserves nested layer transform");
  }
  EmoteState.reset();EmoteState.sync(java.util.List.of(new Bridge.EmoteEvent(player.UUID().toString(),"BlueFox","wave",10,1)));''').replace('HAT_SIT', 'check(m.hat.POSITION==10,"Detached hat follows seated head");' if era=='entity' else 'check(m.hat.POSITION==0,"Nested hat inherits seated translation once");').replace('SIT_RESET', 'reset.invoke(m,new org.spongepowered.asm.mixin.injection.callback.CallbackInfo()); check(m.body.POSITION==0&&m.hat.POSITION==0&&m.rightLeg.POSITION==0,"Leaving sit restores model origins");' if era=='entity' else '').replace('POSITION',position).replace('ACTOR',actor).replace('AVATAR',avatar).replace('UUID()',('getUUID' if mojang else 'getUuid')+'()').replace('CALL',call).replace('PITCH',angles[0]).replace('ROLL',angles[2]).replace('RESET', '''var reset=EmoteModelMixin.class.getDeclaredMethod("cubeon$reset",org.spongepowered.asm.mixin.injection.callback.CallbackInfo.class); reset.setAccessible(true);
  reset.invoke(m,new org.spongepowered.asm.mixin.injection.callback.CallbackInfo());
  check(m.head.roll==0&&m.body.roll==0,"Legacy pose does not accumulate across frames or players");''' if era=='entity' else '')
    paths=[]
    for relative,text in fixtures.items():
     p=folder/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);paths.append(p)
    java=ROOT/'mod/src/main/java/com/cubeon/client'
    paths += [java/'Json.java',java/'Bridge.java',*sorted((java/'emotes').glob('*.java')), *sorted((java/'ui').glob('*.java'))]
    run=subprocess.run(['javac','--release','17','-d',str(folder),*map(str,paths)],capture_output=True,text=True,timeout=60)
    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
    run=subprocess.run(['java','-cp',str(folder),'ModelTest'],capture_output=True,text=True,timeout=60)
    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
    print(era+': '+run.stdout.strip())

if __name__=='__main__':unittest.main()
