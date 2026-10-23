package com.emotesmod.net;

import com.emotesmod.Emote;
import com.emotesmod.EmotesMod;
import net.minecraft.network.PacketByteBuf;
import net.minecraft.network.codec.PacketCodec;
import net.minecraft.network.packet.CustomPayload;
import net.minecraft.util.Identifier;

/**
 * Client to server: "please play this emote on me".
 *
 * @param emoteId id of the emote to play, or {@link Emote#STOP_ID} to stop the current one
 * @param serial  client generated counter echoed back by the server, used to match the
 *                optimistic local prediction with the authoritative broadcast
 */
public record EmoteRequestPayload(int emoteId, int serial) implements CustomPayload {
	public static final CustomPayload.Id<EmoteRequestPayload> ID =
			new CustomPayload.Id<>(Identifier.of(EmotesMod.MOD_ID, "request"));

	public static final PacketCodec<PacketByteBuf, EmoteRequestPayload> CODEC =
			CustomPayload.codecOf(EmoteRequestPayload::write, EmoteRequestPayload::new);

	public Emote emote() {
		return Emote.byId(this.emoteId);
	}

	private EmoteRequestPayload(PacketByteBuf buf) {
		this(buf.readByte(), buf.readVarInt());
	}

	private void write(PacketByteBuf buf) {
		buf.writeByte(this.emoteId);
		buf.writeVarInt(this.serial);
	}

	@Override
	public CustomPayload.Id<EmoteRequestPayload> getId() {
		return ID;
	}
}
