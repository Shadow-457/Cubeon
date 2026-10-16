package com.cubeon.client.hud;

import com.cubeon.client.hud.screen.CubeonHudMenuScreen;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import net.minecraft.util.Identifier;

import org.lwjgl.glfw.GLFW;

/**
 * The single "open the Cubeon Client menu" key. Registered in its own category so it can be
 * rebound from Settings -> Controls -> Key Binds -> Cubeon Client like any vanilla key.
 */
public final class CubeonHudKeybinds {
	public static final KeyBinding.Category CATEGORY =
			KeyBinding.Category.create(Identifier.of(CubeonHudClient.MOD_ID, "main"));

	/** Vanilla 1.21.11 leaves K unbound; users can rebind it in the controls screen. */
	private static KeyBinding openMenu;

	private CubeonHudKeybinds() {
	}

	public static void register() {
		openMenu = new KeyBinding(
				"key." + CubeonHudClient.MOD_ID + ".open_menu",
				InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_K,
				CATEGORY);
		KeyBindingHelper.registerKeyBinding(openMenu);
	}

	/** Called once per client tick; opens the menu when the key was newly pressed. */
	public static void tick() {
		MinecraftClient client = MinecraftClient.getInstance();

		// Vanilla only presses keybindings while no screen is open, so this cannot fight a GUI.
		if (client.player == null || client.world == null || client.currentScreen != null) {
			return;
		}

		if (openMenu.wasPressed()) {
			client.setScreen(new CubeonHudMenuScreen());
		}
	}
}
