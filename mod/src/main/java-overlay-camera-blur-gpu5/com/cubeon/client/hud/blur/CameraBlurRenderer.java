package com.cubeon.client.hud.blur;

import com.cubeon.client.hud.CameraBlur;
import com.cubeon.client.hud.CubeonHudConfig;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.textures.GpuTexture;
import com.mojang.blaze3d.systems.RenderSystem;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.GameRenderer;
import net.minecraft.util.Identifier;
import com.mojang.blaze3d.textures.FilterMode;
import com.mojang.blaze3d.textures.AddressMode;
import net.minecraft.client.gl.UniformType;
import com.mojang.blaze3d.textures.TextureFormat;
import com.mojang.blaze3d.platform.DepthTestFunction;
import com.mojang.blaze3d.vertex.VertexFormat;

/** Native GPU pass: copy this scene once, then spatially sample it. No frame history. */
public final class CameraBlurRenderer {
    private static RenderPipeline pipeline;
    private static GpuTexture scratch;
    private static Object resources;
    private static int width, height;
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
            var device = RenderSystem.getDevice();
            var color = main.getColorAttachment();
            if (color == null) return;
            if (resources != client.getResourceManager() || width != main.textureWidth || height != main.textureHeight) release();
            if (pipeline == null) createPipeline();
            if (scratch == null) {
                scratch = device.createTexture("Cubeon camera blur current scene", color.getFormat(), main.textureWidth, main.textureHeight, 1);
                scratch.setTextureFilter(FilterMode.LINEAR, false);
                scratch.setAddressMode(AddressMode.CLAMP_TO_EDGE);

                resources = client.getResourceManager(); width = main.textureWidth; height = main.textureHeight;
            }
            var encoder = device.createCommandEncoder();
            encoder.copyTextureToTexture(color, scratch, 0, 0, 0, 0, 0, width, height);

            try (var pass = encoder.createRenderPass(main.getColorAttachment(), java.util.OptionalInt.empty())) {
                pass.setPipeline(pipeline);
                pass.bindSampler("InSampler", scratch);
                pass.setUniform("BlurVector", blur.x(), blur.y());
                pass.draw(0, 3);
            }

        } catch (Exception | LinkageError error) {
            release(); failed = true; blur.reset();
            LOG.warn("Camera blur disabled for this session; renderer could not apply the optional effect", error);
        }
    }
    private static void createPipeline() {
        pipeline = RenderPipeline.builder()
                .withLocation(Identifier.tryParse("cubeon-client:pipeline/camera_blur"))
                .withVertexShader(Identifier.tryParse("cubeon-client:core/camera_blur"))
                .withFragmentShader(Identifier.tryParse("cubeon-client:core/camera_blur"))
                .withCull(false)
                .withSampler("InSampler")
                .withUniform("BlurVector", UniformType.VEC2)
                .withDepthTestFunction(DepthTestFunction.NO_DEPTH_TEST)
                .withDepthWrite(false).withoutBlend()
                .withVertexFormat(VertexFormat.builder().build(), VertexFormat.DrawMode.TRIANGLES).build();

    }
    private static void release() {

        if (scratch != null) { try { scratch.close(); } catch (Exception | LinkageError ignored) {} scratch = null; }
        // Keep the immutable descriptor: native caches key pipelines by identity.
        resources = null; width = height = 0;
    }
}
