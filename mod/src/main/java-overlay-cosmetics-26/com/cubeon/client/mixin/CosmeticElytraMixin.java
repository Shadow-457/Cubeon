package com.cubeon.client.mixin;

import com.cubeon.client.cosmetics.CosmeticElytra;
import com.mojang.blaze3d.vertex.PoseStack;
import net.minecraft.client.renderer.SubmitNodeCollector;
import net.minecraft.client.renderer.entity.layers.WingsLayer;
import net.minecraft.client.renderer.entity.state.HumanoidRenderState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Hide vanilla wings only after this player's cosmetic wing draw succeeded. */
@Mixin(WingsLayer.class)
public abstract class CosmeticElytraMixin {
    @Inject(method = "submit(Lcom/mojang/blaze3d/vertex/PoseStack;Lnet/minecraft/client/renderer/SubmitNodeCollector;ILnet/minecraft/client/renderer/entity/state/HumanoidRenderState;FF)V", at = @At("HEAD"), cancellable = true)
    private void cubeon$elytra(PoseStack pose, SubmitNodeCollector collector, int light,
                              HumanoidRenderState player, float limbAngle, float limbDistance,
                              CallbackInfo ci) {
        if (CosmeticElytra.consume(player)) ci.cancel();
    }
}
