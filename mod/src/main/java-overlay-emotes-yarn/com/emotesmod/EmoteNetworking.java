package com.emotesmod;

import com.emotesmod.net.EmoteRequestPayload;
import com.emotesmod.net.EmoteStatePayload;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.PlayerLookup;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerPlayerEntity;

import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Server side of the emote protocol.
 *
 * <p>The server is authoritative: a client asks for an emote, the server validates the
 * request and then broadcasts the result to everyone tracking that player (including the
 * player themself, which is how the client learns that its request was accepted).
 */
public final class EmoteNetworking {
	/** Minimum number of server ticks between two accepted emote requests from one player. */
	private static final long COOLDOWN_TICKS = 5L;

	/** Server tick of the last accepted request, per player. */
	private static final Map<UUID, Long> LAST_REQUEST_TICK = new ConcurrentHashMap<>();

	private EmoteNetworking() {
	}

	/**
	 * Registers both payload types. Runs on the client and the server, and has to happen
	 * before any receiver is registered.
	 */
	public static void registerPayloads() {
		PayloadTypeRegistry.playC2S().register(EmoteRequestPayload.ID, EmoteRequestPayload.CODEC);
		PayloadTypeRegistry.playS2C().register(EmoteStatePayload.ID, EmoteStatePayload.CODEC);
	}

	/** Call once from the common initializer. */
	public static void registerServerbound() {
		ServerPlayNetworking.registerGlobalReceiver(EmoteRequestPayload.ID,
				(payload, context) -> context.server().execute(() -> handleRequest(payload, context)));

		ServerPlayConnectionEvents.DISCONNECT.register(
				(handler, server) -> LAST_REQUEST_TICK.remove(handler.getPlayer().getUuid()));
	}

	private static void handleRequest(EmoteRequestPayload payload,
			ServerPlayNetworking.Context context) {
		ServerPlayerEntity player = context.player();

		// Never trust the client: make sure this is a living, non-spectating player.
		if (player == null || !player.isAlive() || player.isDead() || player.isSpectator()) {
			return;
		}

		MinecraftServer server = context.server();
		long now = server.getTicks();
		UUID uuid = player.getUuid();
		Long last = LAST_REQUEST_TICK.get(uuid);

		if (last != null && now - last < COOLDOWN_TICKS) {
			return;
		}

		LAST_REQUEST_TICK.put(uuid, now);

		if (payload.emoteId() == Emote.STOP_ID) {
			broadcast(player, Emote.STOP_ID, 0);
			return;
		}

		Emote emote = payload.emote();

		// Unknown emote id - the client is running a different version of the mod.
		if (emote == null) {
			return;
		}

		broadcast(player, emote.id(), payload.serial());
	}

	/**
	 * Starts {@code emote} on {@code player} and tells everyone who can see them about it.
	 *
	 * @param serial value echoed back so the requesting client can keep its own start time
	 * @return {@code true} if the emote was broadcast
	 */
	public static boolean playFor(ServerPlayerEntity player, Emote emote, int serial) {
		if (emote == null) {
			return false;
		}

		broadcast(player, emote.id(), serial);
		return true;
	}

	/** Stops whatever emote {@code player} is currently playing. */
	public static void stopFor(ServerPlayerEntity player) {
		broadcast(player, Emote.STOP_ID, 0);
	}

	/**
	 * Sends the emote state to every player that can see {@code player}.
	 *
	 * <p>The acting player is always included explicitly: vanilla never adds a player to
	 * the tracker of their own entity ({@code EntityTracker.updateTrackedStatus} starts
	 * with {@code if (player != this.entity)}), so {@link PlayerLookup#tracking} on its
	 * own would leave the sender without the authoritative confirmation.
	 */
	private static void broadcast(ServerPlayerEntity player, int emoteId, int serial) {
		EmoteStatePayload payload = new EmoteStatePayload(player.getId(), emoteId, serial);
		Collection<ServerPlayerEntity> viewers = new LinkedHashSet<>(PlayerLookup.tracking(player));
		viewers.add(player);

		for (ServerPlayerEntity viewer : viewers) {
			ServerPlayNetworking.send(viewer, payload);
		}
	}
}
