package com.cubeon.forge;

import com.cubeon.client.Bridge;
import com.cubeon.client.emotes.EmoteWheel;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.gui.GuiScreen;
import net.minecraft.client.renderer.GlStateManager;
import org.lwjgl.input.Keyboard;

/**
 * Circle emote picker drawn by the shared wheel. B opens it, holding B and
 * releasing on a slot plays it; E edits favorites, Esc/right click cancels.
 */
public final class EmoteScreen extends GuiScreen {
    private final EmoteWheel wheel = new EmoteWheel(CubeonHudConfig.get().emoteFavorites);

    public EmoteScreen() { }

    @Override public void initGui() { wheel.layout(width, height); }
    @Override public boolean doesGuiPauseGame() { return false; }

    @Override public void drawScreen(int mouseX, int mouseY, float partial) {
        drawDefaultBackground();
        wheel.render(new ForgeCanvas(), width, height, mouseX, mouseY,
                CubeonHudConfig.get().showEmotes, Bridge.get().emotesReady(),
                CubeonHudConfig.get().menuAnimations);
        GlStateManager.color(1.0F, 1.0F, 1.0F, 1.0F);
        // Releasing B over a slot plays it, as before the wheel was shared.
        if (!wheel.editing() && !CubeonForge.held(CubeonForge.EMOTES)) choose(wheel.selection());
    }

    @Override protected void mouseClicked(int mouseX, int mouseY, int button) {
        if (button == 1) { close(); return; }
        if (button == 0) choose(wheel.hit(mouseX, mouseY));
    }

    @Override protected void keyTyped(char typed, int key) {
        if (key == Keyboard.KEY_ESCAPE) { close(); return; }
        if (key >= Keyboard.KEY_1 && key <= Keyboard.KEY_8) { choose(key - Keyboard.KEY_1); return; }
        if (wheel.editing() && key == Keyboard.KEY_9) { choose(8); return; }
        if (wheel.editing() && key == Keyboard.KEY_0) { choose(9); return; }
        if (key == Keyboard.KEY_E) { wheel.edit(!wheel.editing()); return; }
        if (key == Keyboard.KEY_LEFT || key == Keyboard.KEY_UP) { wheel.step(-1); return; }
        if (key == Keyboard.KEY_RIGHT || key == Keyboard.KEY_DOWN || key == Keyboard.KEY_TAB) { wheel.step(1); return; }
        if (key == Keyboard.KEY_RETURN || key == Keyboard.KEY_NUMPADENTER) { choose(wheel.selection()); }
    }

    private void choose(int selection) {
        if (selection == EmoteWheel.EDIT) { wheel.edit(true); return; }
        if (selection == EmoteWheel.DONE) { wheel.edit(false); return; }
        if (wheel.editing()) {
            if (selection < 0 || selection >= wheel.choices()) return;
            if (wheel.toggleFavorite(selection)) {
                CubeonHudConfig.get().emoteFavorites = wheel.favorites();
                CubeonHudConfig.save();
            }
            return;
        }
        if (selection == EmoteWheel.TOGGLE) {
            if (CubeonHudConfig.get().showEmotes) CubeonForge.play(-1);
            CubeonHudConfig.get().showEmotes = !CubeonHudConfig.get().showEmotes;
            CubeonHudConfig.save();
            return;
        }
        if (selection < EmoteWheel.STOP || selection >= wheel.slots() || !CubeonHudConfig.get().showEmotes) return;
        CubeonForge.play(wheel.emote(selection));
        close();
    }

    private void close() {
        if (wheel.editing()) { wheel.edit(false); return; }
        mc.displayGuiScreen(null);
    }
}
