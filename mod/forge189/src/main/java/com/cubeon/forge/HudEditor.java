package com.cubeon.forge;
import com.cubeon.client.hud.*;
import net.minecraft.client.gui.*;
import org.lwjgl.input.Mouse;
import java.io.IOException;

public final class HudEditor extends GlassScreen {
    private HudFeatures selected;
    private int offsetX,offsetY;
    public HudEditor(GuiScreen parent) { super(parent); }
    @Override public void initGui() {
        buttonList.clear(); button(0,width/2-45,height-26,90,"Done"); button(1,width/2-100,8,90,"Reset layout");
    }
    @Override public void drawScreen(int x,int y,float partial) {
        if(mc.theWorld==null) drawDefaultBackground();
        Hud189.draw(partial,true);
        drawCenteredString(fontRendererObj,"Drag widgets · wheel changes selected size · right click toggles",width/2,height-42,0xffe8f5f2);
        super.drawScreen(x,y,partial);
    }
    @Override protected void mouseClicked(int x,int y,int button) {
        super.mouseClicked(x,y,button);
        for(HudFeatures f:HudFeatures.ALL) {
            float s=CubeonHudConfig.get().scaleFor(f.slot);
            int px=Math.round(Hud189.position(f,false)*Math.max(0,width-f.width*s));
            int py=Math.round(Hud189.position(f,true)*Math.max(0,height-f.height*s));
            if(x>=px && y>=py && x<px+f.width*s && y<py+f.height*s) {
                selected=f; offsetX=x-px; offsetY=y-py;
                if(button==1) Hud189.toggle(f);
                break;
            }
        }
    }
    @Override protected void mouseClickMove(int x,int y,int b,long time) {
        if(b==0 && selected!=null) {
            float s=CubeonHudConfig.get().scaleFor(selected.slot);
            Hud189.position(selected,(x-offsetX)/Math.max(1,width-selected.width*s),(y-offsetY)/Math.max(1,height-selected.height*s));
        }
    }
    @Override protected void mouseReleased(int x,int y,int b) { CubeonHudConfig.save(); super.mouseReleased(x,y,b); }
    @Override public void handleMouseInput() {
        super.handleMouseInput(); int wheel=Mouse.getEventDWheel();
        if(wheel!=0 && selected!=null) CubeonHudConfig.get().setScaleFor(selected.slot,CubeonHudConfig.get().scaleFor(selected.slot)+(wheel>0?.1f:-.1f));
    }
    @Override protected void actionPerformed(GuiButton b) {
        if(b.id==0) mc.displayGuiScreen(parent); else { CubeonHudConfig.resetPositions(); CubeonHudConfig.save(); }
    }
}
