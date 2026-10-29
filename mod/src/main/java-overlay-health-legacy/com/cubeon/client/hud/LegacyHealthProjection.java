package com.cubeon.client.hud;

import net.fabricmc.fabric.api.client.rendering.v1.WorldRenderEvents;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.world.ClientWorld;
import net.minecraft.util.math.Vec3d;
import org.joml.Matrix4f;
import org.joml.Quaternionf;
import org.joml.Vector4f;
import java.lang.ref.WeakReference;

/** World projection for versions predating GameRenderer.project. */
public final class LegacyHealthProjection {
    private static final Matrix4f matrix = new Matrix4f();
    private static Vec3d camera;
    private static WeakReference<ClientWorld> world = new WeakReference<>(null);
    private static float tickDelta;
    private static boolean ready;
    private LegacyHealthProjection() {}

    public static void register() {
        WorldRenderEvents.AFTER_ENTITIES.register(context -> {
            ready = false;
            if (!CubeonHudConfig.get().showEnemyHealth) return;
            matrix.set(context.projectionMatrix()).rotate(new Quaternionf(context.camera().getRotation()).conjugate());
            camera = context.camera().getPos();
            if (world.get() != context.world()) world = new WeakReference<>(context.world());
            tickDelta = context.tickDelta();
            ready = true;
        });
    }

    public static void render(DrawContext context, MinecraftClient client) {
        if (!ready || world.get() != client.world) return;
        ready = false; // Never reuse a previous world's/frame's projection.
        EnemyHealthRenderer.render(context, client, LegacyHealthProjection::project, tickDelta);
    }

    private static Vec3d project(Vec3d point) {
        Vec3d relative = point.subtract(camera);
        Vector4f clip = matrix.transform(new Vector4f((float) relative.x, (float) relative.y, (float) relative.z, 1));
        if (!Float.isFinite(clip.w) || clip.w <= 0) return null;
        return new Vec3d(clip.x / clip.w, clip.y / clip.w, clip.z / clip.w);
    }
}
