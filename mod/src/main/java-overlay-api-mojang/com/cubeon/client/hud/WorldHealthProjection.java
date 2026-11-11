package com.cubeon.client.hud;

import com.cubeon.client.hud.mixin.EnemyHealthGameRendererAccessor;
import com.mojang.blaze3d.vertex.PoseStack;
import net.minecraft.client.Minecraft;
import net.minecraft.world.phys.Vec3;
import org.joml.Matrix4f;
import org.joml.Quaternionf;
import org.joml.Quaternionfc;
import org.joml.Vector4f;

/** Project from this GUI extraction's camera state, including native walking and hurt motion. */
public final class WorldHealthProjection {
    private WorldHealthProjection() {}

    public static Frame current(Minecraft client) {
        if (client.level == null || client.player == null
                || !(client.gameRenderer instanceof EnemyHealthGameRendererAccessor renderer)) return null;
        var game = renderer.cubeon$healthRenderState();
        var camera = game.levelRenderState.cameraRenderState;
        if (!camera.initialized || camera.pos == null) return null;

        // 26.x extracts the GUI before drawing the world. Capturing renderLevel's
        // matrices would pair the previous frame's camera with current entity positions.
        var effects = new PoseStack();
        renderer.cubeon$healthHurt(camera, effects);
        if (game.optionsRenderState.bobView) renderer.cubeon$healthBob(camera, effects);
        var matrix = new Matrix4f(camera.projectionMatrix)
                .mul(effects.last().pose()).mul(camera.viewRotationMatrix);
        return new Frame(matrix, camera.pos, new Quaternionf(camera.orientation));
    }

    /** A snapshot keeps every name/bar projection on the same extracted camera. */
    public static final class Frame {
        private final Matrix4f matrix;
        private final Vec3 camera;
        private final Quaternionf rotation;

        private Frame(Matrix4f matrix, Vec3 camera, Quaternionf rotation) {
            this.matrix = matrix;
            this.camera = camera;
            this.rotation = rotation;
        }

        public Vec3 camera() { return camera; }
        public Quaternionfc rotation() { return rotation; }

        public Vec3 project(Vec3 point) {
            var clip = matrix.transform(new Vector4f((float) (point.x - camera.x),
                    (float) (point.y - camera.y), (float) (point.z - camera.z), 1));
            if (!Float.isFinite(clip.w) || clip.w <= 0) return null;
            return new Vec3(clip.x / clip.w, clip.y / clip.w, clip.z / clip.w);
        }
    }
}
