package com.cubeon.forge;

import com.cubeon.client.hud.*;
import net.minecraft.client.gui.*;
import java.io.IOException;
import java.util.*;

public final class ClientScreen extends GlassScreen {
    private int category, page;
    private final Map<Integer,String> toggles=new HashMap<>();
    private final Map<Integer,HudFeatures> overlays=new HashMap<>();
    private static final String[][] OPTIONS={
        {"showEnemyHealth","Enemy health"},{"autoSprint","Auto sprint"},{"worldClock","World clock"},
        {"cosmeticAnimations","Cosmetic animation"},{"wingDepth","Wing depth"},{"showOtherCosmetics","Other player cosmetics"},
        {"showEmotes","Player emotes"},{"cameraMotionBlur","Camera motion blur"},
        {"showArmorHelmet","Helmet"},{"showArmorChest","Chestplate"},{"showArmorLegs","Leggings"},{"showArmorFeet","Boots"}
    };
    public ClientScreen(GuiScreen parent) { super(parent); }
    @Override public void initGui() {
        buttonList.clear(); toggles.clear(); overlays.clear();
        int w=Math.min(290,width-32), x=(width-w)/2;
        button(1,x,36,w/2-2,"HUD"); button(2,x+w/2+2,36,w/2-2,"Settings");
        int rows=Math.max(1,(height-152)/23), count=category==0?HudFeatures.ALL.length:OPTIONS.length;
        page=Math.max(0,Math.min(page,(count-1)/rows));
        CubeonHudConfig c=CubeonHudConfig.get();
        for(int i=page*rows;i<Math.min(count,(page+1)*rows);i++) {
            int y=64+(i-page*rows)*23;
            if(category==0) {
                HudFeatures f=HudFeatures.ALL[i]; int id=100+i; overlays.put(id,f);
                button(id,x,y,w,Hud189.label(f)+": "+(Hud189.enabled(f)?"On":"Off"));
            } else {
                String field=OPTIONS[i][0]; int id=200+i; toggles.put(id,field);
                boolean on=false; try { on=CubeonHudConfig.class.getField(field).getBoolean(c); } catch(Exception ignored) { }
                button(id,x,y,w,OPTIONS[i][1]+": "+(on?"On":"Off"));
            }
        }
        button(3,x,height-82,w/2-2,"‹ Previous"); button(4,x+w/2+2,height-82,w/2-2,"Next ›");
        button(5,x,height-59,w/2-2,"Edit HUD"); button(6,x+w/2+2,height-59,w/2-2,"Friends / Chat");
        button(7,x,height-36,w/2-2,"Zoom: "+c.zoomFactor+"×"); button(0,x+w/2+2,height-36,w/2-2,"Done");
    }
    @Override protected void actionPerformed(GuiButton b) {
        if(b.id==0) mc.displayGuiScreen(parent);
        else if(b.id==1 || b.id==2) { category=b.id-1; page=0; initGui(); }
        else if(b.id==3 || b.id==4) { page+=b.id==3?-1:1; initGui(); }
        else if(b.id==5) mc.displayGuiScreen(new HudEditor(this));
        else if(b.id==6) mc.displayGuiScreen(new FriendsScreen(this));
        else if(b.id==7) { CubeonHudConfig c=CubeonHudConfig.get(); c.zoomFactor=c.zoomFactor>=8?1.5f:c.zoomFactor+.5f; CubeonHudConfig.save(); initGui(); }
        else if(overlays.containsKey(b.id)) { Hud189.toggle(overlays.get(b.id)); initGui(); }
        else if(toggles.containsKey(b.id)) {
            try { java.lang.reflect.Field f=CubeonHudConfig.class.getField(toggles.get(b.id)); f.setBoolean(CubeonHudConfig.get(),!f.getBoolean(CubeonHudConfig.get())); CubeonHudConfig.save(); }
            catch(ReflectiveOperationException e) { throw new IllegalStateException(e); }
            initGui();
        }
    }
    @Override public void drawScreen(int x,int y,float partial) { chrome("Cubeon Client · Forge 1.8.9"); super.drawScreen(x,y,partial); }
}
