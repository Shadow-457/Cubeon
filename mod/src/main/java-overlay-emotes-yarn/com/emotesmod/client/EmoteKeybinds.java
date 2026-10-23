package com.emotesmod.client;

import com.emotesmod.Emote;
import com.emotesmod.EmotesMod;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import net.minecraft.util.Identifier;

import org.lwjgl.glfw.GLFW;

/**
 * One configurable key per emote, grouped under their own category in the controls screen.
 */
public final class EmoteKeybinds {
	public static final KeyBinding.Category CATEGORY =
			KeyBinding.Category.create(Identifier.of(EmotesMod.MOD_ID, "main"));

	/**
	 * Default keys, chosen because vanilla 1.21.11 leaves all of them completely unbound.
	 * Users can rebind them in Settings -> Controls -> Key Binds -> Emotes.
	 */
	private static final int[] DEFAULT_KEYS = {
			GLFW.GLFW_KEY_J, // Wave
			GLFW.GLFW_KEY_L, // Dance
			GLFW.GLFW_KEY_U, // Bow
			GLFW.GLFW_KEY_O, // Salute
			GLFW.GLFW_KEY_M, // Shrug
			GLFW.GLFW_KEY_N, // Point
	};

	private static final KeyBinding[] BINDINGS = new KeyBinding[Emote.values().length];

	private EmoteKeybinds() {
	}

	public static void register() {
		Emote[] emotes = Emote.values();

		for (int i = 0; i < emotes.length; i++) {
			Emote emote = emotes[i];
			int defaultKey = i < DEFAULT_KEYS.length ? DEFAULT_KEYS[i] : InputUtil.UNKNOWN_KEY.getCode();
			KeyBinding binding = new KeyBinding(
					"key." + EmotesMod.MOD_ID + "." + emote.getName(),
					InputUtil.Type.KEYSYM,
					defaultKey,
					CATEGORY);
			KeyBindingHelper.registerKeyBinding(binding);
			BINDINGS[i] = binding;
		}
	}

	/** Called once per client tick; fires any emote whose key was newly pressed. */
	public static void tick() {
		MinecraftClient client = MinecraftClient.getInstance();

		// Do not fire emotes while a screen is open, or with no world to emote in.
		if (client.player == null || client.world == null || client.currentScreen != null) {
			return;
		}

		Emote[] emotes = Emote.values();

		for (int i = 0; i < emotes.length; i++) {
			KeyBinding binding = BINDINGS[i];

			if (binding != null && binding.wasPressed()) {
				ClientEmoteState.playLocally(emotes[i]);
			}
		}
	}
}
