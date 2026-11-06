package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.entity.player.AvatarRenderer;
import net.minecraft.world.entity.Avatar;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Opt-in local third-person label, using Minecraft's normal nameplate pipeline. */
@Mixin(AvatarRenderer.class)
public abstract class OwnNameTagMixin {
    @Inject(method="shouldShowName(Lnet/minecraft/world/entity/Avatar;D)Z", at=@At("HEAD"), cancellable=true, require=1)
    private void cubeon$ownNameTag(Avatar entity, double distance, CallbackInfoReturnable<Boolean> ci) {
        var client = Minecraft.getInstance();
        if (client == null || client.player == null || entity != client.player
                || !CubeonHudConfig.get().showOwnNameTag) return;
        ci.setReturnValue(!client.options.getCameraType().isFirstPerson()
                && !com.cubeon.client.hud.CubeonHud.hudHidden() && !entity.isInvisibleTo(client.player)
                && !entity.isSpectator() && !entity.isVehicle()
                && distance < (entity.isDiscrete() ? 1024 : 4096));
    }
}
