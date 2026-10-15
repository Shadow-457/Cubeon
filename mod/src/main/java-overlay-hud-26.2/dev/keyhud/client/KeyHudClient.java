package dev.keyhud.client;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * KeyHUD - client side entry point: config load, the menu keybind and the HUD overlays.
 */
public final class KeyHudClient implements ClientModInitializer {
	public static final String MOD_ID = "keyhud";

	public static final Logger LOGGER = LoggerFactory.getLogger("KeyHUD");

	@Override
	public void onInitializeClient() {
		// Fabric API is a *recommended* dependency of this mod, not a required one:
		// a player without it must lose the HUD, never the game. Every HUD call
		// below goes through Fabric API, so without it this block throws
		// NoClassDefFoundError - and letting that escape would take the whole
		// Cubeon Client entrypoint down, costing the player the Cubeon button as
		// well. The launcher installs Fabric API; this is the belt to that brace.
		try {
			KeyHudConfig.load();
			KeyHudKeybinds.register();
			KeyHudHud.register();

			ClientTickEvents.END_CLIENT_TICK.register(client -> KeyHudKeybinds.tick());
			ClientTickEvents.END_CLIENT_TICK.register(client -> PingProbe.tick());
		} catch (Throwable missingApi) {
			LOGGER.warn("KeyHUD overlays unavailable (Fabric API missing?): {}",
					missingApi.toString());
		}
	}
}
