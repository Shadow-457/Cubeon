package com.cubeon.client.hud.blur;

import com.cubeon.client.hud.CameraBlur;
import com.cubeon.client.hud.TemporalBlur;
import com.cubeon.client.hud.blur.mixin.CameraBlurPasses;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.GameRenderer;
import net.minecraft.client.gl.PostEffectProcessor;
import net.minecraft.util.Identifier;

/** Uses vanilla post-processing, with a reusable current-scene intermediate. */
public final class CameraBlurRenderer {
    private static PostEffectProcessor effect;
    private static boolean effectPlus;
    private static Object resources;
    private static int width, height;
    private static final org.slf4j.Logger LOG = org.slf4j.LoggerFactory.getLogger("CubeonCameraBlur");
    private static Object scene;
    private static boolean failed;
    private static volatile boolean resetRequested;
    public static double fov = 70;

    public static void beginFrame() {
        var client = MinecraftClient.getInstance();
        if (resetRequested || !(CubeonHudConfig.get().cameraMotionBlur || CubeonHudConfig.get().temporalMotionBlur) || client.world == null || client.currentScreen != null
                || client.world != scene) {
            shutdown(); scene = client.world;
        }
    }
    /** May be requested from the settings/reload thread; GPU cleanup stays on render. */
    public static void reset() { resetRequested = true; }
    public static void shutdown() {
        resetRequested = false;
        CameraBlur.INSTANCE.reset();
        TemporalBlur.INSTANCE.reset();
        release(); failed = false; scene = null;
    }

    public static void render(GameRenderer renderer) {
        var client = MinecraftClient.getInstance();
        if (failed || !(CubeonHudConfig.get().cameraMotionBlur || CubeonHudConfig.get().temporalMotionBlur) || client.world == null || client.currentScreen != null) return;
        boolean plus = CubeonHudConfig.get().temporalMotionBlur;
        var main = client.getFramebuffer();
        if (main.textureWidth <= 0 || main.textureHeight <= 0) return;
        var camera = renderer.getCamera();
        CameraBlur blur = CameraBlur.INSTANCE;
        long now = System.nanoTime();
        blur.update(now, camera.getYaw(), camera.getPitch(), fov,
                (double)main.textureWidth / main.textureHeight, client.world, true, CubeonHudConfig.get().cameraBlurIntensity);
        if (plus) TemporalBlur.INSTANCE.update(now, camera.getYaw(), camera.getPitch(), fov,
                (double)main.textureWidth / main.textureHeight, client.world, true, CubeonHudConfig.get().temporalBlurStrength);
        if (!plus && !blur.moving()) return;
        try {
            if (effectPlus != plus || resources != client.getResourceManager() || width != main.textureWidth || height != main.textureHeight) release();
            if (effect == null) {
                effect = new PostEffectProcessor(client.getTextureManager(), client.getResourceManager(), main,
                        Identifier.tryParse(plus ? "cubeon-client:shaders/post/motion_plus.json" : "cubeon-client:shaders/post/camera_blur.json"));
                effect.setupDimensions(main.textureWidth, main.textureHeight);
                effectPlus = plus;
                resources = client.getResourceManager(); width = main.textureWidth; height = main.textureHeight;
            }
            var passes = ((CameraBlurPasses)(Object)effect).cubeon$passes();
            var vector = passes.get(0).getProgram().getUniformByName("BlurVector");
            if (vector == null) throw new IllegalStateException("Camera blur uniform is unavailable");
            vector.set(plus ? TemporalBlur.INSTANCE.weight() : blur.x(), plus ? 0 : blur.y());
            effect.render(0);
        } catch (Exception | LinkageError error) {
            release(); failed = true; blur.reset();
            LOG.warn("Camera blur disabled for this session; renderer could not apply the optional effect", error);
        } finally {
            main.beginWrite(true);
        }
    }
    private static void release() {
        TemporalBlur.INSTANCE.reset();
        if (effect != null) { try { effect.close(); } catch (Exception | LinkageError ignored) {} }
        effect = null; resources = null; width = height = 0;
    }
}
