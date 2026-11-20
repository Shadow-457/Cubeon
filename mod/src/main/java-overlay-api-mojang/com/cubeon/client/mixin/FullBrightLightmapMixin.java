package com.cubeon.client.mixin;

import com.cubeon.client.hud.FullBright;
import net.minecraft.client.renderer.LightmapRenderStateExtractor;
import net.minecraft.client.renderer.state.LightmapRenderState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Limits the gamma override to the lightmap extraction, never options persistence. */
@Mixin(LightmapRenderStateExtractor.class)
public abstract class FullBrightLightmapMixin {
    @Shadow private boolean needsUpdate;
    @Unique private boolean cubeon$fullBright;

    @Inject(method = "extract(Lnet/minecraft/client/renderer/state/LightmapRenderState;F)V",
            at = @At("HEAD"), require = 1)
    private void cubeon$begin(LightmapRenderState state, float tickDelta, CallbackInfo ci) {
        boolean enabled = com.cubeon.client.hud.CubeonHudConfig.get().fullBright;
        if (cubeon$fullBright != enabled) {
            cubeon$fullBright = enabled;
            needsUpdate = true;
        }
        FullBright.beginLightmap();
    }

    @Inject(method = "extract(Lnet/minecraft/client/renderer/state/LightmapRenderState;F)V",
            at = @At("RETURN"), require = 1)
    private void cubeon$end(LightmapRenderState state, float tickDelta, CallbackInfo ci) {
        if (state.needsUpdate && FullBright.isActive()) {
            // 26.x can have exactly zero ambient light. Gamma multiplies that
            // black value (and its shader divides by zero), so use neutral,
            // fully lit render data instead of relying on a gamma multiplier.
            state.ambientColor = LightmapRenderStateExtractor.WHITE;
            state.brightness = 0.0F;
            state.darknessEffectScale = 0.0F;
            state.bossOverlayWorldDarkening = 0.0F;
        }
        FullBright.endLightmap();
    }
}
