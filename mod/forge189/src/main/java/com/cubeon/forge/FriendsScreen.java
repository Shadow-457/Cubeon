package com.cubeon.forge;
import com.cubeon.client.*;
import net.minecraft.client.gui.*;
import org.lwjgl.input.Keyboard;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;

public final class FriendsScreen extends GlassScreen {
    private static final ThreadPoolExecutor ACTIONS=new ThreadPoolExecutor(1,1,10,TimeUnit.SECONDS,
            new ArrayBlockingQueue<Runnable>(8),job->{ Thread t=new Thread(job,"cubeon-forge-actions"); t.setDaemon(true); return t; });
    static { ACTIONS.allowCoreThreadTimeOut(true); }
    private GuiTextField input;
    private final Map<Integer,Bridge.Friend> rows=new HashMap<>();
    private int page;
    private long revision=-1;
    private volatile String status="";
    private volatile boolean busy;
    public FriendsScreen(GuiScreen parent) { super(parent); }
    @Override public void initGui() {
        String typed=input==null?"":input.getText();
        buttonList.clear(); rows.clear();
        int w=Math.min(380,width-32),x=(width-w)/2;
        input=new GuiTextField(900,fontRendererObj,x,42,w-92,18); input.setMaxStringLength(32); input.setText(typed);
        button(1,x+w-88,41,88,"Add by ID");
        List<Bridge.Friend> friends=Bridge.get().snapshot().friends();
        int count=Math.max(1,(height-145)/32); page=Math.max(0,Math.min(page,Math.max(0,(friends.size()-1)/count)));
        for(int i=page*count;i<Math.min(friends.size(),(page+1)*count);i++) {
            int y=75+(i-page*count)*32; Bridge.Friend f=friends.get(i); rows.put(100+i,f);
            button(100+i,x,y,w-130,f.label());
            button(1000+i,x+w-126,y,62,f.invited()?"Join":"Invite"); rows.put(1000+i,f);
            button(2000+i,x+w-60,y,60,"Remove"); rows.put(2000+i,f);
        }
        button(2,x,height-56,w/3-3,"‹ Previous"); button(3,x+w/3,height-56,w/3-3,"Next ›");
        button(4,x+2*w/3,height-56,w/3,"Refresh"); button(0,x,height-32,w,"Back");
        revision=Bridge.get().revision(); Keyboard.enableRepeatEvents(true);
    }
    private void action(String path,String body) {
        if(busy) return; busy=true; status="Working…";
        try { ACTIONS.execute(()->{
            try { Bridge.Result r=Bridge.get().post(path,body); status=r.ok()?"Done":r.error(); Bridge.get().wake(); }
            finally { busy=false; }
        }); } catch(RejectedExecutionException e) { busy=false; status="Please wait for the current action."; }
    }
    @Override protected void actionPerformed(GuiButton b) {
        if(b.id==0) mc.displayGuiScreen(parent);
        else if(b.id==1) action("/add",Json.object("name",input.getText().trim()));
        else if(b.id==2 || b.id==3) { page+=b.id==2?-1:1; initGui(); }
        else if(b.id==4) Bridge.get().wake();
        else if(rows.containsKey(b.id)) {
            Bridge.Friend f=rows.get(b.id);
            if(b.id>=2000) mc.displayGuiScreen(new RemoveScreen(this,f));
            else if(b.id>=1000) action(f.invited()?"/join":"/invite",Json.object("name",f.name()));
            else mc.displayGuiScreen(new ChatScreen(this,f));
        }
    }
    @Override public void updateScreen() { input.updateCursorCounter(); if(revision!=Bridge.get().revision()) initGui(); }
    @Override protected void mouseClicked(int x,int y,int b) { super.mouseClicked(x,y,b); input.mouseClicked(x,y,b); }
    @Override protected void keyTyped(char c,int key) { if(!input.textboxKeyTyped(c,key)) super.keyTyped(c,key); }
    @Override public void onGuiClosed() { Keyboard.enableRepeatEvents(false); }
    @Override public void drawScreen(int x,int y,float p) {
        chrome("Cubeon Friends · "+Bridge.get().snapshot().connectionLine()); input.drawTextBox();
        if(!status.isEmpty()) drawCenteredString(fontRendererObj,status,width/2,height-71,0xffd7e8e2);
        if(rows.isEmpty()) drawCenteredString(fontRendererObj,"Add a friend using their eight-digit Cubeon ID",width/2,90,0xffb9ccc6);
        super.drawScreen(x,y,p);
    }
    private static final class RemoveScreen extends GlassScreen {
        private final FriendsScreen owner; private final Bridge.Friend friend;
        RemoveScreen(FriendsScreen owner,Bridge.Friend friend) { super(owner); this.owner=owner; this.friend=friend; }
        @Override public void initGui() { button(1,width/2-96,height/2,92,"Remove"); button(0,width/2+4,height/2,92,"Cancel"); }
        @Override protected void actionPerformed(GuiButton b) { if(b.id==1) owner.action("/remove",Json.object("name",friend.name())); mc.displayGuiScreen(owner); }
        @Override public void drawScreen(int x,int y,float p) { chrome("Remove "+friend.label()+" from friends?"); super.drawScreen(x,y,p); }
    }
    private static final class ChatScreen extends GlassScreen {
        private final Bridge.Friend friend; private GuiTextField text;
        private long sent;
        ChatScreen(GuiScreen parent,Bridge.Friend friend) { super(parent); this.friend=friend; }
        @Override public void initGui() {
            String draft=text==null?"":text.getText(); buttonList.clear();
            text=new GuiTextField(901,fontRendererObj,16,height-54,width-104,18); text.setMaxStringLength(1000); text.setText(draft); text.setFocused(true);
            button(1,width-82,height-55,66,"Send"); button(0,16,height-31,width-32,"Back");
            Bridge.get().openChat(friend.name()); Keyboard.enableRepeatEvents(true);
        }
        private void send() { if(sent==0) sent=Bridge.get().sendChat(friend.name(),text.getText()); }
        @Override protected void actionPerformed(GuiButton b) { if(b.id==0) mc.displayGuiScreen(parent); else send(); }
        @Override public void updateScreen() {
            text.updateCursorCounter(); Bridge.ChatSent r=Bridge.get().chatSent();
            if(sent!=0 && r.id()==sent) { if(r.result().ok() && r.text().equals(text.getText().trim())) text.setText(""); sent=0; }
        }
        @Override protected void mouseClicked(int x,int y,int b) { super.mouseClicked(x,y,b); text.mouseClicked(x,y,b); }
        @Override protected void keyTyped(char c,int key) {
            if(key==28) send(); else if(!text.textboxKeyTyped(c,key)) super.keyTyped(c,key);
        }
        @Override public void onGuiClosed() { Bridge.get().closeChat(); Keyboard.enableRepeatEvents(false); }
        @Override public void drawScreen(int x,int y,float p) {
            chrome("Chat · "+friend.label());
            Bridge.ChatView chat=Bridge.get().chat(); List<String> lines=new ArrayList<>();
            if(chat.peer().equals(friend.name())) for(Bridge.ChatMessage m:chat.messages())
                lines.addAll(fontRendererObj.listFormattedStringToWidth(("out".equals(m.direction())?"You: ":friend.displayName()+": ")+m.text(),width-36));
            int count=Math.max(1,(height-115)/11),start=Math.max(0,lines.size()-count);
            for(int i=start;i<lines.size();i++) fontRendererObj.drawString(lines.get(i),18,40+(i-start)*11,0xffe6f1ed);
            if(!chat.error().isEmpty()) drawCenteredString(fontRendererObj,chat.error(),width/2,height-69,0xffffbdb1);
            text.drawTextBox(); super.drawScreen(x,y,p);
        }
    }
}
