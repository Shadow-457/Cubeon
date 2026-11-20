package com.cubeon.forge;

import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.HudFeatures;
import com.cubeon.client.ui.HudMenu;
import net.minecraft.client.audio.PositionedSoundRecord;
import net.minecraft.client.gui.GuiScreen;
import net.minecraft.client.renderer.GlStateManager;
import net.minecraft.util.ResourceLocation;
import org.lwjgl.input.Keyboard;
import org.lwjgl.input.Mouse;

/**
 * 1.8.9 host for the shared Cubeon Client menu. Layout, artwork, labels and
 * behaviour come from {@link HudMenu}; this class only adapts native input.
 */
public final class ClientScreen extends GuiScreen {
    private final GuiScreen parent;
    private final HudMenu menu = new HudMenu();
    private final MenuConfig settings = new MenuConfig();

    public ClientScreen(GuiScreen parent) { this.parent = parent; }

    @Override public void initGui() { menu.layout(width, height); }
    @Override public boolean doesGuiPauseGame() { return false; }

    @Override public void drawScreen(int mouseX, int mouseY, float partial) {
        drawDefaultBackground();
        menu.render(new ForgeCanvas(), width, height, mouseX, mouseY, settings);
        GlStateManager.color(1.0F, 1.0F, 1.0F, 1.0F);
        super.drawScreen(mouseX, mouseY, partial);
    }

    @Override protected void mouseClicked(int x, int y, int button) {
        if (button == 1) { close(); return; }
        if (button != 0) return;
        if (!menu.beginScale(x, y)) choose(menu.hit(x, y));
    }

    @Override protected void mouseClickMove(int x, int y, int button, long time) {
        if (button == 0) menu.dragScale(x);
    }

    @Override protected void mouseReleased(int x, int y, int button) { menu.finishScale(); }

    @Override public void handleMouseInput() {
        super.handleMouseInput();
        int wheel = Mouse.getEventDWheel();
        if (wheel != 0) menu.scroll(wheel > 0 ? -1 : 1);
    }

    @Override protected void keyTyped(char typed, int key) {
        if (key == Keyboard.KEY_ESCAPE) { if (!menu.back()) close(); return; }
        if (key == Keyboard.KEY_BACK) { if (!menu.backspace()) menu.back(); return; }
        // The search field and the custom-theme hex field own printable keys.
        if (menu.searchFocused()) {
            if (typed >= 32 && typed != 127) menu.type(typed);
            return;
        }
        if (key == Keyboard.KEY_LEFT && menu.adjustScale(-.01F)) return;
        if (key == Keyboard.KEY_RIGHT && menu.adjustScale(.01F)) return;
        if (key == Keyboard.KEY_SLASH) { menu.focusSearchShortcut(); return; }
        if (key >= Keyboard.KEY_1 && key <= Keyboard.KEY_5) { choose((key - Keyboard.KEY_1) * 3); return; }
        if (key == Keyboard.KEY_LEFT || key == Keyboard.KEY_UP) { menu.step(-1); return; }
        if (key == Keyboard.KEY_RIGHT || key == Keyboard.KEY_DOWN || key == Keyboard.KEY_TAB) { menu.step(1); return; }
        if (key == Keyboard.KEY_RETURN || key == Keyboard.KEY_NUMPADENTER || key == Keyboard.KEY_SPACE) {
            choose(menu.selection()); return;
        }
        if (key == Keyboard.KEY_G) { choose(HudMenu.FRIENDS); return; }
        if (key == Keyboard.KEY_E) { choose(HudMenu.EMOTES); return; }
        if (key == Keyboard.KEY_RSHIFT) close();
    }

    private void choose(int action) {
        if (action < 0 || action >= HudMenu.ACTION_COUNT) return;
        menu.press(action);
        mc.getSoundHandler().playSound(PositionedSoundRecord.create(
                new ResourceLocation("gui.button.press"), 1.0F));
        // Back, categories, paging, theme screens, search and the size slider live in HudMenu.
        if (menu.activate(action)) return;
        int overlay = HudMenu.overlayIndex(action);
        if (overlay >= 0) {
            int operation = HudMenu.overlayOperation(action);
            if (operation == 0) Hud189.toggle(HudFeatures.ALL[overlay]);
            else if (operation == 1) mc.displayGuiScreen(new HudEditor(this, HudFeatures.ALL[overlay]));
            return;
        }
        CubeonHudConfig config = CubeonHudConfig.get();
        switch (action) {
            case HudMenu.HUD_EDITOR: mc.displayGuiScreen(new HudEditor(this, null)); break;
            case HudMenu.RESET: CubeonHudConfig.resetPositions(); CubeonHudConfig.save(); break;
            case HudMenu.EMOTES: mc.displayGuiScreen(new EmoteScreen()); break;
            case HudMenu.FRIENDS: mc.displayGuiScreen(new FriendsScreen(this)); break;
            case HudMenu.DONE: close(); break;
            case HudMenu.SPRINT: config.autoSprint = !config.autoSprint; CubeonHudConfig.save(); break;
            case HudMenu.CLOCK_MODE: config.worldClock = !config.worldClock; CubeonHudConfig.save(); break;
            case HudMenu.HEALTH: config.showEnemyHealth = !config.showEnemyHealth; CubeonHudConfig.save(); break;
            case HudMenu.ANIMATIONS: config.cosmeticAnimations = !config.cosmeticAnimations; CubeonHudConfig.save(); break;
            case HudMenu.WING_DEPTH: config.wingDepth = !config.wingDepth; CubeonHudConfig.save(); break;
            case HudMenu.OTHER_COSMETICS: config.showOtherCosmetics = !config.showOtherCosmetics; CubeonHudConfig.save(); break;
            case HudMenu.CAMERA_BLUR: config.cameraMotionBlur = !config.cameraMotionBlur; CubeonHudConfig.save(); break;
            case HudMenu.FULL_BRIGHT: config.fullBright = !config.fullBright; CubeonHudConfig.save(); break;
            case HudMenu.MENU_ANIMATIONS: config.menuAnimations = !config.menuAnimations; CubeonHudConfig.save(); break;
            case HudMenu.OWN_NAME_TAG: config.showOwnNameTag = !config.showOwnNameTag; CubeonHudConfig.save(); break;
            default: break;
        }
    }

    private void close() { mc.displayGuiScreen(parent); }
}
