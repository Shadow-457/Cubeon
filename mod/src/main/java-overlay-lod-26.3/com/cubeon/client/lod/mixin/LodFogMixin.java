package com.cubeon.client.lod.mixin;

import com.cubeon.client.lod.LodClient;
import com.cubeon.client.lod.LodRenderer;
import net.minecraft.client.Camera;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.renderer.fog.FogData;
import net.minecraft.client.renderer.fog.FogRenderer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Share distance fog across the seam; vanilla still owns weather and environmental fog. */
@Mixin(FogRenderer.class)
public abstract class LodFogMixin {
    @Inject(method = "setupFog", at = @At("RETURN"))
    private void cubeon$lodFog(Camera camera, int near, DeltaTracker delta, float darkness,
                               ClientLevel level, CallbackInfoReturnable<FogData> result) {
        if (!LodClient.enabled() || LodRenderer.paused()) return;
        var frame = LodClient.frame();
        if (frame == null || frame.meshes().isEmpty()) return;
        int distance = LodClient.options().active().distance();
        if (distance <= near) return;
        var fog = result.getReturnValue();
        fog.renderDistanceEnd = distance * 16f;
        fog.renderDistanceStart = fog.renderDistanceEnd * .6f;
    }
}
