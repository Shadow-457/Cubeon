package com.cubeon.client.hud.screen;
import com.cubeon.client.Bridge;
import com.cubeon.client.emotes.EmoteClient;
import com.cubeon.client.emotes.EmoteWheel;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.text.Text;
import org.lwjgl.glfw.GLFW;

/** Circular emote picker. B opens; click or 1–6 plays; Esc/right click cancels. */
public final class EmoteMenuScreen extends Screen {
    private final EmoteWheel wheel = new EmoteWheel();
    public EmoteMenuScreen() { super(Text.translatable("cubeonclient.menu.emotes")); }
    @Override protected void init() { wheel.layout(this.width, this.height); }
    @Override public void renderBackground(DrawContext context) {
        context.fill(0, 0, this.width, this.height, 0x75070C15);
    }
    @Override public void render(DrawContext context, int mouseX, int mouseY, float delta) {
        renderBackground(context);
        super.render(context, mouseX, mouseY, delta);
        wheel.render(new EmoteWheel.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { context.fill(x0, y0, x1, y1, color); }
            public void text(String value, int x, int y, int color) { context.drawCenteredTextWithShadow(textRenderer, value, x, y, color); }
            public String translate(String key) { return Text.translatable(key).getString(); }
        }, this.width, this.height, mouseX, mouseY, CubeonHudConfig.get().showEmotes, Bridge.get().emotesReady());
    }
    @Override public boolean mouseClicked(double mouseX, double mouseY, int button) {
        if (button == 1) { close(); return true; }
        if (button == 0) return choose(wheel.hit(mouseX, mouseY));
        return super.mouseClicked(mouseX, mouseY, button);
    }
    @Override public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
        return key(keyCode) || super.keyPressed(keyCode, scanCode, modifiers);
    }
    private boolean key(int key) {
        if (key >= GLFW.GLFW_KEY_1 && key <= GLFW.GLFW_KEY_6) return choose(key - GLFW.GLFW_KEY_1);
        if (key == GLFW.GLFW_KEY_LEFT || key == GLFW.GLFW_KEY_UP) { wheel.step(-1); return true; }
        if (key == GLFW.GLFW_KEY_RIGHT || key == GLFW.GLFW_KEY_DOWN || key == GLFW.GLFW_KEY_TAB) { wheel.step(1); return true; }
        if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER) return choose(wheel.selection());
        if (key == GLFW.GLFW_KEY_B) { if (!choose(wheel.selection())) close(); return true; }
        return false;
    }
    private boolean choose(int selection) {
        if (selection == EmoteWheel.TOGGLE) {
            if (CubeonHudConfig.get().showEmotes) EmoteClient.play(-1);
            CubeonHudConfig.get().showEmotes = !CubeonHudConfig.get().showEmotes;
            CubeonHudConfig.save(); return true;
        }
        if (selection == EmoteWheel.NONE || !CubeonHudConfig.get().showEmotes) return false;
        EmoteClient.play(selection); close(); return true;
    }
    @Override public void close() {
        if (this.client != null) this.client.setScreen(null);
    }
    @Override public boolean shouldPause() { return false; }
}
