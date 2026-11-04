package com.cubeon.client.mixin;

import com.cubeon.client.cosmetics.CosmeticElytra;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.client.render.VertexConsumerProvider;
import net.minecraft.client.render.entity.feature.ElytraFeatureRenderer;
import net.minecraft.entity.LivingEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Hide vanilla wings only after this player's cosmetic wing draw succeeded. */
@Mixin(ElytraFeatureRenderer.class)
public abstract class CosmeticElytraMixin {
    @Inject(method = "render(Lnet/minecraft/client/util/math/MatrixStack;Lnet/minecraft/client/render/VertexConsumerProvider;ILnet/minecraft/entity/LivingEntity;FFFFFF)V", at = @At("HEAD"), cancellable = true)
    private void cubeon$elytra(MatrixStack pose, VertexConsumerProvider output, int light,
                              LivingEntity player, float limbAngle, float limbDistance,
                              float tickDelta, float age, float headYaw, float headPitch,
                              CallbackInfo ci) {
        if (CosmeticElytra.consume(player)) ci.cancel();
    }
}
