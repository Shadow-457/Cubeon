package com.cubeon.client.hud;

import com.mojang.blaze3d.platform.InputConstants;
import com.cubeon.client.hud.screen.CubeonHudMenuScreen;
import com.cubeon.client.cosmetics.CosmeticSelection;
import com.cubeon.client.cosmetics.WingAction;
import net.fabricmc.fabric.api.client.keymapping.v1.KeyMappingHelper;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.resources.Identifier;

/**
 * The single "open the Cubeon Client menu" key. Registered in its own category so it can be
 * rebound from Settings -> Controls -> Key Binds -> Cubeon Client like any vanilla key.
 */
public final class CubeonHudKeybinds {
	public static final KeyMapping.Category CATEGORY =
			KeyMapping.Category.register(Identifier.fromNamespaceAndPath(CubeonHudClient.MOD_ID, "main"));

	// 26.3 uses native keyboard scan codes, not the older GLFW key symbols.
	private static final int KEY_OPEN_MENU = InputConstants.KEY_K;

	private static KeyMapping openMenu;
	private static KeyMapping emotes;
	private static KeyMapping wingFlare;
	private static KeyMapping freelook;

	private CubeonHudKeybinds() {
	}

	public static void register() {
		openMenu = new KeyMapping(
				"key." + CubeonHudClient.MOD_ID + ".open_menu",
				// 26.3 renamed 26.1/26.2's KEYSYM to KEYBOARD (and dropped
				// SCANCODE). This overlay exists only for that spelling.
				InputConstants.Type.KEYBOARD,
				KEY_OPEN_MENU,
				CATEGORY);
		KeyMappingHelper.registerKeyMapping(openMenu);

		emotes = new KeyMapping(
				"key." + CubeonHudClient.MOD_ID + ".emotes",
				// 26.3 renamed 26.1/26.2's KEYSYM to KEYBOARD (and dropped
				// SCANCODE). This overlay exists only for that spelling.
				InputConstants.Type.KEYBOARD,
				InputConstants.KEY_B,
				CATEGORY);
		KeyMappingHelper.registerKeyMapping(emotes);

		wingFlare = new KeyMapping(
				"key." + CubeonHudClient.MOD_ID + ".wing_flare",
				// 26.3 renamed 26.1/26.2's KEYSYM to KEYBOARD (and dropped
				// SCANCODE). This overlay exists only for that spelling.
				InputConstants.Type.KEYBOARD,
				InputConstants.KEY_N,
				CATEGORY);
		KeyMappingHelper.registerKeyMapping(wingFlare);

		freelook = new KeyMapping(
				"key." + CubeonHudClient.MOD_ID + ".freelook",
				// 26.3 renamed 26.1/26.2's KEYSYM to KEYBOARD (and dropped
				// SCANCODE). This overlay exists only for that spelling.
				InputConstants.Type.KEYBOARD,
				InputConstants.KEY_LALT,
				CATEGORY);
		KeyMappingHelper.registerKeyMapping(freelook);
	}

	/** Called once per client tick; opens the menu when the key was newly pressed. */
	public static void tick() {
		Minecraft client = Minecraft.getInstance();
		FreelookController.sync();

        boolean wingPressed = false;
        while (wingFlare != null && wingFlare.consumeClick()) wingPressed = true;
        WingAction.INSTANCE.tick(wingFlare != null && wingFlare.isDown(), wingPressed,
                freelookEligible() && CubeonHudConfig.get().cosmeticAnimations,
                client.player, client.level, CosmeticSelection.selectedWing(),
                client.player == null ? 0 : client.player.tickCount / 20.0f);


		// Vanilla only presses key mappings while no screen is open, so this cannot fight a GUI.
		if (client.player == null || client.level == null || client.gui.screen() != null) {
			return;
		}

		if (emotes.consumeClick()) {
			client.gui.setScreen(new com.cubeon.client.hud.screen.EmoteMenuScreen());
		}

		if (openMenu.consumeClick()) {
			client.gui.setScreen(new CubeonHudMenuScreen());
		}
	}

    public static boolean freelookHeld() { return freelook != null && freelook.isDown(); }
    public static boolean freelookEligible() {
        Minecraft client = Minecraft.getInstance();
        return client.player != null && client.level != null && client.gui.screen() == null
                && client.isWindowActive() && client.mouseHandler.isMouseGrabbed()
                && client.getCameraEntity() == client.player && client.player.isAlive() && !client.player.isSleeping();
    }
}
