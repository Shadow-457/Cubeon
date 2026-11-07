package com.cubeon.client.mixin;

import com.cubeon.client.hud.HealthCamera;
import com.cubeon.client.hud.WorldHealthProjection;
import com.llamalad7.mixinextras.sugar.Local;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.Camera;
import net.minecraft.client.render.RenderTickCounter;
import net.minecraft.client.render.WorldRenderer;
import org.joml.Matrix4f;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.ModifyVariable;

/** Capture the projection used by the world, including current FOV and view effects. */
@Mixin(WorldRenderer.class)
public abstract class EnemyHealthProjectionMixin {
    @ModifyVariable(method="render",at=@At("HEAD"),argsOnly=true,ordinal=1,require=1)
    private Matrix4f cubeon$healthProjection(Matrix4f projection,
            @Local(argsOnly=true,ordinal=0) Matrix4f view,
            @Local(argsOnly=true) Camera camera,
            @Local(argsOnly=true) RenderTickCounter counter) {
        WorldHealthProjection.capture(view,projection,HealthCamera.position(camera),
                MinecraftClient.getInstance().world,counter.getTickProgress(false));
        return projection;
    }
}
