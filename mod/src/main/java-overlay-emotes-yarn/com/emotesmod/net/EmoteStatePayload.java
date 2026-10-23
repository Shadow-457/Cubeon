package com.emotesmod.net;

import com.emotesmod.Emote;
import com.emotesmod.EmotesMod;
import net.minecraft.network.PacketByteBuf;
import net.minecraft.network.codec.PacketCodec;
import net.minecraft.network.packet.CustomPayload;
import net.minecraft.util.Identifier;

/**
 * Server to client: the authoritative emote state of a single entity.
 *
 * <p>Sent to every player that is tracking the entity, including the entity themself.
 *
 * @param entityId network id of the entity the emote belongs to
 * @param emoteId  id of the emote to play, or {@link Emote#STOP_ID} to stop the current one
 * @param serial   value the requesting client sent along, used to keep the local
 *                 prediction's start time instead of restarting the animation
 */
public record EmoteStatePayload(int entityId, int emoteId, int serial) implements CustomPayload {
	public static final CustomPayload.Id<EmoteStatePayload> ID =
			new CustomPayload.Id<>(Identifier.of(EmotesMod.MOD_ID, "state"));

	public static final PacketCodec<PacketByteBuf, EmoteStatePayload> CODEC =
			CustomPayload.codecOf(EmoteStatePayload::write, EmoteStatePayload::new);

	public Emote emote() {
		return Emote.byId(this.emoteId);
	}

	private EmoteStatePayload(PacketByteBuf buf) {
		this(buf.readVarInt(), buf.readByte(), buf.readVarInt());
	}

	private void write(PacketByteBuf buf) {
		buf.writeVarInt(this.entityId);
		buf.writeByte(this.emoteId);
		buf.writeVarInt(this.serial);
	}

	@Override
	public CustomPayload.Id<EmoteStatePayload> getId() {
		return ID;
	}
}
