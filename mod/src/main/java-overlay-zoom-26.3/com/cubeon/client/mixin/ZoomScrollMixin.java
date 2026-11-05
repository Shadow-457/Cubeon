package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudKeybinds;
import com.cubeon.client.hud.Zoom;
import net.minecraft.client.MouseHandler;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(MouseHandler.class)
public abstract class ZoomScrollMixin {
    @Inject(method = "onScroll", at = @At("HEAD"), cancellable = true)
    private void cubeon$zoomScroll(long window, double horizontal, double vertical, CallbackInfo ci) {
        if (!CubeonHudKeybinds.zoomActive() || !Double.isFinite(vertical) || vertical == 0) return;
        Zoom.onScroll(vertical);
        ci.cancel();
    }
}
