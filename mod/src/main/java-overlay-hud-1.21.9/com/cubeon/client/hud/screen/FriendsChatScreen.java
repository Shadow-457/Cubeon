package com.cubeon.client.hud.screen;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.text.Text;
import net.minecraft.client.MinecraftClient;
import org.lwjgl.glfw.GLFW;
import net.minecraft.client.input.KeyInput;
import net.minecraft.client.gui.Click;

import com.cubeon.client.ui.ClientUi;
import com.cubeon.client.ui.MenuUi;

import com.cubeon.client.Bridge;
import com.cubeon.client.ui.FriendsPanel;
import net.minecraft.client.gui.widget.TextFieldWidget;
/** Friends messages use the launcher's encrypted history, never the server chat channel. */
public final class FriendsChatScreen extends Screen {
    private final SkinNative backdrop = new SkinNative();
    private final Screen parent;
    private final FriendsPanel panel = new FriendsPanel(Bridge.get());
    private TextFieldWidget input;
    public FriendsChatScreen() { this(null); }
    public FriendsChatScreen(Screen parent) { super(Text.translatable("cubeonclient.friends.chat_title")); this.parent = parent; }
    public static void open(Screen parent) { MinecraftClient.getInstance().setScreen(new FriendsChatScreen(parent)); }
    @Override protected void init() {
        if (input != null) panel.saveDraft(input.getText());
        panel.layout(this.width, this.height); panel.ensurePeer();
        input = new TextFieldWidget(textRenderer, panel.inputX(), panel.inputY(), panel.inputWidth(), 16,
                Text.translatable("cubeonclient.friends.message"));
        input.setMaxLength(1000);
        input.setDrawsBackground(false); input.setEditableColor(MenuUi.TEXT);

        input.setText(panel.draft());
        addDrawableChild(input); setInitialFocus(input);
    }
    @Override public void renderBackground(DrawContext context, int mouseX, int mouseY, float delta) {
        backdrop.draw(context, this.width, this.height, delta);
    }
    @Override public void render(DrawContext context, int mouseX, int mouseY, float delta) {
        
        super.render(context, mouseX, mouseY, delta);
        panel.render(canvas(context), this.width, this.height, mouseX, mouseY, com.cubeon.client.hud.CubeonHudConfig.get().menuAnimations);
        input.render(context, mouseX, mouseY, delta);
    }
    private ClientUi.Canvas canvas(DrawContext context) { return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { context.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(context, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = Text.literal(value);
                context.drawText(textRenderer, label, x - textRenderer.getWidth(label) / 2, y, color, false);
            }
            public int width(String value) { return textRenderer.getWidth(Text.literal(value)); }
            public String translate(String key) { return Text.translatable(key).getString(); }
        }; }
    @Override public void tick() {
        if (panel.ensurePeer()) input.setText(panel.draft());
        if (panel.completed(input.getText())) input.setText("");
        panel.saveDraft(input.getText());
        input.setEditable(!panel.peer().isEmpty());
        
    }
    private boolean choose(int action) {
        if (action == FriendsPanel.CLOSE) { close(); return true; }
        if (action == FriendsPanel.SEND) { panel.send(input.getText()); return true; }
        if (action >= 0) {
            panel.saveDraft(input.getText()); panel.select(action); input.setText(panel.draft());
            setInitialFocus(input); return true;
        }
        return false;
    }
    private boolean key(int key, int modifiers) {
        if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER) { panel.send(input.getText()); return true; }
        if (key == GLFW.GLFW_KEY_PAGE_UP || key == GLFW.GLFW_KEY_PAGE_DOWN) {
            panel.scroll(panel.inputX(), key == GLFW.GLFW_KEY_PAGE_UP ? 1 : -1); return true;
        }
        if ((modifiers & 2) != 0 && (key == GLFW.GLFW_KEY_UP || key == GLFW.GLFW_KEY_DOWN)) {
            panel.saveDraft(input.getText()); panel.step(key == GLFW.GLFW_KEY_UP ? -1 : 1);
            input.setText(panel.draft()); return true;
        }
        return false;
    }
    @Override public boolean mouseClicked(Click event, boolean doubleClick) {
        if (event.button() == 0 && choose(panel.hit(event.x(), event.y()))) return true;
        return super.mouseClicked(event, doubleClick);
    }
    @Override public boolean keyPressed(KeyInput event) {
        return key(event.key(), event.modifiers()) || super.keyPressed(event);
    }
    @Override public boolean mouseScrolled(double x, double y, double horizontal, double amount) {
        panel.scroll(x, amount); return true;
    }
    @Override public void removed() { if (input != null) panel.saveDraft(input.getText()); panel.close(); }
    @Override public void close() { if (this.client != null) this.client.setScreen(parent); }
    @Override public boolean shouldPause() { return false; }
}
