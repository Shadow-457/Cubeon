package com.cubeon.client.mixin;

import com.cubeon.client.hud.Freelook;
import com.cubeon.client.hud.FreelookController;
import net.minecraft.client.Camera;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.ModifyArgs;
import org.spongepowered.asm.mixin.injection.ModifyVariable;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.invoke.arg.Args;

@Mixin(Camera.class)
public abstract class FreelookCameraMixin {
    @Inject(method = "update", at = @At("HEAD"))
    private void cubeon$freelookUpdate(CallbackInfo ci) { FreelookController.sync(); }

    @ModifyArgs(method = "alignWithEntity", at = @At(value = "INVOKE",
            target = "Lnet/minecraft/client/Camera;setRotation(FF)V"))
    private void cubeon$freelookRotation(Args args) {
        if (FreelookController.sync()) {
            args.set(0, Freelook.INSTANCE.yaw());
            args.set(1, Freelook.INSTANCE.pitch());
        }
    }
    @ModifyVariable(method = "getMaxZoom", at = @At("HEAD"), argsOnly = true)
    private float cubeon$freelookDistance(float original) {
        return FreelookController.sync() ? (float) (original * Freelook.INSTANCE.distance() / 4) : original;
    }
}
