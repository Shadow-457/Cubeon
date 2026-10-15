package dev.keyhud.client.mixin;

import dev.keyhud.client.PingProbe;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.ping.ClientboundPongResponsePacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Feeds the pong responses vanilla's ping monitor also receives into KeyHUD's own
 * latency measurement, so the HUD ping updates every second instead of waiting for
 * the next tab-list update.
 */
@Mixin(ClientPacketListener.class)
public class ClientPacketListenerMixin {
	@Inject(
			method = "handlePongResponse(Lnet/minecraft/network/protocol/ping/ClientboundPongResponsePacket;)V",
			at = @At("HEAD")
	)
	private void keyhud$onPongResponse(ClientboundPongResponsePacket packet, CallbackInfo ci) {
		PingProbe.onPong(packet.time());
	}
}
