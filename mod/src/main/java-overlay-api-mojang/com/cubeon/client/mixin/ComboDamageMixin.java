package com.cubeon.client.mixin;

import com.cubeon.client.hud.ExtraHud;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundDamageEventPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public abstract class ComboDamageMixin {
    @Inject(method = "handleDamageEvent", at = @At("RETURN"), require = 0)
    private void cubeon$confirmedHit(ClientboundDamageEventPacket packet, CallbackInfo ci) {
        var player = Minecraft.getInstance().player;
        if (player != null) ExtraHud.damage(packet.entityId(), packet.sourceCauseId(), packet.sourceDirectId(), player.getId(), System.currentTimeMillis());
    }
}
