package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.HudReadings;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Treat sprint as held while moving forward; vanilla retains eligibility/cancel rules. */
@Mixin(KeyBinding.class)
public abstract class AutoSprintMixin {
    @Inject(method = "isPressed", at = @At("RETURN"), cancellable = true, require = 0)
    private void cubeon$sprint(CallbackInfoReturnable<Boolean> ci) {
        if (!CubeonHudConfig.get().autoSprint) return;
        var client = MinecraftClient.getInstance();
        if ((Object)this != client.options.sprintKey || client.player == null || HudReadings.screenOpen()) return;
        if (client.options.forwardKey.isPressed() && !client.options.sneakKey.isPressed()) ci.setReturnValue(true);
    }
}
