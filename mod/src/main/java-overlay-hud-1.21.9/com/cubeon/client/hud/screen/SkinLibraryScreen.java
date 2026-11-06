package com.cubeon.client.hud.screen;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.text.Text;
import net.minecraft.client.MinecraftClient;
import org.lwjgl.glfw.GLFW;
import net.minecraft.client.input.KeyInput;
import net.minecraft.client.gui.Click;

import com.cubeon.client.ui.ClientUi;

import com.cubeon.client.ui.SkinMenu;
import java.nio.file.Path;
import java.util.List;

/** In-game skin wardrobe adapter for this Minecraft GUI era. */
public final class SkinLibraryScreen extends Screen {
    private final Screen parent;
    private final SkinNative nativeSkin=new SkinNative();
    private final SkinMenu menu=new SkinMenu(nativeSkin);
    public SkinLibraryScreen(Screen parent) { super(Text.translatable("cubeonclient.cosmetics.title")); this.parent=parent; }
    @Override public void renderBackground(DrawContext context, int mouseX, int mouseY, float delta) {
        nativeSkin.draw(context,this.width,this.height,delta);
    }
    @Override public void render(DrawContext context, int mouseX, int mouseY, float delta) {
        super.render(context, mouseX, mouseY, delta);
        menu.render(canvas(context), this.width, this.height, mouseX, mouseY);
    }

    public static void open(Screen parent) { MinecraftClient.getInstance().setScreen(new SkinLibraryScreen(parent)); }

    private ClientUi.Canvas canvas(DrawContext context) { return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { context.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(context, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = Text.literal(value);
                context.drawText(textRenderer, label, x - textRenderer.getWidth(label) / 2, y, color, true);
            }
            public int width(String value) { return textRenderer.getWidth(Text.literal(value)); }
            public void textScaled(String value,int x,int y,int color,float scale) {
                var matrices=context.getMatrices(); matrices.pushMatrix();
                matrices.translate(x, y); matrices.scale(scale, scale);
                context.drawText(textRenderer, Text.literal(value), -textRenderer.getWidth(value) / 2, 0, color, true);
                matrices.popMatrix();
            }
            public String translate(String key) { return Text.translatable(key).getString(); }
        }; }
    @Override public boolean mouseClicked(Click event, boolean doubleClick) {
        if(event.button()==1) { close(); return true; }
        if(event.button()==0) return click(event.x(),event.y());
        return super.mouseClicked(event,doubleClick);
    }
    @Override public boolean mouseDragged(Click event,double dx,double dy) { return menu.drag(event.x(),event.y()); }
    @Override public boolean mouseReleased(Click event) { menu.release(); return true; }
    @Override public boolean keyPressed(KeyInput event) {
        boolean handled=key(event.key(),(event.modifiers() & 2) != 0)||super.keyPressed(event);
        
        return handled;
    }
    @Override public boolean charTyped(net.minecraft.client.input.CharInput event) { return menu.type(event.codepoint())||super.charTyped(event); }
    @Override public boolean mouseScrolled(double x,double y,double horizontal,double amount) { return menu.scroll(amount); }
    public void filesDragged(List<Path> paths) { menu.dropped(paths); }
    public void onFilesDropped(List<Path> paths) { menu.dropped(paths); }
    private boolean key(int key,boolean control) {
        if(key==GLFW.GLFW_KEY_ESCAPE) { if(!menu.escape()) close(); return true; }
        if(menu.focused()) {
            if(key==GLFW.GLFW_KEY_BACKSPACE) return menu.backspace();
            if(key==GLFW.GLFW_KEY_V&&control) { menu.paste(client.keyboard.getClipboard()); return true; }
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
            if(menu.selection()==SkinMenu.BACK) { close(); return true; }
            return menu.activate(menu.selection());
        }
        return false;
    }
    private boolean click(double x,double y) {
        if(menu.hit(x,y)==SkinMenu.BACK) { close(); return true; }
        boolean handled=menu.click(x,y);
        
        return handled;
    }
    @Override public void removed() {  menu.close(); }
    @Override public void close() { if(this.client!=null) this.client.setScreen(parent); }
    @Override public boolean shouldPause() { return false; }
}
