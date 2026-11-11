package com.cubeon.client.hud.mixin;

import com.mojang.blaze3d.vertex.PoseStack;
import net.minecraft.client.renderer.GameRenderer;
import net.minecraft.client.renderer.state.GameRenderState;
import net.minecraft.client.renderer.state.level.CameraRenderState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;
import org.spongepowered.asm.mixin.gen.Invoker;

/** Reuse native view effects instead of approximating their tick-dependent transforms. */
@Mixin(GameRenderer.class)
public interface EnemyHealthGameRendererAccessor {
    @Accessor("gameRenderState")
    GameRenderState cubeon$healthRenderState();

    @Invoker("bobHurt")
    void cubeon$healthHurt(CameraRenderState camera, PoseStack matrices);

    @Invoker("bobView")
    void cubeon$healthBob(CameraRenderState camera, PoseStack matrices);
}
