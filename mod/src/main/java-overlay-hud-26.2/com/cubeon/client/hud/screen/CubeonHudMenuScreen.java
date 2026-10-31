package com.cubeon.client.hud.screen;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import org.lwjgl.glfw.GLFW;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.input.MouseButtonEvent;

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
    public CubeonHudMenuScreen() { super(Component.translatable("cubeonclient.menu.title")); }
    @Override protected void init() { menu.layout(this.width, this.height); }
    @Override public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        graphics.fill(0, 0, this.width, this.height, ClientUi.BACKDROP);
    }
    @Override public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        super.extractRenderState(graphics, mouseX, mouseY, partialTick);
        menu.render(canvas(graphics), this.width, this.height, mouseX, mouseY, settings);
    }

    private ClientUi.Canvas canvas(GuiGraphicsExtractor graphics) { return new ClientUi.Canvas() {
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
        }; }
    @Override public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
        if (event.button() == 1) { onClose(); return true; }
        if (event.button() == 0) return choose(menu.hit(event.x(), event.y()));
        return super.mouseClicked(event, doubleClick);
    }
    @Override public boolean keyPressed(KeyEvent event) {
        return key(event.key()) || super.keyPressed(event);
    }

    private boolean key(int key) {
        if (key >= GLFW.GLFW_KEY_1 && key <= GLFW.GLFW_KEY_5) return choose((key - GLFW.GLFW_KEY_1) * 3);
        if (key == GLFW.GLFW_KEY_LEFT || key == GLFW.GLFW_KEY_UP) { menu.step(-1); return true; }
        if (key == GLFW.GLFW_KEY_RIGHT || key == GLFW.GLFW_KEY_DOWN || key == GLFW.GLFW_KEY_TAB) { menu.step(1); return true; }
        if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER || key == GLFW.GLFW_KEY_SPACE) return choose(menu.selection());
        if (key == GLFW.GLFW_KEY_E) return choose(HudMenu.EMOTES);
        if (key == GLFW.GLFW_KEY_K) { onClose(); return true; }
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
                case 1 -> { if (this.minecraft != null) this.minecraft.gui.setScreen(new MoveOverlayScreen(this, overlay)); }
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
            case HudMenu.EMOTES -> { if (this.minecraft != null) this.minecraft.gui.setScreen(new EmoteMenuScreen()); }
            case HudMenu.HEALTH -> { config.showEnemyHealth = !config.showEnemyHealth; CubeonHudConfig.save(); }
            case HudMenu.ANIMATIONS -> { config.cosmeticAnimations = !config.cosmeticAnimations; CubeonHudConfig.save(); }
            case HudMenu.WING_DEPTH -> { config.wingDepth = !config.wingDepth; CubeonHudConfig.save(); }
            case HudMenu.OTHER_COSMETICS -> { config.showOtherCosmetics = !config.showOtherCosmetics; CubeonHudConfig.save(); }
            case HudMenu.RESET -> { CubeonHudConfig.resetPositions(); CubeonHudConfig.save(); }
            case HudMenu.DONE -> onClose();
        }
        return true;
    }

    @Override public void removed() { CubeonHudConfig.save(); }
    @Override public void onClose() {
        CubeonHudConfig.save();
        if (this.minecraft != null) this.minecraft.gui.setScreen(null);
    }
    @Override public boolean isPauseScreen() { return false; }
}
