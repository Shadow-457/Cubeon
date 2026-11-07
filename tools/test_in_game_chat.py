"""Real local API + Java bridge + encrypted service: synchronized chat and custom UI bounds."""
from pathlib import Path
import http.client
import json
import os
import runpy
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_mod_bridge import find_jdk
import _sandbox_home
_sandbox_home.isolate()

HARNESS = r'''
package com.cubeon.client;
import com.cubeon.client.ui.*;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.nio.file.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import javax.imageio.ImageIO;
public class FriendsChatTest {
 static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
 static void await(BooleanSupplier ready,String m)throws Exception{
  long end=System.nanoTime()+8_000_000_000L;
  while(!ready.getAsBoolean()&&System.nanoTime()<end)Thread.sleep(20);
  check(ready.getAsBoolean(),m);
 }
 static class Canvas implements ClientUi.Canvas {
  final int w,h;final BufferedImage image;final Graphics2D g;final Map<String,Object> labels;
  int calls, widthCalls, greenTints;final Map<String,BufferedImage> assets=new HashMap<>();
  void color(int color){if((color&0xFFFFFF)==0x8DBA83)return;if(((color>>>8)&255)>Math.max((color>>>16)&255,color&255)+10)greenTints++;}
  Canvas(int w,int h,String font,String language)throws Exception{
   this.w=w;this.h=h;image=new BufferedImage(w*3,h*3,BufferedImage.TYPE_INT_ARGB);g=image.createGraphics();g.scale(3,3);
   g.setFont(Font.createFont(Font.TRUETYPE_FONT,new java.io.File(font)).deriveFont(9f));
   g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
   labels=Json.parseObject(Files.readString(Path.of(language)));
  }
  public String translate(String key){return Json.str(labels,key,key);}
  public int width(String value){widthCalls++;return g.getFontMetrics().stringWidth(value);}
  public void fill(int x0,int y0,int x1,int y1,int color){
   color(color);
   check(x0>=0&&y0>=0&&x1<=w&&y1<=h&&x0<=x1&&y0<=y1,"quads remain in screen");
   g.setColor(new Color(color,true));g.fillRect(x0,y0,x1-x0,y1-y0);calls++;
  }
  public void text(String text,int x,int y,int color){
   color(color);
   check(x-width(text)/2>=0&&x+(width(text)+1)/2<=w&&y>=0&&y+9<=h,"text bounds: "+text);
   g.setColor(new Color(color,true));g.drawString(text,x-width(text)/2,y+8);calls++;
  }
  public boolean textures(){return true;}
  public void image(String path,int x,int y,int w,int h,int u,int v,int rw,int rh,int tw,int th,int color){
   color(color);
   check(x>=0&&y>=0&&x+w<=this.w&&y+h<=this.h,"texture bounds");
   try{
    var atlas=assets.get(path);if(atlas==null){atlas=ImageIO.read(Path.of(System.getProperty("cubeon.ui.assets"),path).toFile());assets.put(path,atlas);}
    check(atlas.getWidth()==tw&&atlas.getHeight()==th,"bundled texture seam");
    var op=new java.awt.image.RescaleOp(new float[]{((color>>>16)&255)/255f,((color>>>8)&255)/255f,(color&255)/255f,(color>>>24)/255f},new float[4],null);
    var tinted=op.filter(atlas.getSubimage(u,v,rw,rh),null);
    g.drawImage(tinted,x,y,x+w,y+h,0,0,rw,rh,null);calls++;
   }catch(Exception e){throw new RuntimeException(e);}
  }
 }
 public static void main(String[] args)throws Exception{
  Bridge bridge=Bridge.get();bridge.start();await(()->bridge.snapshot().connected(),"real authenticated roster");
  FriendsPanel panel=new FriendsPanel(bridge);check(panel.ensurePeer(),"first friend selected");
  await(()->bridge.chat().messages().size()==1,"launcher transcript read in Minecraft");
  check(bridge.chat().messages().get(0).text().equals("From the launcher"),"same store payload");
  long start=System.nanoTime();check(panel.send("Minecraft → launcher 😀"),"send queued");
  check(System.nanoTime()-start<100_000_000L,"input does not perform slow encryption/HTTP");
  check(!panel.send("duplicate click"),"single in-flight send");
  await(()->bridge.chatSent().id()>0,"asynchronous send reply");
  check(panel.completed("Minecraft → launcher 😀"),"accepted unchanged draft cleared");
  await(()->bridge.chat().messages().size()==2,"echo appears once");
  check(bridge.chat().messages().get(1).direction().equals("out"),"actual dir field honored");
  check(panel.send("deny"),"rejected send attempted");long first=bridge.chatSent().id();
  await(()->bridge.chatSent().id()>first,"rejection completed");
  check(!panel.completed("deny")&&panel.draft().equals("deny"),"failed send keeps draft");
  check(bridge.chat().messages().size()==2,"refused message never enters history");
  long previous=bridge.chatSent().id();check(panel.send("close during send"),"closing send queued");panel.close();
  await(()->bridge.chatSent().id()>previous,"send finishes with screen closed");
  panel=new FriendsPanel(bridge);check(panel.ensurePeer(),"reopened conversation");
  check(panel.draft().isEmpty(),"accepted closed-screen draft is not offered for duplicate resend");
  await(()->bridge.chat().messages().size()==3,"reopened transcript synchronized");
  panel.saveDraft("work in progress");panel.select(1);panel.saveDraft("Bob's draft");panel.select(0);
  check(panel.draft().equals("work in progress"),"drafts survive friend switches");
  for(int[] size:new int[][]{{320,240},{640,360},{960,540}}){
   Canvas canvas=new Canvas(size[0],size[1],args[0],args[1]);panel.layout(size[0],size[1]);Thread.sleep(180);
   panel.render(canvas,size[0],size[1],0,0);
   check(panel.inputWidth()>80&&panel.inputX()+panel.inputWidth()<size[0],"composer fits minimum GUI");
   check(canvas.calls<200,"only visible rows drawn");
   check(canvas.greenTints>0,"Chat controls use Cubeon green accents");
   if(Boolean.getBoolean("cubeon.ui.capture"))ImageIO.write(canvas.image,"png",Path.of(args[2],"friends-"+size[1]+".png").toFile());
  }
  var transcriptField=Bridge.class.getDeclaredField("chat");transcriptField.setAccessible(true);
  var transcriptLock=Bridge.class.getDeclaredField("chatLock");transcriptLock.setAccessible(true);
  synchronized(transcriptLock.get(bridge)) {
   Object saved=transcriptField.get(bridge);
   try {
    var rows=new ArrayList<Bridge.ChatMessage>();
    for(int i=0;i<150;i++)rows.add(new Bridge.ChatMessage(i,i%2==0?"out":"in","Message "+i+": this is a long conversation with readable wrapped lines."));
    transcriptField.set(bridge,new Bridge.ChatView("alice",java.util.List.copyOf(rows),false,false,""));
    Canvas full=new Canvas(640,360,args[0],args[1]);panel.render(full,640,360,0,0);
    rows.add(new Bridge.ChatMessage(150,"in","Only this new line should be wrapped."));
    transcriptField.set(bridge,new Bridge.ChatView("alice",java.util.List.copyOf(rows),false,false,""));
    Canvas incremental=new Canvas(640,360,args[0],args[1]);panel.render(incremental,640,360,0,0);
    check(incremental.widthCalls<200,"new message does not remeasure the existing transcript");
    var longMessage=new Bridge.ChatMessage(999,"out","Unicode 😀 long line ".repeat(50));
    transcriptField.set(bridge,new Bridge.ChatView("alice",java.util.List.of(longMessage),false,false,""));
    for(int[] size:new int[][]{{320,240},{640,360}}) {
     Canvas clipped=new Canvas(size[0],size[1],args[0],args[1]);panel.render(clipped,size[0],size[1],0,0);
     check(clipped.calls<200,"long bubbles draw only viewport rows");
     clipped.calls=0;panel.scroll(panel.inputX(),1);panel.render(clipped,size[0],size[1],0,0);
     check(clipped.calls<200,"scrolling a long bubble still draws only viewport rows");
    }
   } finally {transcriptField.set(bridge,saved);}
  }
  var q=ClientToasts.class.getDeclaredField("queue");q.setAccessible(true);ClientToasts.clear();
  ClientToasts.accept(new Bridge.Toast(1,"Friend invited you",false));ClientToasts.accept(new Bridge.Toast(2,"Friend invited you",false));
  check(((java.util.Deque<?>)q.get(null)).size()==1,"toast dedupe");
  for(int i=0;i<20;i++)ClientToasts.accept(new Bridge.Toast(i,"Notice "+i,false));
  check(((java.util.Deque<?>)q.get(null)).size()==6,"toast queue bounded");
  Canvas canvas=new Canvas(640,360,args[0],args[1]);Thread.sleep(200);ClientToasts.render(canvas,640,360);
  if(Boolean.getBoolean("cubeon.ui.capture"))ImageIO.write(canvas.image,"png",Path.of(args[2],"toasts.png").toFile());
  Thread.sleep(5050);Canvas expired=new Canvas(640,360,args[0],args[1]);ClientToasts.render(expired,640,360);
  check(expired.calls==0,"expired toasts cause no drawing");
  // A queued message cannot cross a refreshed account identity.
  var lockField=Bridge.class.getDeclaredField("chatLock");lockField.setAccessible(true);
  var currentField=Bridge.class.getDeclaredField("current");currentField.setAccessible(true);
  long rejected;
  synchronized(lockField.get(bridge)) {
   rejected=bridge.sendChat("alice","wrong account");check(rejected>0,"account-race fixture queued");
   currentField.set(bridge,Bridge.parseSnapshot("{\"you\":\"Other\",\"connected\":true,\"available\":true}"));
  }
  await(()->bridge.chatSent().id()==rejected,"account-race request resolves");
  check(!bridge.chatSent().result().ok(),"account-race draft rejected before HTTP send");
  panel.close();System.out.println("Encrypted cross-view chat, drafts, account gate, bounds and toast lifecycle passed");
 }
}
'''

