package com.emotesmod.client;

import com.emotesmod.Emote;
import com.emotesmod.EmotesMod;
import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.fabric.api.client.keymapping.v1.KeyMappingHelper;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.resources.Identifier;

/**
 * One configurable key per emote, grouped under their own category in the controls screen.
 */
public final class EmoteKeybinds {
	public static final KeyMapping.Category CATEGORY =
			KeyMapping.Category.register(Identifier.fromNamespaceAndPath(EmotesMod.MOD_ID, "main"));

	// Raw keyboard scan codes, the same values vanilla uses for its own default bindings
	// (87 = W for "key.forward", 65 = A for "key.left", and so on). Vanilla 1.21.11 leaves
	// every one of these completely unbound. Users can rebind them in
	// Settings -> Controls -> Key Binds -> Emotes.
	private static final int KEY_WAVE = 74;   // J
	private static final int KEY_DANCE = 76;  // L
	private static final int KEY_BOW = 85;    // U
	private static final int KEY_SALUTE = 79; // O
	private static final int KEY_SHRUG = 77;  // M
	private static final int KEY_POINT = 78;  // N

	private static final int[] DEFAULT_KEYS = {
			KEY_WAVE, KEY_DANCE, KEY_BOW, KEY_SALUTE, KEY_SHRUG, KEY_POINT,
	};

	private static final KeyMapping[] BINDINGS = new KeyMapping[Emote.values().length];

	private EmoteKeybinds() {
	}

	public static void register() {
		Emote[] emotes = Emote.values();

		for (int i = 0; i < emotes.length; i++) {
			Emote emote = emotes[i];
			int defaultKey = i < DEFAULT_KEYS.length ? DEFAULT_KEYS[i] : InputConstants.UNKNOWN.getValue();
			KeyMapping mapping = new KeyMapping(
					"key." + EmotesMod.MOD_ID + "." + emote.getName(),
					InputConstants.Type.KEYBOARD,
					defaultKey,
					CATEGORY);
			KeyMappingHelper.registerKeyMapping(mapping);
			BINDINGS[i] = mapping;
		}
	}

	/** Called once per client tick; fires any emote whose key was newly pressed. */
	public static void tick() {
		Minecraft client = Minecraft.getInstance();

		// Do not fire emotes while a screen is open, or with no world to emote in.
		if (client.player == null || client.level == null || client.gui.screen() != null) {
			return;
		}

		Emote[] emotes = Emote.values();

		for (int i = 0; i < emotes.length; i++) {
			KeyMapping mapping = BINDINGS[i];

			if (mapping != null && mapping.consumeClick()) {
				ClientEmoteState.playLocally(emotes[i]);
			}
		}
	}
}
