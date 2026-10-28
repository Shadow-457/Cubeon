package com.cubeon.client.hud;

import com.cubeon.client.hud.screen.CubeonHudMenuScreen;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;

import org.lwjgl.glfw.GLFW;

/**
 * The single "open the Cubeon Client menu" key. On this version the category is a plain
 * string that doubles as its translation key, so Settings -> Controls -> Key Binds
 * shows the Cubeon Client group like any vanilla one. Vanilla leaves K unbound; users can
 * rebind it in the controls screen.
 */
public final class CubeonHudKeybinds {
	private static KeyBinding openMenu;
	private static KeyBinding zoom;

	private CubeonHudKeybinds() {
	}

	public static void register() {
		openMenu = new KeyBinding(
				"key." + CubeonHudClient.MOD_ID + ".open_menu",
				InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_K,
				"key.category." + CubeonHudClient.MOD_ID + ".main");
		KeyBindingHelper.registerKeyBinding(openMenu);

		// Z is unbound in vanilla; the same controls screen can move it.
		zoom = new KeyBinding(
				"key." + CubeonHudClient.MOD_ID + ".zoom",
				InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_Z,
				"key.category." + CubeonHudClient.MOD_ID + ".main");
		KeyBindingHelper.registerKeyBinding(zoom);
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

	/**
	 * True while the zoom key is held in game. The FOV and scroll mixins call
	 * this every frame instead of caching the state, so a rebind takes effect
	 * immediately and no screen can end up zoomed.
	 */
	public static boolean zoomActive() {
		MinecraftClient client = MinecraftClient.getInstance();
		return zoom != null && zoom.isPressed() && client.player != null
				&& client.world != null && client.currentScreen == null;
	}
}
