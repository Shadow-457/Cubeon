"""Relay lifecycle and production Java poses for two Cubeon clients."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cubeon.emotes import EmoteRelay

class Client:
    is_connected=True
    def __init__(self): self.sent=[]
    def send_emote_room(self,room): self.sent.append(('room',room)); return self.is_connected
    def send_emote(self,*args): self.sent.append(args); return self.is_connected

class RelayTests(unittest.TestCase):
    def setUp(self):
        self.now=10.0; self.client=Client(); self.relay=EmoteRelay(self.client,clock=lambda:self.now)
        self.room='a'*64; self.entity=str(uuid.uuid4())
        self.relay.context({'room':self.room}); self.relay.acknowledge({'room':self.room,'ready':True})
    def frame(self,**patch):
        return dict(room=self.room,uuid=self.entity,username='BlueFox',emote='wave',serial=1,age=0)|patch
    def test_receive_expiry_and_stop(self):
        self.relay.receive(self.frame(age=.5)); self.now+=.5
        self.assertEqual(self.relay.snapshot()['active'][0]['age'],1)
        self.relay.receive(self.frame(age=0))
        self.assertEqual(self.relay.snapshot()['active'][0]['age'],1,'duplicate cannot restart pose')
        self.now+=2; self.assertEqual(self.relay.snapshot()['active'],[])
        self.relay.receive(self.frame(serial=2)); self.relay.receive(self.frame(emote='stop',serial=3))
        self.assertEqual(self.relay.snapshot()['active'],[])
    def test_reject_bad_and_other_room(self):
        for patch in ({'room':'b'*64},{'uuid':'bad'},{'username':'bad user'}, {'emote':[]},
                      {'age':float('nan')},{'age':-1},{'serial':True},{'serial':1.5},{'emote':'unknown'}):
            self.relay.receive(self.frame(**patch))
        self.assertEqual(self.relay.snapshot()['active'],[])
        self.assertFalse(self.relay.context({'room':'raw-server-address'})['ok'])
    def test_connection_clear_and_rejoin(self):
        self.relay.receive(self.frame()); self.relay.connection(False)
        self.assertFalse(self.relay.snapshot()['ready']); self.assertEqual(self.relay.snapshot()['active'],[])
        self.relay.connection(True); self.assertEqual(self.client.sent[-1],('room',self.room))
        self.relay.acknowledge({'room':'wrong','ready':True}); self.assertFalse(self.relay.snapshot()['ready'])
        self.relay.context({'room':'b'*64}); self.assertEqual(self.relay.snapshot()['room'],'b'*64)
    def test_send_throttle_and_old_backend(self):
        body={'uuid':self.entity,'emote':'wave','serial':1}
        self.assertTrue(self.relay.play(body)['ok']); self.assertFalse(self.relay.play(body)['ok'])
        self.assertTrue(self.relay.play(body|{'emote':'stop','serial':2})['ok'])
        self.relay.ready=False; self.assertFalse(self.relay.play(body)['ok'])
        self.now+=46; self.assertFalse(self.relay.snapshot()['ready'])

HARNESS=r'''
import com.cubeon.client.Bridge;
import com.cubeon.client.emotes.*;
import java.util.*;
public class EmoteTest {
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static Bridge.EmoteEvent event(UUID uuid,int serial,float age){return new Bridge.EmoteEvent(uuid.toString(),"BlueFox","wave",serial,age);}
 public static void main(String[] args){
  var actor=UUID.randomUUID(); var viewer=UUID.randomUUID();
  check(EmoteRoom.hash("PLAY.EXAMPLE.COM:25565").equals(EmoteRoom.hash("play.example.com")),"Canonical room");
  check(!EmoteRoom.hash("play.example.com:25566").equals(EmoteRoom.hash("play.example.com")),"Separate ports");
  int seq=EmoteState.play(actor,"BlueFox",0); EmoteState.tick();
  check(EmoteState.frame(actor,"BlueFox",.5f)!=null,"Local pose plays instantly");
  check(EmoteState.frame(viewer,"RubyFox",.5f)==null,"Does not dress another player");
  check(EmoteState.frame(actor,"WrongName",.5f)==null,"UUID and username must both match");
  EmoteState.sync(List.of(event(actor,seq,0)));
  var first=EmoteState.frame(actor,"BlueFox",.5f).weight;
  EmoteState.tick(); EmoteState.sync(List.of(event(actor,seq,0)));
  check(EmoteState.frame(actor,"BlueFox",.5f).weight>first,"Echo does not restart animation");
  EmoteState.play(actor,"BlueFox",-1);
  EmoteState.sync(List.of(event(actor,seq,0)));
  check(!EmoteState.playing(actor),"Late echo cannot undo stop");
  EmoteState.reset(); EmoteState.sync(List.of(event(actor,20,1)));
  check(EmoteState.frame(actor,"BlueFox",.5f).weight==1,"Remote joins mid-emote");
  EmoteState.sync(List.of()); check(!EmoteState.active(),"Remote stop propagates");
  for(int e=0;e<6;e++) {
   int serial=EmoteState.play(actor,"BlueFox",e);
   for(int i=0;i<140;i++) {
    EmoteState.tick(); var pose=EmoteState.frame(actor,"BlueFox",.5f);
    if(pose!=null)for(int part=0;part<6;part++)for(int axis=0;axis<3;axis++)
      check(Float.isFinite(pose.blend(part,axis,.1f)),"Finite pose");
   }
   check(!EmoteState.active(),"Finite duration");
   var start=EmotePose.sample(e,0,3); var end=EmotePose.sample(e,3,3);
   check(start.weight==0&&end.weight==0,"Smooth start and end");
  }
  System.out.println("Emote poses, identity, instant local start, authoritative echo, delayed stop, late join, expiry and room hashing passed.");
 }
}
'''

@unittest.skipUnless(shutil.which('javac') and shutil.which('java'),'JDK required')
class JavaTests(unittest.TestCase):
    def test_production_poses(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);harness=folder/'EmoteTest.java';harness.write_text(HARNESS)
            java=ROOT/'mod/src/main/java/com/cubeon/client'
            sources=[java/'Json.java',java/'Bridge.java',*sorted((java/'emotes').glob('*.java')),harness]
            run=subprocess.run(['javac','--release','17','-d',str(folder),*map(str,sources)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            run=subprocess.run(['java','-cp',str(folder),'EmoteTest'],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            print(run.stdout.strip())

if __name__=='__main__': unittest.main()
