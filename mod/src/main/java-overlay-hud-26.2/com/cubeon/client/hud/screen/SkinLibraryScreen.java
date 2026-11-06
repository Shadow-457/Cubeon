package com.cubeon.client.hud.screen;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import net.minecraft.client.Minecraft;
import org.lwjgl.glfw.GLFW;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.input.MouseButtonEvent;

import com.cubeon.client.ui.ClientUi;

import com.cubeon.client.ui.SkinMenu;
import java.nio.file.Path;
import java.util.List;

/** In-game skin wardrobe adapter for this Minecraft GUI era. */
public final class SkinLibraryScreen extends Screen {
    private final Screen parent;
    private final SkinNative nativeSkin=new SkinNative();
    private final SkinMenu menu=new SkinMenu(nativeSkin);
    public SkinLibraryScreen(Screen parent) { super(Component.translatable("cubeonclient.cosmetics.title")); this.parent=parent; }
    @Override public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        if(minecraft.level==null) extractPanorama(graphics,partialTick);
        extractBlurredBackground(graphics);
        graphics.fill(0,0,this.width,this.height,0x9309090C);
    }
    @Override public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        super.extractRenderState(graphics, mouseX, mouseY, partialTick);
        menu.render(canvas(graphics), this.width, this.height, mouseX, mouseY);
    }

    public static void open(Screen parent) { Minecraft.getInstance().gui.setScreen(new SkinLibraryScreen(parent)); }

    private ClientUi.Canvas canvas(GuiGraphicsExtractor graphics) { return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { graphics.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(graphics, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = Component.literal(value);
                graphics.text(font, label, x - font.width(label) / 2, y, color, true);
            }
            public int width(String value) { return font.width(Component.literal(value)); }
            public void textScaled(String value,int x,int y,int color,float scale) {
                var matrices=graphics.pose(); matrices.pushMatrix();
                matrices.translate(x, y); matrices.scale(scale, scale);
                graphics.text(font, Component.literal(value), -font.width(value) / 2, 0, color, true);
                matrices.popMatrix();
            }
            public String translate(String key) { return Component.translatable(key).getString(); }
        }; }
    @Override public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
        if(event.button()==1) { onClose(); return true; }
        if(event.button()==0) return click(event.x(),event.y());
        return super.mouseClicked(event,doubleClick);
    }
    @Override public boolean mouseDragged(MouseButtonEvent event,double dx,double dy) { return menu.drag(event.x(),event.y()); }
    @Override public boolean mouseReleased(MouseButtonEvent event) { menu.release(); return true; }
    @Override public boolean keyPressed(KeyEvent event) {
        boolean handled=key(event.key(),(event.modifiers() & 2) != 0)||super.keyPressed(event);
        
        return handled;
    }
    @Override public boolean charTyped(net.minecraft.client.input.CharacterEvent event) { return menu.type(event.codepoint())||super.charTyped(event); }
    @Override public boolean mouseScrolled(double x,double y,double horizontal,double amount) { return menu.scroll(amount); }
    public void onFilesDrop(List<Path> paths) { menu.dropped(paths); }
    private boolean key(int key,boolean control) {
        if(key==GLFW.GLFW_KEY_ESCAPE) { if(!menu.escape()) onClose(); return true; }
        if(menu.focused()) {
            if(key==GLFW.GLFW_KEY_BACKSPACE) return menu.backspace();
            if(key==GLFW.GLFW_KEY_V&&control) { menu.paste(minecraft.keyboardHandler.getClipboard()); return true; }
            if(key==GLFW.GLFW_KEY_ENTER||key==GLFW.GLFW_KEY_KP_ENTER) return menu.activate(SkinMenu.LOOKUP);
            if(key==GLFW.GLFW_KEY_TAB) { menu.step(1); return true; }
            return true;
        }
        if(key==GLFW.GLFW_KEY_SLASH) { menu.focus(); return true; }
        if(key==GLFW.GLFW_KEY_TAB||key==GLFW.GLFW_KEY_DOWN) { menu.step(1); return true; }
        if(key==GLFW.GLFW_KEY_UP) { menu.step(-1); return true; }
        if(key==GLFW.GLFW_KEY_LEFT) return menu.activate(SkinMenu.LEFT);
        if(key==GLFW.GLFW_KEY_RIGHT) return menu.activate(SkinMenu.RIGHT);
        if(key==GLFW.GLFW_KEY_ENTER||key==GLFW.GLFW_KEY_KP_ENTER||key==GLFW.GLFW_KEY_SPACE) {
            if(menu.selection()==SkinMenu.BACK) { onClose(); return true; }
            return menu.activate(menu.selection());
        }
        return false;
    }
    private boolean click(double x,double y) {
        if(menu.hit(x,y)==SkinMenu.BACK) { onClose(); return true; }
        boolean handled=menu.click(x,y);
        
        return handled;
    }
    @Override public void removed() {  menu.close(); }
    @Override public void onClose() { if(this.minecraft!=null) this.minecraft.gui.setScreen(parent); }
    @Override public boolean isPauseScreen() { return false; }
}
