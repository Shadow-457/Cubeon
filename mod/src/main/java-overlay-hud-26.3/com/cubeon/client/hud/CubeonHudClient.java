package com.cubeon.client.hud;

import com.cubeon.client.ChatCollapse;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Cubeon Client - client side entry point: config load, the menu keybind and the HUD overlays.
 */
public final class CubeonHudClient implements ClientModInitializer {
	public static final String MOD_ID = "cubeon-client";

	public static final Logger LOGGER = LoggerFactory.getLogger("Cubeon Client");

	@Override
	public void onInitializeClient() {
		// Fabric API is a *recommended* dependency of this mod, not a required one:
		// a player without it must lose the HUD, never the game. Every HUD call
		// below goes through Fabric API, so without it this block throws
		// NoClassDefFoundError - and letting that escape would take the whole
		// Cubeon Client entrypoint down, costing the player the Cubeon button as
		// well. The launcher installs Fabric API; this is the belt to that brace.
		try {
			CubeonHudConfig.load();
			ChatCollapse.register();
			CubeonHudKeybinds.register();
			CubeonHud.register();

			ClientTickEvents.END_CLIENT_TICK.register(client -> {
				CubeonHudKeybinds.tick();
				com.cubeon.client.emotes.EmoteClient.tick();
			});
			ClientTickEvents.END_CLIENT_TICK.register(client -> PingProbe.tick());
		} catch (Throwable missingApi) {
			LOGGER.warn("Cubeon Client overlays unavailable (Fabric API missing?): {}",
					missingApi.toString());
		}
	}
}
