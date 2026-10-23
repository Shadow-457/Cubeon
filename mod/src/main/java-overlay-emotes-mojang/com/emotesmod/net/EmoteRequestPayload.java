package com.emotesmod.net;

import com.emotesmod.Emote;
import com.emotesmod.EmotesMod;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;

/**
 * Client to server: "please play this emote on me".
 *
 * @param emoteId id of the emote to play, or {@link Emote#STOP_ID} to stop the current one
 * @param serial  client generated counter echoed back by the server, used to match the
 *                optimistic local prediction with the authoritative broadcast
 */
public record EmoteRequestPayload(int emoteId, int serial) implements CustomPacketPayload {
	public static final CustomPacketPayload.Type<EmoteRequestPayload> ID =
			new CustomPacketPayload.Type<>(Identifier.fromNamespaceAndPath(EmotesMod.MOD_ID, "request"));

	public static final StreamCodec<FriendlyByteBuf, EmoteRequestPayload> CODEC =
			CustomPacketPayload.codec(EmoteRequestPayload::write, EmoteRequestPayload::new);

	public Emote emote() {
		return Emote.byId(this.emoteId);
	}

	private EmoteRequestPayload(FriendlyByteBuf buf) {
		this(buf.readByte(), buf.readVarInt());
	}

	private void write(FriendlyByteBuf buf) {
		buf.writeByte(this.emoteId);
		buf.writeVarInt(this.serial);
	}

	@Override
	public CustomPacketPayload.Type<EmoteRequestPayload> type() {
		return ID;
	}
}
