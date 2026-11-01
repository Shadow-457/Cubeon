package com.cubeon.client.hud.blur.mixin;

import com.cubeon.client.hud.blur.CameraBlurRenderer;
import net.minecraft.client.MinecraftClient;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(MinecraftClient.class)
public abstract class CameraBlurReloadMixin {
    @Inject(method = "reloadResources", at = @At("HEAD"))
    private void cubeon$reload(CallbackInfoReturnable<?> ci) { CameraBlurRenderer.reset(); }
}
