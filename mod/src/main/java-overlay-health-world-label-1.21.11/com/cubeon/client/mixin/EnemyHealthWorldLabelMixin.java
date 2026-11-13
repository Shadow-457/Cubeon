package com.cubeon.client.mixin;

import com.cubeon.client.hud.EnemyHealthWorldLabels;
import net.minecraft.client.render.command.OrderedRenderCommandQueue;
import net.minecraft.client.render.entity.LivingEntityRenderer;
import net.minecraft.client.render.entity.state.LivingEntityRenderState;
import net.minecraft.client.render.state.CameraRenderState;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.entity.LivingEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Adds Cubeon's health label to the exact world render state used by 1.21.11. */
@Mixin(LivingEntityRenderer.class)
public abstract class EnemyHealthWorldLabelMixin {
    @Inject(method = "updateRenderState(Lnet/minecraft/entity/LivingEntity;Lnet/minecraft/client/render/entity/state/LivingEntityRenderState;F)V",
            at = @At("TAIL"))
    private void cubeon$captureHealth(LivingEntity entity, LivingEntityRenderState state,
                                      float tickProgress, CallbackInfo ci) {
        EnemyHealthWorldLabels.capture(entity, state);
    }

    @Inject(method = "render(Lnet/minecraft/client/render/entity/state/LivingEntityRenderState;Lnet/minecraft/client/util/math/MatrixStack;Lnet/minecraft/client/render/command/OrderedRenderCommandQueue;Lnet/minecraft/client/render/state/CameraRenderState;)V",
            at = @At("TAIL"))
    private void cubeon$renderHealth(LivingEntityRenderState state, MatrixStack matrices,
                                     OrderedRenderCommandQueue queue, CameraRenderState camera,
                                     CallbackInfo ci) {
        EnemyHealthWorldLabels.render(state, matrices, queue, camera);
    }
}
