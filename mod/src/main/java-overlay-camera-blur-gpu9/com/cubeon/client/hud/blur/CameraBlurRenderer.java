package com.cubeon.client.hud.blur;

import com.cubeon.client.hud.CameraBlur;
import com.cubeon.client.hud.TemporalBlur;
import com.cubeon.client.hud.CubeonHudConfig;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.textures.GpuTexture;
import com.mojang.blaze3d.systems.RenderSystem;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.render.GameRenderer;
import net.minecraft.util.Identifier;
import com.mojang.blaze3d.textures.FilterMode;
import com.mojang.blaze3d.textures.AddressMode;
import com.mojang.blaze3d.textures.GpuTextureView;
import com.mojang.blaze3d.buffers.GpuBuffer;
import net.minecraft.client.gl.UniformType;
import com.mojang.blaze3d.textures.TextureFormat;
import com.mojang.blaze3d.platform.DepthTestFunction;
import com.mojang.blaze3d.vertex.VertexFormat;

/** Native GPU pass: copy this scene once, then spatially sample it. Motion blur+ adds time-based scene history. */
public final class CameraBlurRenderer {
    private static RenderPipeline pipeline;
    private static GpuTexture scratch;
    private static GpuTexture history;
    private static boolean historyReady;
    private static Object resources;
    private static int width, height;
    private static GpuTextureView scratchView;
    private static GpuTextureView historyView;
    private static GpuBuffer uniform;
    private static final java.nio.ByteBuffer DATA = java.nio.ByteBuffer.allocateDirect(16).order(java.nio.ByteOrder.nativeOrder());
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
            var device = RenderSystem.getDevice();
            var color = main.getColorAttachment();
            if (color == null) return;
            if (resources != client.getResourceManager() || width != main.textureWidth || height != main.textureHeight) release();
            if (pipeline == null) createPipeline();
            if (scratch == null) {
                scratch = device.createTexture("Cubeon camera blur current scene", GpuTexture.USAGE_COPY_SRC | GpuTexture.USAGE_COPY_DST | GpuTexture.USAGE_TEXTURE_BINDING, color.getFormat(), main.textureWidth, main.textureHeight, 1, 1);

                scratchView = device.createTextureView(scratch);
                uniform = device.createBuffer(() -> "Cubeon camera blur exposure", GpuBuffer.USAGE_UNIFORM | GpuBuffer.USAGE_COPY_DST, 16);
                resources = client.getResourceManager(); width = main.textureWidth; height = main.textureHeight;
            }
            if (plus && history == null) {
                history = device.createTexture("Cubeon camera blur history", GpuTexture.USAGE_COPY_DST | GpuTexture.USAGE_TEXTURE_BINDING, color.getFormat(), main.textureWidth, main.textureHeight, 1, 1);
                historyView = device.createTextureView(history);
                historyReady = false;
            }
            float vectorX = plus ? 1 + (historyReady ? TemporalBlur.INSTANCE.weight() : 0) : blur.x();
            float vectorY = plus ? 0 : blur.y();
            var encoder = device.createCommandEncoder();
            encoder.copyTextureToTexture(color, scratch, 0, 0, 0, 0, 0, width, height);
            DATA.clear(); DATA.putFloat(vectorX).putFloat(vectorY).putFloat(0).putFloat(0).flip();
            encoder.writeToBuffer(uniform.slice(), DATA);
            try (var pass = encoder.createRenderPass(() -> "Cubeon camera blur", main.getColorAttachmentView(), java.util.OptionalInt.empty())) {
                pass.setPipeline(pipeline);
                pass.bindTexture("InSampler", scratchView, RenderSystem.getSamplerCache().get(FilterMode.LINEAR));
                pass.bindTexture("HistorySampler", (plus ? historyView : scratchView), RenderSystem.getSamplerCache().get(FilterMode.LINEAR));
                pass.setUniform("CameraBlur", uniform);
                pass.draw(0, 3);
            }
            if (plus) {
                encoder.copyTextureToTexture(scratch, history, 0, 0, 0, 0, 0, width, height);
                historyReady = true;
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
                .withSampler("HistorySampler")
                .withUniform("CameraBlur", UniformType.UNIFORM_BUFFER)
                .withDepthTestFunction(DepthTestFunction.NO_DEPTH_TEST)
                .withDepthWrite(false).withoutBlend()
                .withVertexFormat(VertexFormat.builder().build(), VertexFormat.DrawMode.TRIANGLES).build();

    }
    private static void release() {
        historyReady = false; TemporalBlur.INSTANCE.reset();
        if (uniform != null) { try { uniform.close(); } catch (Exception | LinkageError ignored) {} uniform = null; }
        if (scratchView != null) { try { scratchView.close(); } catch (Exception | LinkageError ignored) {} scratchView = null; }
        if (scratch != null) { try { scratch.close(); } catch (Exception | LinkageError ignored) {} scratch = null; }
        if (historyView != null) { try { historyView.close(); } catch (Exception | LinkageError ignored) {} historyView = null; }
        if (history != null) { try { history.close(); } catch (Exception | LinkageError ignored) {} history = null; }
        // Keep the immutable descriptor: native caches key pipelines by identity.
        resources = null; width = height = 0;
    }
}
