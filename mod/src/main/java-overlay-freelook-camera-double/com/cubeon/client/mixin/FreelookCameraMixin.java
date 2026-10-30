package com.cubeon.client.mixin;

import com.cubeon.client.hud.Freelook;
import com.cubeon.client.hud.FreelookController;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.Perspective;
import net.minecraft.client.render.Camera;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.ModifyArgs;
import org.spongepowered.asm.mixin.injection.ModifyVariable;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.invoke.arg.Args;

@Mixin(Camera.class)
public abstract class FreelookCameraMixin {
    @Unique private boolean cubeon$managedView;

    @Unique private boolean cubeon$syncView() {
        boolean wasActive = Freelook.INSTANCE.active();
        boolean active = FreelookController.sync();
        cubeon$managedView |= wasActive || active;
        return cubeon$managedView;
    }

    @Inject(method = "update", at = @At("RETURN"))
    private void cubeon$finishedView(CallbackInfo ci) { cubeon$managedView = false; }

    @ModifyVariable(method = "update", at = @At("HEAD"), argsOnly = true, ordinal = 0)
    private boolean cubeon$thirdPerson(boolean original) {
        return cubeon$syncView() ? MinecraftClient.getInstance().options.getPerspective() != Perspective.FIRST_PERSON : original;
    }
    @ModifyVariable(method = "update", at = @At("HEAD"), argsOnly = true, ordinal = 1)
    private boolean cubeon$frontView(boolean original) {
        return cubeon$syncView() ? MinecraftClient.getInstance().options.getPerspective() == Perspective.THIRD_PERSON_FRONT : original;
    }

    @ModifyArgs(method = "update", at = @At(value = "INVOKE",
            target = "Lnet/minecraft/client/render/Camera;setRotation(FF)V"))
    private void cubeon$freelookRotation(Args args) {
        if (FreelookController.sync()) {
            args.set(0, Freelook.INSTANCE.yaw());
            args.set(1, Freelook.INSTANCE.pitch());
        }
    }
    /** Feed vanilla's collision test the chosen distance; never bypass walls. */
    @ModifyVariable(method = "clipToSpace", at = @At("HEAD"), argsOnly = true)
    private double cubeon$freelookDistance(double original) {
        return FreelookController.sync() ? original * Freelook.INSTANCE.distance() / 4 : original;
    }
}
