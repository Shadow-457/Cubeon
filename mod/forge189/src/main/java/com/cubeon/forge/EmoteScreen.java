package com.cubeon.forge;
import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.emotes.*;
import java.io.IOException;

public final class EmoteScreen extends GlassScreen {
    private int selected=-1;
    private String[] favorites;
    public EmoteScreen() { super(null); }
    @Override public void initGui() { favorites=EmoteFavorites.normalize(CubeonHudConfig.get().emoteFavorites); }
    @Override public void drawScreen(int x,int y,float partial) {
        drawRect(0,0,width,height,0x70202a30);
        int cx=width/2,cy=height/2; double dx=x-cx,dy=y-cy;
        selected=dx*dx+dy*dy<225?-1:(int)Math.floor((Math.atan2(dx,-dy)+Math.PI*2+Math.PI/8)%(Math.PI*2)/(Math.PI/4));
        int radius=Math.max(35,Math.min(75,Math.min(width,height)/3));
        for(int i=0;i<8;i++) {
            double a=i*Math.PI/4; int px=cx+(int)(Math.sin(a)*radius),py=cy-(int)(Math.cos(a)*radius);
            drawRect(px-29,py-11,px+29,py+11,i==selected?0xd04e8878:0xb0283c42);
            drawCenteredString(fontRendererObj,favorites[i],px,py-4,0xffe8f5f2);
        }
        drawCenteredString(fontRendererObj,"Emotes",cx,cy-4,0xffe8f5f2);
        drawCenteredString(fontRendererObj,"Release B or click · right click changes a favorite",cx,height-18,0xffd0dfdc);
        if(!CubeonForge.held(CubeonForge.EMOTES)) choose();
    }
    private void choose() { if(selected>=0) CubeonForge.play(EmoteState.id(favorites[selected])); mc.displayGuiScreen(null); }
    @Override protected void mouseClicked(int x,int y,int b) {
        if(b==0) choose();
        else if(b==1 && selected>=0) {
            int id=EmoteState.id(favorites[selected]);
            favorites[selected]=EmoteState.NAMES[(id+1)%EmoteState.NAMES.length];
            CubeonHudConfig.get().emoteFavorites=EmoteFavorites.normalize(favorites); CubeonHudConfig.save();
            favorites=CubeonHudConfig.get().emoteFavorites;
        }
    }
    @Override protected void keyTyped(char c,int code) { if(code==1) mc.displayGuiScreen(null); }
}
