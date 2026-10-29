package com.cubeon.client.hud;

import com.mojang.blaze3d.platform.InputConstants;
import com.cubeon.client.hud.screen.CubeonHudMenuScreen;
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

	// Raw keyboard scan code for K, the same values vanilla uses for its own default
	// bindings (75 = K). Vanilla leaves this key completely unbound; users can
	// rebind it in Settings -> Controls -> Key Binds -> Cubeon Client.
	private static final int KEY_OPEN_MENU = 75;

	private static KeyMapping openMenu;
	private static KeyMapping emotes;

	private CubeonHudKeybinds() {
	}

	public static void register() {
		openMenu = new KeyMapping(
				"key." + CubeonHudClient.MOD_ID + ".open_menu",
				// 26.1/26.2 still call this KEYSYM; 26.3 renamed it to KEYBOARD
				// (and dropped SCANCODE). One overlay per spelling - see hud-26.3.
				InputConstants.Type.KEYSYM,
				KEY_OPEN_MENU,
				CATEGORY);
		KeyMappingHelper.registerKeyMapping(openMenu);

		emotes = new KeyMapping(
				"key." + CubeonHudClient.MOD_ID + ".emotes",
				// 26.1/26.2 still call this KEYSYM; 26.3 renamed it to KEYBOARD
				// (and dropped SCANCODE). One overlay per spelling - see hud-26.3.
				InputConstants.Type.KEYSYM,
				66,
				CATEGORY);
		KeyMappingHelper.registerKeyMapping(emotes);
	}

	/** Called once per client tick; opens the menu when the key was newly pressed. */
	public static void tick() {
		Minecraft client = Minecraft.getInstance();

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
}
