package com.cubeon.client.hud.screen;
import com.cubeon.client.Bridge;
import com.cubeon.client.emotes.EmoteClient;
import com.cubeon.client.emotes.EmoteWheel;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import com.mojang.blaze3d.platform.InputConstants;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.input.MouseButtonEvent;

/** Circular emote picker. B opens; click or 1–6 plays; Esc/right click cancels. */
public final class EmoteMenuScreen extends Screen {
    private final EmoteWheel wheel = new EmoteWheel();
    public EmoteMenuScreen() { super(Component.translatable("cubeonclient.menu.emotes")); }
    @Override protected void init() { wheel.layout(this.width, this.height); }
    @Override public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        graphics.fill(0, 0, this.width, this.height, 0x75070C15);
    }
    @Override public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        super.extractRenderState(graphics, mouseX, mouseY, partialTick);
        wheel.render(new EmoteWheel.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { graphics.fill(x0, y0, x1, y1, color); }
            public void text(String value, int x, int y, int color) { graphics.centeredText(font, Component.literal(value), x, y, color); }
            public String translate(String key) { return Component.translatable(key).getString(); }
        }, this.width, this.height, mouseX, mouseY, CubeonHudConfig.get().showEmotes, Bridge.get().emotesReady());
    }
    @Override public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
        if (event.button() == InputConstants.MOUSE_BUTTON_RIGHT) { onClose(); return true; }
        if (event.button() == InputConstants.MOUSE_BUTTON_LEFT) return choose(wheel.hit(event.x(), event.y()));
        return super.mouseClicked(event, doubleClick);
    }
    @Override public boolean keyPressed(KeyEvent event) {
        return key(event.key()) || super.keyPressed(event);
    }
    private boolean key(int key) {
        if (key >= InputConstants.KEY_1 && key <= InputConstants.KEY_6) return choose(key - InputConstants.KEY_1);
        if (key == InputConstants.KEY_LEFT || key == InputConstants.KEY_UP) { wheel.step(-1); return true; }
        if (key == InputConstants.KEY_RIGHT || key == InputConstants.KEY_DOWN || key == InputConstants.KEY_TAB) { wheel.step(1); return true; }
        if (key == InputConstants.KEY_RETURN || key == InputConstants.KEY_NUMPADENTER) return choose(wheel.selection());
        if (key == InputConstants.KEY_B) { if (!choose(wheel.selection())) onClose(); return true; }
        return false;
    }
    private boolean choose(int selection) {
        if (selection == EmoteWheel.TOGGLE) {
            if (CubeonHudConfig.get().showEmotes) EmoteClient.play(-1);
            CubeonHudConfig.get().showEmotes = !CubeonHudConfig.get().showEmotes;
            CubeonHudConfig.save(); return true;
        }
        if (selection == EmoteWheel.NONE || !CubeonHudConfig.get().showEmotes) return false;
        EmoteClient.play(selection); onClose(); return true;
    }
    @Override public void onClose() {
        if (this.minecraft != null) this.minecraft.gui.setScreen(null);
    }
    @Override public boolean isPauseScreen() { return false; }
}
