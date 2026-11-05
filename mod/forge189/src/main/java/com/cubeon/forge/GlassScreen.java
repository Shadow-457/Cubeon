package com.cubeon.forge;

import net.minecraft.client.gui.*;
import java.io.IOException;

/** Shared translucent Cubeon controls, with vanilla keyboard and button semantics. */
public abstract class GlassScreen extends GuiScreen {
    protected final GuiScreen parent;
    protected GlassScreen(GuiScreen parent) { this.parent=parent; }
    protected GuiButton button(int id,int x,int y,int w,String label) {
        GuiButton b=new GlassButton(id,x,y,w,20,label); buttonList.add(b); return b;
    }
    protected void chrome(String title) {
        drawDefaultBackground();
        drawRect(8,8,width-8,height-8,0xc01b272c);
        drawRect(8,8,width-8,9,0xb07edac5);
        drawCenteredString(fontRendererObj,title,width/2,17,0xffe8f5f2);
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
            drawRect(xPosition,yPosition,xPosition+width,yPosition+height,!enabled?0x60404c50:hovered?0xc0528073:0xa02c444a);
            drawRect(xPosition,yPosition,xPosition+width,yPosition+1,hovered?0xff9be9d2:0x705b8b83);
            drawCenteredString(mc.fontRendererObj,displayString,xPosition+width/2,yPosition+(height-8)/2,enabled?0xffe8f5f2:0xff869795);
            mouseDragged(mc,x,y);
        }
    }
}
