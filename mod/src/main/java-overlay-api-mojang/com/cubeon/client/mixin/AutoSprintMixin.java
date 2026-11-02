package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudConfig;
import com.cubeon.client.hud.HudReadings;
import net.minecraft.client.Minecraft;
import net.minecraft.client.KeyMapping;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Treat sprint as held while moving forward; vanilla retains eligibility/cancel rules. */
@Mixin(KeyMapping.class)
public abstract class AutoSprintMixin {
    @Inject(method = "isDown", at = @At("RETURN"), cancellable = true, require = 0)
    private void cubeon$sprint(CallbackInfoReturnable<Boolean> ci) {
        if (!CubeonHudConfig.get().autoSprint) return;
        var client = Minecraft.getInstance();
        if ((Object)this != client.options.keySprint || client.player == null || HudReadings.screenOpen()) return;
        if (client.options.keyUp.isDown() && !client.options.keyShift.isDown()) ci.setReturnValue(true);
    }
}
