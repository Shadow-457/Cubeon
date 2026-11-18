package com.cubeon.client.hud.blur;

import com.cubeon.client.hud.CameraBlur;
import com.cubeon.client.hud.blur.mixin.CameraBlurPasses;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.GameRenderer;
import net.minecraft.client.gl.PostEffectProcessor;
import net.minecraft.util.Identifier;
import net.minecraft.client.util.Pool;
import java.util.Set;

/** Uses vanilla post-processing, with a reusable current-scene intermediate. */
public final class CameraBlurRenderer {
    private static PostEffectProcessor effect;
    private static Object resources;
    private static int width, height;
    private static Pool pool;
    private static final org.slf4j.Logger LOG = org.slf4j.LoggerFactory.getLogger("CubeonCameraBlur");
    private static Object scene;
    private static boolean failed;
    private static volatile boolean resetRequested;
    public static double fov = 70;

    public static void beginFrame() {
        var client = MinecraftClient.getInstance();
        if (resetRequested || !CubeonHudConfig.get().cameraMotionBlur || client.world == null || client.currentScreen != null
                || client.world != scene) {
            shutdown(); scene = client.world;
        }
    }
    /** May be requested from the settings/reload thread; GPU cleanup stays on render. */
    public static void reset() { resetRequested = true; }
    public static void shutdown() {
        resetRequested = false;
        CameraBlur.INSTANCE.reset();
        release(); failed = false; scene = null;
    }

    public static void render(GameRenderer renderer) {
        var client = MinecraftClient.getInstance();
        if (failed || !CubeonHudConfig.get().cameraMotionBlur || client.world == null || client.currentScreen != null) return;
        var main = client.getFramebuffer();
        if (main.textureWidth <= 0 || main.textureHeight <= 0) return;
        var camera = renderer.getCamera();
        CameraBlur blur = CameraBlur.INSTANCE;
        blur.update(System.nanoTime(), camera.getYaw(), camera.getPitch(), fov,
                (double)main.textureWidth / main.textureHeight, client.world, true, CubeonHudConfig.get().cameraBlurIntensity);
        if (!blur.moving()) return;
        try {
            if (resources != client.getResourceManager() || width != main.textureWidth || height != main.textureHeight) release();
            if (effect == null) {
                effect = client.getShaderLoader().loadPostEffect(Identifier.tryParse("cubeon-client:camera_blur"), Set.of(PostEffectProcessor.MAIN));
                if (effect == null) throw new IllegalStateException("Camera blur shader is unavailable");
                pool = new Pool(1);
                resources = client.getResourceManager(); width = main.textureWidth; height = main.textureHeight;
            }
            var passes = ((CameraBlurPasses)(Object)effect).cubeon$passes();
            var vector = passes.get(0).getProgram().getUniform("BlurVector");
            if (vector == null) throw new IllegalStateException("Camera blur uniform is unavailable");
            vector.set(blur.x(), blur.y());
            effect.render(main, pool);
            pool.decrementLifespan();
        } catch (Exception | LinkageError error) {
            release(); failed = true; blur.reset();
            LOG.warn("Camera blur disabled for this session; renderer could not apply the optional effect", error);
        } finally {
            main.beginWrite(true);
        }
    }
    private static void release() {
        if (pool != null) { try { pool.close(); } catch (Exception | LinkageError ignored) {} pool = null; }
        effect = null; resources = null; width = height = 0;
    }
}
