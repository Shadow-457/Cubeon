package com.cubeon.client.mixin;

import com.cubeon.client.hud.FreelookController;
import net.minecraft.client.MouseHandler;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(MouseHandler.class)
public abstract class FreelookScrollMixin {
    @Inject(method = "onScroll", at = @At("HEAD"), cancellable = true)
    private void cubeon$freelookScroll(long window, double horizontal, double vertical, CallbackInfo ci) {
        if (FreelookController.scroll(vertical)) ci.cancel();
    }
}
