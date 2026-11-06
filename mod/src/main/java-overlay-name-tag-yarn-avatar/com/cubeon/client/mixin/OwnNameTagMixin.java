package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.entity.PlayerEntityRenderer;
import net.minecraft.entity.PlayerLikeEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Opt-in local third-person label, using Minecraft's normal nameplate pipeline. */
@Mixin(PlayerEntityRenderer.class)
public abstract class OwnNameTagMixin {
    @Inject(method="hasLabel(Lnet/minecraft/entity/PlayerLikeEntity;D)Z", at=@At("HEAD"), cancellable=true, require=1)
    private void cubeon$ownNameTag(PlayerLikeEntity entity, double distance, CallbackInfoReturnable<Boolean> ci) {
        var client = MinecraftClient.getInstance();
        if (client == null || client.player == null || entity != client.player
                || !CubeonHudConfig.get().showOwnNameTag) return;
        ci.setReturnValue(!client.options.getPerspective().isFirstPerson()
                && MinecraftClient.isHudEnabled() && !entity.isInvisibleTo(client.player)
                && !entity.isSpectator() && !entity.hasPassengers()
                && distance < (entity.isSneaky() ? 1024 : 4096));
    }
}
