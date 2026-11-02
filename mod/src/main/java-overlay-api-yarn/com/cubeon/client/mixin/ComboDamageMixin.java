package com.cubeon.client.mixin;

import com.cubeon.client.hud.ExtraHud;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayNetworkHandler;
import net.minecraft.network.packet.s2c.play.EntityDamageS2CPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPlayNetworkHandler.class)
public abstract class ComboDamageMixin {
    @Inject(method = "onEntityDamage", at = @At("RETURN"), require = 0)
    private void cubeon$confirmedHit(EntityDamageS2CPacket packet, CallbackInfo ci) {
        var player = MinecraftClient.getInstance().player;
        if (player != null) ExtraHud.damage(packet.entityId(), packet.sourceCauseId(), packet.sourceDirectId(), player.getId(), System.currentTimeMillis());
    }
}
