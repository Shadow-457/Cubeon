package com.cubeon.forge;

import com.cubeon.client.ui.ClientTheme;
import net.minecraft.client.gui.*;
import java.io.IOException;

/** Legacy input adapter for the same instance palette and seasonal presets. */
public final class ThemeScreen extends GlassScreen {
    private int index=ClientTheme.selected(),role;
    private int[] draft=ClientTheme.colors();
    private GuiTextField field;
    private String message="";
    public ThemeScreen(GuiScreen parent) { super(parent); }
    @Override protected int[] themeColors() { return draft; }
    @Override public void initGui() {
        buttonList.clear();
        int w=Math.min(290,width-32),x=(width-w)/2,cell=(w-8)/3;
        for(int i=0;i<6;i++) button(10+i,x+(i%3)*(cell+4),36+(i/3)*23,cell,ClientTheme.NAMES[i]);
        field=null;
        if(index==5) {
            for(int i=0;i<6;i++) button(20+i,x+(i%3)*(cell+4),100+(i/3)*23,cell,ClientTheme.ROLES[i]);
            field=new GuiTextField(30,fontRendererObj,x,148,w,20);
            field.setMaxStringLength(6); field.setText(ClientTheme.hex(draft[role]));
        }
        button(0,x,height-36,76,"Back");button(1,x+w-76,height-36,76,"Apply");
    }
    private boolean valid() {
        if(field==null) return true;
        if(!ClientTheme.validHex(field.getText())) { message="Enter all six hex digits"; return false; }
        draft[role]=Integer.parseInt(field.getText(),16);return true;
    }
    @Override protected void actionPerformed(GuiButton button) {
        if(button.id==0) { mc.displayGuiScreen(parent);return; }
        if(!valid()) return;
        if(button.id>=10 && button.id<16) { index=button.id-10;draft=ClientTheme.preset(index);message="";initGui(); }
        else if(button.id>=20 && button.id<26) {
            role=button.id-20;initGui();field.setFocused(true);field.setCursorPositionEnd();field.setSelectionPos(0);
        } else if(button.id==1) message=ClientTheme.apply(index,draft)?"Saved":"Could not save theme";
    }
    @Override protected void mouseClicked(int x,int y,int button) {
        super.mouseClicked(x,y,button);if(field!=null) field.mouseClicked(x,y,button);
    }
    @Override protected void keyTyped(char c,int code) {
        if(code==1) { mc.displayGuiScreen(parent);return; }
        if(field!=null && field.isFocused()) {
            field.textboxKeyTyped(c,code);
            if(ClientTheme.validHex(field.getText())) draft[role]=Integer.parseInt(field.getText(),16);
        } else super.keyTyped(c,code);
    }
    @Override public void drawScreen(int x,int y,float tick) {
        chrome("Themes");super.drawScreen(x,y,tick);
        if(field!=null) field.drawTextBox();
        drawCenteredString(fontRendererObj,message.isEmpty()?(index==5?"Select a color and enter its hex code":"Apply to save this menu theme"):message,width/2,height-57,0xFF000000|draft[5]);
    }
}
