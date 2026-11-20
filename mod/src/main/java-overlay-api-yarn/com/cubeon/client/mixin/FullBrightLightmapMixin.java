package com.cubeon.client.mixin;

import com.cubeon.client.hud.FullBright;
import net.minecraft.client.render.LightmapTextureManager;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Limits the gamma override to the lightmap update, never options persistence. */
@Mixin(value = LightmapTextureManager.class, priority = 2000)
public abstract class FullBrightLightmapMixin {
    @Shadow private boolean dirty;
    @Unique private boolean cubeon$fullBright;

    @Inject(method = "update(F)V", at = @At("HEAD"), require = 1)
    private void cubeon$begin(float tickDelta, CallbackInfo ci) {
        // 1.21.11's lightmap is aggressively cached (and BadOptimizations can
        // extend that cache). A menu toggle otherwise reaches update(), hits
        // the vanilla `if (!dirty) return`, and appears to do nothing until an
        // unrelated world-light change. Detect the setting edge before that
        // guard and force exactly one rebuild for both enable and disable.
        boolean enabled = com.cubeon.client.hud.CubeonHudConfig.get().fullBright;
        if (cubeon$fullBright != enabled) {
            cubeon$fullBright = enabled;
            dirty = true;
        }
        FullBright.beginLightmap();
    }

    @Inject(method = "update(F)V", at = @At("RETURN"), require = 1)
    private void cubeon$end(float tickDelta, CallbackInfo ci) { FullBright.endLightmap(); }
}
