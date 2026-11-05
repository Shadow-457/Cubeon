package com.cubeon.client.mixin;

import com.cubeon.client.hud.CubeonHudKeybinds;
import com.cubeon.client.hud.Zoom;
import com.cubeon.client.hud.blur.CameraBlurRenderer;
import net.minecraft.client.Camera;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Apply zoom before Camera.update stores FOV and builds the world projection. */
@Mixin(Camera.class)
public abstract class ZoomMixin {
    @Inject(method = "calculateFov", at = @At("RETURN"), cancellable = true)
    private void cubeon$zoomFov(float partialTick, CallbackInfoReturnable<Float> cir) {
        float factor = Zoom.fovFactor(CubeonHudKeybinds.zoomActive());
        if (factor != 1) cir.setReturnValue(cir.getReturnValueF() * factor);
        CameraBlurRenderer.fov = cir.getReturnValueF();
    }
}
