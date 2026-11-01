package com.cubeon.client.hud.blur.mixin;

import com.cubeon.client.hud.blur.CameraBlurRenderer;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(Minecraft.class)
public abstract class CameraBlurReloadMixin {
    @Inject(method = "reloadResourcePacks", at = @At("HEAD"))
    private void cubeon$reload(CallbackInfoReturnable<?> ci) { CameraBlurRenderer.reset(); }
}
