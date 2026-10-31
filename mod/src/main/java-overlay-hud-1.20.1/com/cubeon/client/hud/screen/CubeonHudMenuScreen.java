package com.cubeon.client.hud.screen;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.text.Text;
import org.lwjgl.glfw.GLFW;

import com.cubeon.client.hud.CubeonHud;
import com.cubeon.client.hud.CubeonHud.Overlay;
import com.cubeon.client.ui.ClientUi;
import com.cubeon.client.ui.HudMenu;

/** Cubeon HUD settings, with custom cards and native input adapters. */
public final class CubeonHudMenuScreen extends Screen {
    private static final Overlay[] OVERLAYS = Overlay.values();
    private static final float[] SCALES = {.5f, .75f, 1f, 1.25f, 1.5f, 2f};
    private final HudMenu menu = new HudMenu();
    private final HudMenu.Settings settings = new HudMenu.Settings() {
        public boolean visible(int index) {
            var config = CubeonHudConfig.get();
            return switch (OVERLAYS[index]) {
                case FPS -> config.showFps; case KEYS -> config.showKeys;
                case ARMOR -> config.showArmor; case PING -> config.showPing; case CPS -> config.showCps;
            };
        }
        public float scale(int index) { return CubeonHud.scaleOf(OVERLAYS[index]); }
        public boolean health() { return CubeonHudConfig.get().showEnemyHealth; }
        public boolean animations() { return CubeonHudConfig.get().cosmeticAnimations; }
        public boolean wingDepth() { return CubeonHudConfig.get().wingDepth; }
        public boolean otherCosmetics() { return CubeonHudConfig.get().showOtherCosmetics; }
    };
    public CubeonHudMenuScreen() { super(Text.translatable("cubeonclient.menu.title")); }
    @Override protected void init() { menu.layout(this.width, this.height); }
    @Override public void renderBackground(DrawContext context) {
        context.fill(0, 0, this.width, this.height, ClientUi.BACKDROP);
    }
    @Override public void render(DrawContext context, int mouseX, int mouseY, float delta) {
        renderBackground(context);
        super.render(context, mouseX, mouseY, delta);
        menu.render(canvas(context), this.width, this.height, mouseX, mouseY, settings);
    }

    private ClientUi.Canvas canvas(DrawContext context) { return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { context.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(context, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = ClientUiFont.text(value);
                context.drawText(textRenderer, label, x - textRenderer.getWidth(label) / 2, y, color, false);
            }
            public int width(String value) { return textRenderer.getWidth(ClientUiFont.text(value)); }
            public String translate(String key) { return Text.translatable(key).getString(); }
        }; }
    @Override public boolean mouseClicked(double mouseX, double mouseY, int button) {
        if (button == 1) { close(); return true; }
        if (button == 0) return choose(menu.hit(mouseX, mouseY));
        return super.mouseClicked(mouseX, mouseY, button);
    }
    @Override public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
        return key(keyCode) || super.keyPressed(keyCode, scanCode, modifiers);
    }

    private boolean key(int key) {
        if (key >= GLFW.GLFW_KEY_1 && key <= GLFW.GLFW_KEY_5) return choose((key - GLFW.GLFW_KEY_1) * 3);
        if (key == GLFW.GLFW_KEY_LEFT || key == GLFW.GLFW_KEY_UP) { menu.step(-1); return true; }
        if (key == GLFW.GLFW_KEY_RIGHT || key == GLFW.GLFW_KEY_DOWN || key == GLFW.GLFW_KEY_TAB) { menu.step(1); return true; }
        if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER || key == GLFW.GLFW_KEY_SPACE) return choose(menu.selection());
        if (key == GLFW.GLFW_KEY_E) return choose(HudMenu.EMOTES);
        if (key == GLFW.GLFW_KEY_K) { close(); return true; }
        return false;
    }

    private boolean choose(int action) {
        if (action < 0 || action > HudMenu.DONE) return false;
        CubeonHudConfig config = CubeonHudConfig.get();
        if (action < HudMenu.EMOTES) {
            Overlay overlay = OVERLAYS[action / 3];
            switch (action % 3) {
                case 0 -> {
                    switch (overlay) {
                        case FPS -> config.showFps = !config.showFps;
                        case KEYS -> config.showKeys = !config.showKeys;
                        case ARMOR -> config.showArmor = !config.showArmor;
                        case PING -> config.showPing = !config.showPing;
                        case CPS -> config.showCps = !config.showCps;
                    }
                    CubeonHudConfig.save();
                }
                case 1 -> { if (this.client != null) this.client.setScreen(new MoveOverlayScreen(this, overlay)); }
                case 2 -> {
                    float current = CubeonHud.scaleOf(overlay);
                    int index = 0;
                    for (int i = 0; i < SCALES.length; i++) if (Math.abs(SCALES[i] - current) < .001f) { index = i; break; }
                    config.setScaleFor(CubeonHud.slotOf(overlay), SCALES[(index + 1) % SCALES.length]);
                }
            }
            return true;
        }
        switch (action) {
            case HudMenu.EMOTES -> { if (this.client != null) this.client.setScreen(new EmoteMenuScreen()); }
            case HudMenu.HEALTH -> { config.showEnemyHealth = !config.showEnemyHealth; CubeonHudConfig.save(); }
            case HudMenu.ANIMATIONS -> { config.cosmeticAnimations = !config.cosmeticAnimations; CubeonHudConfig.save(); }
            case HudMenu.WING_DEPTH -> { config.wingDepth = !config.wingDepth; CubeonHudConfig.save(); }
            case HudMenu.OTHER_COSMETICS -> { config.showOtherCosmetics = !config.showOtherCosmetics; CubeonHudConfig.save(); }
            case HudMenu.RESET -> { CubeonHudConfig.resetPositions(); CubeonHudConfig.save(); }
            case HudMenu.DONE -> close();
        }
        return true;
    }

    @Override public void removed() { CubeonHudConfig.save(); }
    @Override public void close() {
        CubeonHudConfig.save();
        if (this.client != null) this.client.setScreen(null);
    }
    @Override public boolean shouldPause() { return false; }
}
