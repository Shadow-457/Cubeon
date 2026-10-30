package com.cubeon.client.hud;

import com.cubeon.client.hud.screen.CubeonHudMenuScreen;
import com.cubeon.client.cosmetics.CosmeticSelection;
import com.cubeon.client.cosmetics.WingAction;
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
	private static KeyBinding emotes;
	private static KeyBinding wingFlare;
	private static KeyBinding freelook;
	private static KeyBinding zoom;

	private CubeonHudKeybinds() {
	}

	public static void register() {
		openMenu = new KeyBinding(
				"key." + CubeonHudClient.MOD_ID + ".open_menu",
				InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_K,
				CATEGORY);
		KeyBindingHelper.registerKeyBinding(openMenu);

		emotes = new KeyBinding(
				"key." + CubeonHudClient.MOD_ID + ".emotes",
				InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_B,
				CATEGORY);
		KeyBindingHelper.registerKeyBinding(emotes);

		wingFlare = new KeyBinding(
				"key." + CubeonHudClient.MOD_ID + ".wing_flare",
				InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_N,
				CATEGORY);
		KeyBindingHelper.registerKeyBinding(wingFlare);

		freelook = new KeyBinding(
				"key." + CubeonHudClient.MOD_ID + ".freelook",
				InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_LEFT_ALT,
				CATEGORY);
		KeyBindingHelper.registerKeyBinding(freelook);

		// Z is unbound in vanilla; the same controls screen can move it.
		zoom = new KeyBinding(
				"key." + CubeonHudClient.MOD_ID + ".zoom",
				InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_Z,
				CATEGORY);
		KeyBindingHelper.registerKeyBinding(zoom);
	}

	/** Called once per client tick; opens the menu when the key was newly pressed. */
	public static void tick() {
		MinecraftClient client = MinecraftClient.getInstance();
		FreelookController.sync();

        boolean wingPressed = false;
        while (wingFlare != null && wingFlare.wasPressed()) wingPressed = true;
        WingAction.INSTANCE.tick(wingFlare != null && wingFlare.isPressed(), wingPressed,
                client.player != null && client.world != null && client.currentScreen == null
                && client.isWindowFocused() && client.mouse.isCursorLocked()
                && client.getCameraEntity() == client.player && client.player.isAlive()
                && !client.player.isSleeping() && CubeonHudConfig.get().cosmeticAnimations,
                client.player, client.world, CosmeticSelection.selectedWing(),
                client.player == null ? 0 : client.player.age / 20.0f);


		// Vanilla only presses keybindings while no screen is open, so this cannot fight a GUI.
		if (client.player == null || client.world == null || client.currentScreen != null) {
			return;
		}

		if (emotes.wasPressed()) {
			client.setScreen(new com.cubeon.client.hud.screen.EmoteMenuScreen());
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
				&& client.world != null && client.currentScreen == null && !FreelookController.sync();
	}

    public static boolean freelookHeld() { return freelook != null && freelook.isPressed(); }
}
