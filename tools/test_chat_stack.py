"""Run the production bounded chat policy; check real native injection targets on request."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import tempfile

from test_mod_bridge import find_jdk

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import com.cubeon.client.chat.ChatStack;
import java.util.*;
public class StackTest {
 static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
 record Line(String text,boolean end){}
 public static void main(String[] args)throws Exception {
  ChatStack stack=new ChatStack();Object connection=new Object(),head=new Object();
  var original=new ArrayList<String>();var displayed=new ArrayList<Line>();
  for(int n=1;n<=4;n++){
   String raw=new String("<Alice> hello");original.add(raw);
   int count=stack.accept(raw,"signed","trusted",n,connection,displayed.isEmpty()?null:displayed.get(0));
   if(count>1)ChatStack.removeLatest(displayed,Line::end);
   displayed.add(0,new Line(raw+(count>1?" ×"+count:""),true));stack.rememberHead(displayed.get(0));
  }
  check(original.size()==4&&displayed.size()==1&&displayed.get(0).text().endsWith("×4"),"four raw messages, one displayed entry");
  check(stack.accept("<Bob> hello","signed","trusted",5,connection,displayed.get(0))==1,"different sender resets");
  stack.rememberHead(head);
  check(stack.accept("<Bob> hello","system","trusted",6,connection,head)==1,"different source resets");
  check(stack.accept("<Bob> hello","system","untrusted",7,connection,head)==1,"different indicator resets");
  check(stack.accept("<Bob> hello","system","untrusted",8,new Object(),head)==1,"server switch resets");
  check(stack.accept("<Bob> hello","system","untrusted",9,connection,head)==1,"connection identity");
  check(stack.accept("<Bob> hello","system","untrusted",210,connection,head)==1,"ten second gap resets");
  check(stack.accept("<Bob> hello","system","untrusted",2,connection,head)==1,"backwards time resets");
  check(stack.accept("<Bob> hello","system","untrusted",3,connection,new Object())==1,"another mod's head fails closed");
  var wrapped=new ArrayList<>(List.of(new Line("new last",true),new Line("new middle",false),new Line("new first",false),new Line("old last",true),new Line("old first",false)));
  check(ChatStack.removeLatest(wrapped,Line::end)==3&&wrapped.size()==2&&wrapped.get(0).text().equals("old last"),"wrapped removal stops at next native entry");
  check(ChatStack.removeLatest(new ArrayList<Line>(),Line::end)==0,"empty queue safe");
  stack.reset();
  check(stack.accept("hello","system",null,1,connection,head)==1,"refresh starts raw replay");stack.rememberHead(head);
  check(stack.accept("hello","system",null,2,connection,head)==2,"refresh reconstructs same run");
  var count=ChatStack.class.getDeclaredField("count");count.setAccessible(true);count.setInt(stack,Integer.MAX_VALUE);
  check(stack.accept("hello","system",null,3,connection,head)==Integer.MAX_VALUE,"counter saturates");
  stack.reset();
  for(var f:ChatStack.class.getDeclaredFields())if(f.getType()==Object.class){f.setAccessible(true);check(f.get(stack)==null,"reset releases retained references");}
  System.out.println("Chat stacking policy passed");
 }
}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--targets', action='store_true')
    args = parser.parse_args()
    javac, java = find_jdk()
    if not javac:
        print('SKIP: JDK required'); return 0
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp); (folder/'StackTest.java').write_text(HARNESS)
        subprocess.run([javac, '--release', '17', '-d', temp, str(ROOT/'mod/src/main/java/com/cubeon/client/chat/ChatStack.java'), str(folder/'StackTest.java')], check=True)
        subprocess.run([java, '-cp', temp, 'StackTest'], check=True)
    if args.targets:
        jars = list((ROOT/'mod/.gradle/loom-cache/minecraftMaven').rglob('*.jar'))
        for bracket in json.loads((ROOT/'mod/brackets.json').read_text())['brackets']:
            # The matrix's bracket keys are the builder's actual mcVersion selectors.
            version = bracket['key']
            matches = [p for p in jars if ('/'+version+('-' if version.startswith('1.') else '/')) in str(p)]
            if not matches: raise AssertionError('Missing mapped jar for '+version)
            era = 'mojang' if version.startswith('26.') else 'yarn-legacy' if version in ('1.20','1.20.1','1.20.2','1.20.3','1.20.4') else 'yarn'
            cls = 'net.minecraft.client.gui.components.ChatComponent' if era=='mojang' else 'net.minecraft.client.gui.hud.ChatHud'
            result = subprocess.run([str(Path(javac).with_name('javap')), '-private', '-c', '-cp', str(matches[0]), cls], capture_output=True, text=True)
            if result.returncode: # Some packaged JDKs omit javap.
                result = subprocess.run(['javap','-private','-c','-cp',str(matches[0]),cls],capture_output=True,text=True)
            target = 'addMessageToDisplayQueue' if era=='mojang' else 'addVisibleMessage' if era=='yarn' else 'addMessage(net.minecraft.text.Text, net.minecraft.network.message.MessageSignatureData, int, net.minecraft.client.gui.hud.MessageIndicator, boolean)'
            assert target in result.stdout, (version, target)
            for field in (('trimmedMessages','chatScrollbarPos') if era=='mojang' else ('visibleMessages','scrolledLines')): assert field in result.stdout,(version,field)
        print('All native chat target seams verified')
    return 0

if __name__=='__main__': sys.exit(main())
