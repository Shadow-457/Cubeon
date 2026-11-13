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
    private final HudMenu menu = new HudMenu();
    private final HudMenu.Settings settings = new HudMenu.Settings() {
        public boolean visible(int index) {
            var config = CubeonHudConfig.get();
            return switch (OVERLAYS[index]) {
                case FPS -> config.showFps; case KEYS -> config.showKeys;
                case ARMOR -> config.showArmor; case PING -> config.showPing; case CPS -> config.showCps;
                default -> config.extraEnabled(CubeonHud.slotOf(OVERLAYS[index]));
            };
        }
        public float scale(int index) { return CubeonHud.scaleOf(OVERLAYS[index]); }
        public void setScale(int index, float value) { CubeonHudConfig.get().setScaleForLive(CubeonHud.slotOf(OVERLAYS[index]), value); }
        public void save() { CubeonHudConfig.save(); }
        public boolean menuAnimations() { return CubeonHudConfig.get().menuAnimations; }
        public boolean blurPlus() { return CubeonHudConfig.get().temporalMotionBlur; }
        public float blurPlusStrength() { return CubeonHudConfig.get().temporalBlurStrength; }
        public void setBlurPlusStrength(float value) { CubeonHudConfig.get().temporalBlurStrength=value; com.cubeon.client.hud.blur.CameraBlurRenderer.reset(); }
        public boolean ownNameTag() { return CubeonHudConfig.get().showOwnNameTag; }
        public boolean health() { return CubeonHudConfig.get().showEnemyHealth; }
        public boolean animations() { return CubeonHudConfig.get().cosmeticAnimations; }
        public boolean wingDepth() { return CubeonHudConfig.get().wingDepth; }
        public boolean otherCosmetics() { return CubeonHudConfig.get().showOtherCosmetics; }
        public boolean cameraBlur() { return CubeonHudConfig.get().cameraMotionBlur; }
        public float blurIntensity() { return CubeonHudConfig.get().cameraBlurIntensity; }
        public boolean sprint() { return CubeonHudConfig.get().autoSprint; }
        public boolean worldClock() { return CubeonHudConfig.get().worldClock; }
    };
    public CubeonHudMenuScreen() { super(Component.translatable("cubeonclient.menu.title")); }
    @Override protected void init() { menu.layout(this.width, this.height); }
    @Override public void extractBackground(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float partialTick) {
        if (minecraft.level == null) extractPanorama(graphics, partialTick);
        extractBlurredBackground(graphics);
        graphics.fill(0, 0, this.width, this.height, 0x9309090C);
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
                var label = Component.literal(value);
                graphics.text(font, label, x - font.width(label) / 2, y, color, false);
            }
            public int width(String value) { return font.width(Component.literal(value)); }
            public String translate(String key) { return Component.translatable(key).getString(); }
        }; }
    @Override public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
        if (event.button() == 1) { onClose(); return true; }
        if (event.button() == 0) { boolean handled = menu.beginScale(event.x(), event.y()) || choose(menu.hit(event.x(), event.y())); return handled; }
        return super.mouseClicked(event, doubleClick);
    }
    @Override public boolean mouseDragged(MouseButtonEvent event, double dx, double dy) {
        return event.button() == 0 && menu.dragScale(event.x()) || super.mouseDragged(event, dx, dy);
    }
    @Override public boolean mouseReleased(MouseButtonEvent event) {
        return event.button() == 0 && menu.finishScale() || super.mouseReleased(event);
    }
    @Override public boolean keyPressed(KeyEvent event) {
        return key(event.key()) || super.keyPressed(event);
    }

    @Override public boolean charTyped(net.minecraft.client.input.CharacterEvent event) {
        return menu.type(event.codepoint()) || super.charTyped(event);
    }
    @Override public boolean mouseScrolled(double x, double y, double horizontal, double amount) {
        return menu.scroll(amount < 0 ? 1 : -1);
    }

    private boolean key(int key) {
        if (key == GLFW.GLFW_KEY_ESCAPE && menu.back()) return true;
        if (key == GLFW.GLFW_KEY_BACKSPACE && menu.backspace()) return true;
        if (menu.searchFocused()) {
            if (key == GLFW.GLFW_KEY_ENTER) menu.activate(HudMenu.NONE);
            return true;
        }
        if (key == GLFW.GLFW_KEY_LEFT && menu.adjustScale(-.01f)) return true;
        if (key == GLFW.GLFW_KEY_RIGHT && menu.adjustScale(.01f)) return true;
        if (key == GLFW.GLFW_KEY_SLASH) { menu.focusSearchShortcut(); return true; }
        if (key >= GLFW.GLFW_KEY_1 && key <= GLFW.GLFW_KEY_5) return choose((key - GLFW.GLFW_KEY_1) * 3);
        if (key == GLFW.GLFW_KEY_LEFT || key == GLFW.GLFW_KEY_UP) { menu.step(-1); return true; }
        if (key == GLFW.GLFW_KEY_RIGHT || key == GLFW.GLFW_KEY_DOWN || key == GLFW.GLFW_KEY_TAB) { menu.step(1); return true; }
        if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER || key == GLFW.GLFW_KEY_SPACE) return choose(menu.selection());
        if (key == GLFW.GLFW_KEY_G) return choose(HudMenu.FRIENDS);
        if (key == GLFW.GLFW_KEY_E) return choose(HudMenu.EMOTES);
        if (key == GLFW.GLFW_KEY_K) { onClose(); return true; }
        return false;
    }

    private boolean choose(int action) {
        if (action < 0 || action >= HudMenu.ACTION_COUNT) return false;
        if (menu.activate(action)) return true;
        CubeonHudConfig config = CubeonHudConfig.get();
        int overlayIndex = HudMenu.overlayIndex(action);
        if (overlayIndex >= 0) {
            Overlay overlay = OVERLAYS[overlayIndex];
            switch (HudMenu.overlayOperation(action)) {
                case 0 -> {
                    switch (overlay) {
                        case FPS -> config.showFps = !config.showFps;
                        case KEYS -> config.showKeys = !config.showKeys;
                        case ARMOR -> config.showArmor = !config.showArmor;
                        case PING -> config.showPing = !config.showPing;
                        case CPS -> config.showCps = !config.showCps;
                        default -> { var extra = config.extra(CubeonHud.slotOf(overlay)); extra.enabled = !extra.enabled; }
                    }
                    CubeonHudConfig.save();
                }
                case 1 -> { if (this.minecraft != null) this.minecraft.gui.setScreen(new MoveOverlayScreen(this, overlay)); }
                case 2 -> { /* Size is controlled by the slider, including arrow keys. */ }
            }
            return true;
        }
        switch (action) {
            case HudMenu.HUD_EDITOR -> { if (this.minecraft != null) this.minecraft.gui.setScreen(new MoveOverlayScreen(this)); }
            case HudMenu.SKINS -> { if (this.minecraft != null) this.minecraft.gui.setScreen(new SkinLibraryScreen(this)); }
            case HudMenu.FRIENDS -> { if (this.minecraft != null) this.minecraft.gui.setScreen(new FriendsChatScreen(this)); }
            case HudMenu.EMOTES -> { if (this.minecraft != null) this.minecraft.gui.setScreen(new EmoteMenuScreen()); }
            case HudMenu.OWN_NAME_TAG -> { config.showOwnNameTag = !config.showOwnNameTag; CubeonHudConfig.save(); }
            case HudMenu.HEALTH -> { config.showEnemyHealth = !config.showEnemyHealth; CubeonHudConfig.save(); }
            case HudMenu.MENU_ANIMATIONS -> { config.menuAnimations = !config.menuAnimations; CubeonHudConfig.save(); }
            case HudMenu.ANIMATIONS -> { config.cosmeticAnimations = !config.cosmeticAnimations; CubeonHudConfig.save(); }
            case HudMenu.WING_DEPTH -> { config.wingDepth = !config.wingDepth; CubeonHudConfig.save(); }
            case HudMenu.OTHER_COSMETICS -> { config.showOtherCosmetics = !config.showOtherCosmetics; CubeonHudConfig.save(); }
            case HudMenu.BLUR_PLUS -> { config.temporalMotionBlur = !config.temporalMotionBlur;
                if(config.temporalMotionBlur) config.cameraMotionBlur=false;
                com.cubeon.client.hud.blur.CameraBlurRenderer.reset(); CubeonHudConfig.save(); }
            case HudMenu.CAMERA_BLUR -> { config.cameraMotionBlur = !config.cameraMotionBlur;
                if(config.cameraMotionBlur) config.temporalMotionBlur=false;
                com.cubeon.client.hud.blur.CameraBlurRenderer.reset(); CubeonHudConfig.save(); }
            case HudMenu.BLUR_INTENSITY -> { config.cameraBlurIntensity = HudMenu.nextBlurIntensity(config.cameraBlurIntensity);
                com.cubeon.client.hud.blur.CameraBlurRenderer.reset(); CubeonHudConfig.save(); }
            case HudMenu.SPRINT -> { config.autoSprint = !config.autoSprint; CubeonHudConfig.save(); }
            case HudMenu.CLOCK_MODE -> { config.worldClock = !config.worldClock; CubeonHudConfig.save(); }
            case HudMenu.RESET -> { CubeonHudConfig.resetPositions(); CubeonHudConfig.save(); }
            case HudMenu.DONE -> onClose();
        }
        return true;
    }

    @Override public void removed() { menu.finishScale(); CubeonHudConfig.save(); }
    @Override public void onClose() {
        CubeonHudConfig.save();
        if (this.minecraft != null) this.minecraft.gui.setScreen(null);
    }
    @Override public boolean isPauseScreen() { return false; }
}
