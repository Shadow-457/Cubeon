package com.emotesmod.client;

import com.emotesmod.Emote;
import com.emotesmod.net.EmoteRequestPayload;
import com.emotesmod.net.EmoteStatePayload;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayConnectionEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;

import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/**
 * Tracks which entity is currently playing which emote, and when it started.
 *
 * <p>Time is measured in client ticks rather than wall clock so that emotes pause with
 * the game, resume correctly after unpausing and stay smooth under {@code /tick freeze}.
 */
public final class ClientEmoteState {
	/** A single running emote. */
	public record Active(Emote emote, int serial, long startTick) {
	}

	private static final Map<Integer, Active> ACTIVE = new HashMap<>();

	/** Monotonically increasing client tick counter. */
	private static long tick;

	/** Serial number of the last emote this client requested, echoed back by the server. */
	private static int lastSerial;

	private ClientEmoteState() {
	}

	public static void register() {
		ClientTickEvents.END_CLIENT_TICK.register(client -> {
			tick++;
			sweep();
		});

		ClientPlayNetworking.registerGlobalReceiver(EmoteStatePayload.ID,
				(payload, context) -> context.client().execute(() -> apply(payload)));

		ClientPlayConnectionEvents.DISCONNECT.register((handler, client) -> clear());
		ClientPlayConnectionEvents.JOIN.register((handler, sender, client) -> clear());
	}

	public static Active get(int entityId) {
		return ACTIVE.get(entityId);
	}

	/**
	 * Local, immediate playback. Called the moment a key is pressed so the player does not
	 * have to wait for a round trip before seeing their own emote.
	 */
	public static int playLocally(Emote emote) {
		if (!ClientPlayNetworking.canSend(EmoteRequestPayload.ID)) {
			return 0;
		}

		Minecraft client = Minecraft.getInstance();

		if (client.player == null || client.level == null) {
			return 0;
		}

		int serial = ++lastSerial;
		ACTIVE.put(client.player.getId(), new Active(emote, serial, tick));
		ClientPlayNetworking.send(new EmoteRequestPayload(emote.id(), serial));
		return serial;
	}

	/** Drops every tracked emote. Called when leaving or joining a world. */
	public static void clear() {
		ACTIVE.clear();
	}

	/**
	 * Applies an authoritative update from the server.
	 *
	 * <p>If the update matches the emote this client optimistically started, the existing
	 * start tick is kept so the animation does not visibly restart.
	 */
	private static void apply(EmoteStatePayload payload) {
		Minecraft client = Minecraft.getInstance();

		// Entity ids are recycled, so drop everything once we leave a world.
		if (client.player == null || client.level == null) {
			clear();
			return;
		}

		Emote emote = payload.emote();

		if (emote == null) {
			ACTIVE.remove(payload.entityId());
			return;
		}

		Active current = ACTIVE.get(payload.entityId());

		if (current != null && current.serial() == payload.serial() && current.emote() == emote) {
			// Our own prediction was accepted - keep it running as-is.
			return;
		}

		ACTIVE.put(payload.entityId(), new Active(emote, payload.serial(), tick));
	}

	/** Drops emote entries that have run past their duration. */
	private static void sweep() {
		if (ACTIVE.isEmpty()) {
			return;
		}

		Iterator<Map.Entry<Integer, Active>> iterator = ACTIVE.entrySet().iterator();

		while (iterator.hasNext()) {
			Active active = iterator.next().getValue();
			float age = (tick - active.startTick()) / 20.0F;

			if (age >= active.emote().durationSeconds()) {
				iterator.remove();
			}
		}
	}

	/**
	 * Age of an emote in seconds, interpolated between ticks for smooth rendering.
	 *
	 * @param tickProgress partial tick in the range {@code [0, 1]}
	 */
	public static float ageSeconds(Active active, float tickProgress) {
		return (tick - active.startTick() + Math.max(0.0F, Math.min(1.0F, tickProgress))) / 20.0F;
	}

	/** Convenience for the local player, used by the HUD. */
	public static Active getLocal() {
		LocalPlayer player = Minecraft.getInstance().player;
		return player == null ? null : ACTIVE.get(player.getId());
	}
}
