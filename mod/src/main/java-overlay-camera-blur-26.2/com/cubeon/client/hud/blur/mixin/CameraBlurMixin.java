package com.cubeon.client.hud.blur.mixin;

import com.cubeon.client.hud.blur.CameraBlurRenderer;
import net.minecraft.client.renderer.GameRenderer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Optional world-only pass; the GUI is drawn after this hook. */
@Mixin(value = GameRenderer.class, priority = 900)
public abstract class CameraBlurMixin {
    @Inject(method = "render", at = @At("HEAD"))
    private void cubeon$frame(CallbackInfo ci) { CameraBlurRenderer.beginFrame(); }
    @Inject(method = "renderLevel", at = @At("TAIL"))
    private void cubeon$blur(CallbackInfo ci) { CameraBlurRenderer.render((GameRenderer)(Object)this); }
    @Inject(method = "close", at = @At("HEAD"))
    private void cubeon$close(CallbackInfo ci) { CameraBlurRenderer.shutdown(); }
}
