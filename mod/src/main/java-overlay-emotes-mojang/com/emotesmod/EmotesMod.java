package com.emotesmod;

import com.emotesmod.net.EmoteRequestPayload;
import net.fabricmc.api.ModInitializer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Emotes - adds six character emotes that every player can trigger and that are
 * synchronised to everyone nearby.
 */
public final class EmotesMod implements ModInitializer {
	public static final String MOD_ID = "emotes";

	/** Sub-command of {@code /emote} that cancels the current emote. */
	public static final String STOP_COMMAND = "stop";

	public static final Logger LOGGER = LoggerFactory.getLogger("Emotes");

	@Override
	public void onInitialize() {
		try {
			EmoteNetworking.registerPayloads();
			EmoteNetworking.registerServerbound();
			EmoteCommand.register();
			LOGGER.info("Emotes ready: {} emotes registered.", Emote.values().length);
		} catch (Throwable t) {
			LOGGER.warn("Emotes unavailable (Fabric API missing?): {}", t.toString());
		}
	}
}
