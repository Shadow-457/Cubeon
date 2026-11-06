package com.cubeon.client.hud.screen;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import net.minecraft.client.Minecraft;
import com.mojang.blaze3d.platform.InputConstants;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.input.MouseButtonEvent;

import com.cubeon.client.ui.ClientUi;
import com.cubeon.client.ui.MenuUi;

import com.cubeon.client.Bridge;
import com.cubeon.client.ui.FriendsPanel;
import net.minecraft.client.gui.components.EditBox;
/** Friends messages use the launcher's encrypted history, never the server chat channel. */
public final class FriendsChatScreen extends Screen {
    private final Screen parent;
    private final FriendsPanel panel = new FriendsPanel(Bridge.get());
    private EditBox input;
    public FriendsChatScreen() { this(null); }
    public FriendsChatScreen(Screen parent) { super(Component.translatable("cubeonclient.friends.chat_title")); this.parent = parent; }
    public static void open(Screen parent) { Minecraft.getInstance().gui.setScreen(new FriendsChatScreen(parent)); }
    @Override protected void init() {
        if (input != null) panel.saveDraft(input.getValue());
        panel.layout(this.width, this.height); panel.ensurePeer();
        input = new EditBox(font, panel.inputX(), panel.inputY(), panel.inputWidth(), 16,
                Component.translatable("cubeonclient.friends.message"));
        input.setMaxLength(1000);
        input.setBordered(false); input.setTextColor(MenuUi.TEXT);

        input.setValue(panel.draft());
        addRenderableWidget(input); setInitialFocus(input);
    }
    @Override public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        if (minecraft.level == null) extractPanorama(graphics, partialTick);
        extractBlurredBackground(graphics);
        graphics.fill(0, 0, this.width, this.height, 0x9309090C);
    }
    @Override public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float delta) {
        
        super.extractRenderState(graphics, mouseX, mouseY, delta);
        panel.render(canvas(graphics), this.width, this.height, mouseX, mouseY, com.cubeon.client.hud.CubeonHudConfig.get().menuAnimations);
        input.extractRenderState(graphics, mouseX, mouseY, delta);
    }
    private ClientUi.Canvas canvas(GuiGraphicsExtractor graphics) { return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { graphics.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(graphics, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = Component.literal(value);
                graphics.text(font, label, x - font.width(label) / 2, y, color, false);
            }
            public int width(String value) { return font.width(Component.literal(value)); }
            public String translate(String key) { return Component.translatable(key).getString(); }
        }; }
    @Override public void tick() {
        if (panel.ensurePeer()) input.setValue(panel.draft());
        if (panel.completed(input.getValue())) input.setValue("");
        panel.saveDraft(input.getValue());
        input.setEditable(!panel.peer().isEmpty());
        
    }
    private boolean choose(int action) {
        if (action == FriendsPanel.CLOSE) { onClose(); return true; }
        if (action == FriendsPanel.SEND) { panel.send(input.getValue()); return true; }
        if (action >= 0) {
            panel.saveDraft(input.getValue()); panel.select(action); input.setValue(panel.draft());
            setInitialFocus(input); return true;
        }
        return false;
    }
    private boolean key(int key, int modifiers) {
        if (key == InputConstants.KEY_RETURN || key == InputConstants.KEY_NUMPADENTER) { panel.send(input.getValue()); return true; }
        if (key == InputConstants.KEY_PAGEUP || key == InputConstants.KEY_PAGEDOWN) {
            panel.scroll(panel.inputX(), key == InputConstants.KEY_PAGEUP ? 1 : -1); return true;
        }
        if ((modifiers & 2) != 0 && (key == InputConstants.KEY_UP || key == InputConstants.KEY_DOWN)) {
            panel.saveDraft(input.getValue()); panel.step(key == InputConstants.KEY_UP ? -1 : 1);
            input.setValue(panel.draft()); return true;
        }
        return false;
    }
    @Override public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
        if (event.button() == InputConstants.MOUSE_BUTTON_LEFT && choose(panel.hit(event.x(), event.y()))) return true;
        return super.mouseClicked(event, doubleClick);
    }
    @Override public boolean keyPressed(KeyEvent event) {
        return key(event.key(), event.hasControlDownWithQuirk() ? 2 : 0) || super.keyPressed(event);
    }
    @Override public boolean mouseScrolled(double x, double y, double horizontal, double amount) {
        panel.scroll(x, amount); return true;
    }
    @Override public void removed() { if (input != null) panel.saveDraft(input.getValue()); panel.close(); }
    @Override public void onClose() { if (this.minecraft != null) this.minecraft.gui.setScreen(parent); }
    @Override public boolean isPauseScreen() { return false; }
}