def main():
    javac, java = find_jdk()
    if not javac:
        print('SKIP: JDK required'); return 0
    fixtures = runpy.run_path(str(ROOT/'tools/test_friends_service.py'), run_name='chat_bridge_fixtures')
    fixtures['_identity_on_disk']()
    service, client, _ = fixtures['build']()
    _, alice_pub = fixtures['_alice_keypair']()
    client.pubkeys['alice'] = alice_pub
    client.roster['friends'] = [dict(name='alice', online=True, minecraft_username='Alice', uid='12345678'),
                                dict(name='bob', online=False, minecraft_username='Bob', uid='87654321')]
    service._chat_append('alice', 'in', 'Alice', 'From the launcher', 1, mid='launcher-first')
    send_dm = client.send_dm
    def echo(peer, envelope):
        # Slow transport exercises the render-thread gate, real encrypted send and shared echo.
        sent = send_dm(peer, envelope)
        import threading
        def acknowledge():
            time.sleep(.3)
            client.fire('dm', {'from':'New nickname', 'to':'Changed display', 'text':envelope, 'ts':1})
        thread = threading.Thread(target=acknowledge, daemon=True); thread.start()
        return sent
    client.send_dm = echo
    original_send = service.send_chat
    sent = []
    def send(peer, text, **kwargs):
        sent.append((peer, text))
        if text == 'deny': return {'ok':False, 'error':'Fixture refused the message'}
        return original_send(peer, text, **kwargs)
    service.send_chat = send
    service.start()
    api = fixtures['local_api']; server = api.start._server
    # Launcher viewing and Minecraft viewing are independent owners.
    service.set_open_conversation('Alice', viewer='launcher')
    def post_close(token):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
        conn.request('POST','/chatclose',json.dumps({'name':'Alice'}),{'X-Cubeon-Token':token})
        response = conn.getresponse(); result=(response.status, json.loads(response.read())); conn.close(); return result
    try:
        assert post_close('wrong')[0] == 401
        service.set_open_conversation('Alice', viewer='bridge')
        assert post_close(server.token)[1]['ok']
        assert ('launcher','alice') in service._chat_open and ('bridge','alice') not in service._chat_open
        # Register both a real launcher send and the Java mod against one ring.
        assert service.send_bridge_chat('alice', 'Launcher send seed')['ok']
        # Clear seed solely to give the Java fixture a predictable first page.
        with service._chat_lock:
            service._chat['alice']['msgs'].pop()
        sent.clear()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); harness=folder/'FriendsChatTest.java'; harness.write_text(HARNESS)
            files=[ROOT/'mod/src/main/java/com/cubeon/client'/f for f in ('Bridge.java','Json.java','ui/ClientUi.java','ui/ClientTheme.java','ui/MenuUi.java','ui/FriendsPanel.java','ui/ClientToasts.java')]
            subprocess.run([javac,'--release','17','-d',temp,*map(str,files),str(harness)],check=True)
            captures=ROOT/'archive/ui-captures/in-game-friends'
            if os.environ.get('CUBEON_UI_CAPTURE') == '1': captures.mkdir(parents=True,exist_ok=True)
            font=ROOT/'mod/src/main/resources/assets/cubeon-client/font/inter-ui.ttf'
            if not font.exists(): font=next((ROOT/'mod/src/main/resources/assets/cubeon-client/font').glob('*.ttf'))
            subprocess.run([java,f'-Duser.home={Path(api._TOKEN_FILE).parent.parent}',
                            *(['-Dcubeon.ui.capture=true'] if os.environ.get('CUBEON_UI_CAPTURE') == '1' else []),
                            f'-Dcubeon.ui.assets={ROOT}/mod/src/main/resources/assets/cubeon-client',
                            '-cp',temp,'com.cubeon.client.FriendsChatTest',str(font),
                            str(ROOT/'mod/src/main/resources/assets/cubeon-client/lang/en_us.json'),str(captures)],check=True,timeout=60)
        messages=service.chat_payload('Alice',-1,viewing=False)['messages']
        import threading, types
        import flet as ft
        import ui.chat_tab as chat_ui
        from cubeon.theme import THEME, section_label
        class Page:
            overlay = []; width = 1200
            def update(self, *args): pass
            def run_task(self, *args): pass
        def walk(control):
            yield control
            for child in getattr(control, 'controls', None) or []: yield from walk(child)
            child = getattr(control, 'content', None)
            if child is not None: yield from walk(child)
        real_start = threading.Thread.start
        try:
            threading.Thread.start = lambda self: None  # only suppress this UI's poller
            root, refresh = chat_ui.build_chat_tab(Page(), service.cfg, service.state, service,
                section_label=section_label, **THEME)
        finally:
            threading.Thread.start = real_start
        refresh()
        candidates = [control for control in walk(root)
            if callable(getattr(control, 'on_click', None))
            and any(getattr(child, 'value', None) == 'Alice' for child in walk(control))]
        assert candidates, 'real launcher roster includes Alice'
        row = min(candidates, key=lambda control: sum(1 for _ in walk(control)))
        row.on_click(types.SimpleNamespace(control=row)); refresh()
        assert sum(getattr(control, 'value', None) == 'Minecraft → launcher 😀'
                   for control in walk(root)) == 1, 'game send renders once in real launcher Chat'
        print('Java game send renders in the actual launcher conversation')
        assert sum(m['text']=='Minecraft → launcher 😀' for m in messages)==1
        assert len(sent)==3 and all(text!='duplicate click' for _,text in sent)
        assert all('Minecraft → launcher' not in body for kind, args in client.sent if kind=='dm' for body in [args[1]])
        assert len(client.history_requests) <= 3, 'localhost polls must not spam relay history requests'
        # Live alerts fire once only when neither view is showing the conversation.
        e2ee = fixtures['e2ee']
        alice_priv, _ = fixtures['_alice_keypair']()
        mine_pub = e2ee.public_key_b64(service._e2ee_priv)
        def incoming(mid):
            envelope = e2ee.encrypt_dm(alice_priv, mine_pub, 'Alice', 'Steve', 'live notice')
            client.fire('dm', {'from':'Alice', 'text':json.dumps(envelope), 'id':mid})
            return envelope
        service.close_bridge_chat('alice')
        service.set_open_conversation('alice', viewer='launcher')
        cursor = service.events_since(-1)['cursor']
        incoming('visible-notice')
        assert service.events_since(cursor)['events'] == []
        service.set_open_conversation('alice', viewer='launcher', open_=False)
        envelope = incoming('single-notice')
        assert len(service.events_since(cursor)['events']) == 1
        cursor = service.events_since(-1)['cursor']
        service._notice_seen.clear()  # Prove message-ID dedupe, not merely toast-time dedupe.
        client.fire('dm', {'from':'Alice','text':json.dumps(envelope),'id':'single-notice'})
        assert service.events_since(cursor)['events'] == []
        print('Shared encrypted service, API authentication, independent viewers and live-notice dedupe passed')
    finally:
        service.stop()
    return 0

if __name__=='__main__':sys.exit(main())
