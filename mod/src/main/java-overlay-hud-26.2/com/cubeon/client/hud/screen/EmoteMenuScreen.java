package com.cubeon.client.hud.screen;
import com.cubeon.client.Bridge;
import com.cubeon.client.ui.ClientUi;
import com.cubeon.client.emotes.EmoteClient;
import com.cubeon.client.emotes.EmoteWheel;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import org.lwjgl.glfw.GLFW;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.input.MouseButtonEvent;

/** Circular emote picker. B opens; click or 1–8 plays; Esc/right click cancels. */
public final class EmoteMenuScreen extends Screen {
    private final EmoteWheel wheel = new EmoteWheel(CubeonHudConfig.get().emoteFavorites);
    public EmoteMenuScreen() { super(Component.translatable("cubeonclient.menu.emotes")); }
    @Override protected void init() { wheel.layout(this.width, this.height); }
    @Override public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        graphics.fill(0, 0, this.width, this.height, ClientUi.BACKDROP);
    }
    @Override public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        super.extractRenderState(graphics, mouseX, mouseY, partialTick);
        wheel.render(new EmoteWheel.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { graphics.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(graphics, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = ClientUiFont.text(value);
                graphics.text(font, label, x - font.width(label) / 2, y, color, false);
            }
            public int width(String value) { return font.width(ClientUiFont.text(value)); }
            public String translate(String key) { return Component.translatable(key).getString(); }
        }, this.width, this.height, mouseX, mouseY, CubeonHudConfig.get().showEmotes, Bridge.get().emotesReady());
    }
    @Override public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
        if (event.button() == 1) { onClose(); return true; }
        if (event.button() == 0) return choose(wheel.hit(event.x(), event.y()));
        return super.mouseClicked(event, doubleClick);
    }
    @Override public boolean keyPressed(KeyEvent event) {
        return key(event.key()) || super.keyPressed(event);
    }
    private boolean key(int key) {
        if (key >= GLFW.GLFW_KEY_1 && key <= GLFW.GLFW_KEY_8) return choose(key - GLFW.GLFW_KEY_1);
        if (wheel.editing() && key == GLFW.GLFW_KEY_9) return choose(8);
        if (wheel.editing() && key == GLFW.GLFW_KEY_0) return choose(9);
        if (key == GLFW.GLFW_KEY_E) { wheel.edit(!wheel.editing()); return true; }
        if (key == GLFW.GLFW_KEY_LEFT || key == GLFW.GLFW_KEY_UP) { wheel.step(-1); return true; }
        if (key == GLFW.GLFW_KEY_RIGHT || key == GLFW.GLFW_KEY_DOWN || key == GLFW.GLFW_KEY_TAB) { wheel.step(1); return true; }
        if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER) return choose(wheel.selection());
        if (key == GLFW.GLFW_KEY_B) { if (wheel.editing()) { wheel.edit(false); return true; } if (!choose(wheel.selection())) onClose(); return true; }
        return false;
    }
    private boolean choose(int selection) {
        if (selection == EmoteWheel.EDIT) { wheel.edit(true); return true; }
        if (selection == EmoteWheel.DONE) { wheel.edit(false); return true; }
        if (wheel.editing()) {
            if (selection < 0 || selection >= wheel.choices()) return false;
            if (wheel.toggleFavorite(selection)) {
                CubeonHudConfig.get().emoteFavorites = wheel.favorites();
                CubeonHudConfig.save();
            }
            return true;
        }
        if (selection == EmoteWheel.TOGGLE) {
            if (CubeonHudConfig.get().showEmotes) EmoteClient.play(-1);
            CubeonHudConfig.get().showEmotes = !CubeonHudConfig.get().showEmotes;
            CubeonHudConfig.save(); return true;
        }
        if (selection < EmoteWheel.STOP || selection >= wheel.slots() || !CubeonHudConfig.get().showEmotes) return false;
        EmoteClient.play(wheel.emote(selection)); onClose(); return true;
    }
    @Override public void onClose() {
        if (wheel.editing()) { wheel.edit(false); return; }
        if (this.minecraft != null) this.minecraft.gui.setScreen(null);
    }
    @Override public boolean isPauseScreen() { return false; }
}
