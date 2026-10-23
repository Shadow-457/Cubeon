package com.emotesmod.client;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;

/**
 * Client side entry point: networking, keybinds and the HUD readout.
 */
public final class EmotesClient implements ClientModInitializer {
	@Override
	public void onInitializeClient() {
		ClientEmoteState.register();
		EmoteKeybinds.register();
		EmoteHud.register();

		ClientTickEvents.END_CLIENT_TICK.register(client -> EmoteKeybinds.tick());
	}
}
