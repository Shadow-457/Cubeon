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
    position='y' if mojang else 'originY' if era=='origin' else 'pivotY'
    add(part,'{ public float '+','.join((*angles,position))+'; public void copyTransform(ModelPart other) {'+' '.join(f'{a}=other.{a};' for a in (*angles,position))+'} }')
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
  EmoteState.reset(); EmoteState.sync(java.util.List.of(new Bridge.EmoteEvent(player.UUID().toString(),"BlueFox","wave",23,1)));
  player.riding=true;m=new EmoteModelMixin();CALL
  check(m.rightArm.PITCH==0,"Riding pose remains vanilla");
  player.riding=false;player.swimming=true;m=new EmoteModelMixin();CALL
  check(m.rightArm.PITCH==0,"Swimming pose remains vanilla");
  player.swimming=false;com.cubeon.client.hud.CubeonHudConfig.get().showEmotes=false;
  m=new EmoteModelMixin();CALL
  check(m.rightArm.PITCH==0,"Display off skips emote pose");
  System.out.println("Remote wave, identity matching, hat, riding/swimming and display-off passed.");
 }
}'''.replace('HAT_CHECK', '''check(m.hat.ROLL==m.head.ROLL,"Detached legacy hat follows posed head");''' if era=='entity' else '''check(m.hat.ROLL==0&&m.hat.PITCH==0,"Nested hat and injected 3D mesh retain local identity, inheriting head exactly once");
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
