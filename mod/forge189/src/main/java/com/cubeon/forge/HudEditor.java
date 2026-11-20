package com.cubeon.forge;

import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.HudFeatures;
import com.cubeon.client.ui.ClientUi;
import com.cubeon.client.ui.HudEditorChrome;
import net.minecraft.client.gui.GuiScreen;
import net.minecraft.client.renderer.GlStateManager;
import org.lwjgl.input.Keyboard;
import org.lwjgl.input.Mouse;

/**
 * 1.8.9 HUD placement screen using the shared editor chrome: drag to move,
 * the corner handle or the wheel to resize, Done/Enter to finish.
 */
public final class HudEditor extends GuiScreen {
    private final GuiScreen parent;
    private HudFeatures selected;
    private int grabX, grabY, resizeX, resizeY;
    private boolean dragging, resizing;
    private float resizeBaseWidth, resizeBaseHeight;

    public HudEditor(GuiScreen parent) { this(parent, null); }

    public HudEditor(GuiScreen parent, HudFeatures selected) {
        this.parent = parent;
        this.selected = selected;
    }

    @Override public void initGui() { }
    @Override public boolean doesGuiPauseGame() { return false; }

    private int x(HudFeatures feature) {
        float scale = CubeonHudConfig.get().scaleFor(feature.slot);
        return Math.round(Hud189.position(feature, false) * Math.max(0, width - feature.width * scale));
    }

    private int y(HudFeatures feature) {
        float scale = CubeonHudConfig.get().scaleFor(feature.slot);
        return Math.round(Hud189.position(feature, true) * Math.max(0, height - feature.height * scale));
    }

    private int widthOf(HudFeatures feature) {
        return Math.round(feature.width * CubeonHudConfig.get().scaleFor(feature.slot));
    }

    private int heightOf(HudFeatures feature) {
        return Math.round(feature.height * CubeonHudConfig.get().scaleFor(feature.slot));
    }

    @Override public void drawScreen(int mouseX, int mouseY, float partial) {
        // Translucent darkening instead of the vanilla backdrop, so the world stays visible.
        drawRect(0, 0, width, height, 0x22000000);
        Hud189.draw(partial, true);
        GlStateManager.color(1.0F, 1.0F, 1.0F, 1.0F);
        ClientUi.Canvas ui = new ForgeCanvas();
        int sx = selected == null ? -99 : x(selected), sy = selected == null ? -99 : y(selected);
        int sw = selected == null ? 0 : widthOf(selected), sh = selected == null ? 0 : heightOf(selected);
        for (HudFeatures other : HudFeatures.ALL) {
            if (other == selected) continue;
            HudEditorChrome.peer(ui, width, height, x(other), y(other), widthOf(other), heightOf(other), sx, sy, sw, sh);
        }
        HudEditorChrome.render(ui, width, height,
                selected == null ? ui.translate("cubeonclient.hud.editor") : ui.translate(selected.label()),
                mouseX, mouseY, sx, sy, sw, sh, dragging || resizing);
        GlStateManager.color(1.0F, 1.0F, 1.0F, 1.0F);
    }

    @Override protected void mouseClicked(int mouseX, int mouseY, int button) {
        if (button == 0 && HudEditorChrome.done(width, height, mouseX, mouseY)) { close(); return; }
        if (button == 1) { close(); return; }
        if (button != 0) return;
        for (HudFeatures feature : HudFeatures.ALL) {
            int px = x(feature), py = y(feature), pw = widthOf(feature), ph = heightOf(feature);
            if (selected != null && HudEditorChrome.resizeHandle(x(selected), y(selected), widthOf(selected),
                    heightOf(selected), mouseX, mouseY)) {
                float scale = CubeonHudConfig.get().scaleFor(selected.slot);
                resizeX = x(selected); resizeY = y(selected);
                resizeBaseWidth = widthOf(selected) / scale;
                resizeBaseHeight = heightOf(selected) / scale;
                resizing = true; dragging = false; return;
            }
            if (mouseX >= px && mouseX < px + pw && mouseY >= py && mouseY < py + ph) {
                selected = feature;
                grabX = mouseX - px; grabY = mouseY - py;
                dragging = true; resizing = false;
                return;
            }
        }
    }

    @Override protected void mouseClickMove(int mouseX, int mouseY, int button, long time) {
        if (button != 0 || selected == null) return;
        if (resizing) {
            float scale = Math.max((mouseX - resizeX) / Math.max(1F, resizeBaseWidth),
                    (mouseY - resizeY) / Math.max(1F, resizeBaseHeight));
            CubeonHudConfig.get().setScaleFor(selected.slot, scale);
            return;
        }
        if (!dragging) return;
        float scale = CubeonHudConfig.get().scaleFor(selected.slot);
        Hud189.position(selected, (mouseX - grabX) / Math.max(1F, width - selected.width * scale),
                (mouseY - grabY) / Math.max(1F, height - selected.height * scale));
    }

    @Override protected void mouseReleased(int mouseX, int mouseY, int button) {
        if (dragging || resizing) {
            dragging = false; resizing = false;
            CubeonHudConfig.save();
        }
    }

    @Override public void handleMouseInput() {
        super.handleMouseInput();
        int wheel = Mouse.getEventDWheel();
        if (wheel == 0 || selected == null) return;
        CubeonHudConfig.get().setScaleFor(selected.slot,
                CubeonHudConfig.get().scaleFor(selected.slot) + (wheel > 0 ? .1F : -.1F));
    }

    @Override protected void keyTyped(char typed, int key) {
        if (key == Keyboard.KEY_ESCAPE || key == Keyboard.KEY_RETURN || key == Keyboard.KEY_NUMPADENTER) close();
    }

    @Override public void onGuiClosed() { CubeonHudConfig.save(); }

    private void close() {
        CubeonHudConfig.save();
        mc.displayGuiScreen(parent);
    }
}
