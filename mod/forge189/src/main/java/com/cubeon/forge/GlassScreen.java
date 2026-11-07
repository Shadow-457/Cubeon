package com.cubeon.forge;

import net.minecraft.client.gui.*;
import java.io.IOException;

/** Shared translucent Cubeon controls, with vanilla keyboard and button semantics. */
public abstract class GlassScreen extends GuiScreen {
    protected final GuiScreen parent;
    protected GlassScreen(GuiScreen parent) { this.parent=parent; }
    protected int[] themeColors() { return com.cubeon.client.ui.ClientTheme.colors(); }
    protected GuiButton button(int id,int x,int y,int w,String label) {
        GuiButton b=new GlassButton(id,x,y,w,20,label); buttonList.add(b); return b;
    }
    protected void chrome(String title) {
        drawDefaultBackground();
        int[] colors=themeColors();
        drawRect(8,8,width-8,height-8,0xF0000000|colors[1]);
        drawRect(8,8,width-8,9,0xFF000000|colors[0]);
        drawCenteredString(fontRendererObj,title,width/2,17,0xFF000000|colors[4]);
    }
    @Override public boolean doesGuiPauseGame() { return false; }
    @Override protected void keyTyped(char c,int code) {
        if(code==1) mc.displayGuiScreen(parent); else super.keyTyped(c,code);
    }
    public static final class GlassButton extends GuiButton {
        GlassButton(int id,int x,int y,int w,int h,String s) { super(id,x,y,w,h,s); }
        @Override public void drawButton(net.minecraft.client.Minecraft mc,int x,int y) {
            if(!visible) return;
            hovered=x>=xPosition && y>=yPosition && x<xPosition+width && y<yPosition+height;
            int[] colors=mc.currentScreen instanceof GlassScreen?((GlassScreen)mc.currentScreen).themeColors():com.cubeon.client.ui.ClientTheme.colors();
            drawRect(xPosition,yPosition,xPosition+width,yPosition+height,0xE0000000|colors[2]);
            drawRect(xPosition,yPosition,xPosition+width,yPosition+1,0xFF000000|(hovered?colors[0]:colors[3]));
            drawCenteredString(mc.fontRendererObj,displayString,xPosition+width/2,yPosition+(height-8)/2,0xFF000000|colors[enabled?4:5]);
            mouseDragged(mc,x,y);
        }
    }
}
