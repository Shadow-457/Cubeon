package com.cubeon.client.hud.blur;

import com.cubeon.client.hud.CameraBlur;
import com.cubeon.client.hud.CubeonHudConfig;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.textures.GpuTexture;
import com.mojang.blaze3d.systems.RenderSystem;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.GameRenderer;
import net.minecraft.resources.Identifier;
import com.mojang.blaze3d.textures.FilterMode;
import com.mojang.blaze3d.textures.AddressMode;
import com.mojang.blaze3d.textures.GpuTextureView;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.shaders.UniformType;
import com.mojang.blaze3d.textures.TextureFormat;
import com.mojang.blaze3d.pipeline.ColorTargetState;
import com.mojang.blaze3d.vertex.VertexFormat;

/** Native GPU pass: copy this scene once, then spatially sample it. No frame history. */
public final class CameraBlurRenderer {
    private static RenderPipeline pipeline;
    private static GpuTexture scratch;
    private static Object resources;
    private static int width, height;
    private static GpuTextureView scratchView;
    private static GpuBuffer uniform;
    private static final java.nio.ByteBuffer DATA = java.nio.ByteBuffer.allocateDirect(16).order(java.nio.ByteOrder.nativeOrder());
    private static final org.slf4j.Logger LOG = org.slf4j.LoggerFactory.getLogger("CubeonCameraBlur");
    private static Object scene;
    private static boolean failed;
    private static volatile boolean resetRequested;
    public static double fov = 70;

    public static void beginFrame() {
        var client = Minecraft.getInstance();
        if (resetRequested || !CubeonHudConfig.get().cameraMotionBlur || client.level == null || client.screen != null
                || client.level != scene) {
            shutdown(); scene = client.level;
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
        var client = Minecraft.getInstance();
        if (failed || !CubeonHudConfig.get().cameraMotionBlur || client.level == null || client.screen != null) return;
        var main = client.getMainRenderTarget();
        if (main.width <= 0 || main.height <= 0) return;
        var camera = renderer.getMainCamera();
        CameraBlur blur = CameraBlur.INSTANCE;
        blur.update(System.nanoTime(), camera.yRot(), camera.xRot(), camera.getFov(),
                (double)main.width / main.height, client.level, true, CubeonHudConfig.get().cameraBlurIntensity);
        if (!blur.moving()) return;
        try {
            var device = RenderSystem.getDevice();
            var color = main.getColorTexture();
            if (color == null) return;
            if (resources != client.getResourceManager() || width != main.width || height != main.height) release();
            if (pipeline == null) createPipeline();
            if (scratch == null) {
                scratch = device.createTexture("Cubeon camera blur current scene", GpuTexture.USAGE_COPY_DST | GpuTexture.USAGE_TEXTURE_BINDING, color.getFormat(), main.width, main.height, 1, 1);

                scratchView = device.createTextureView(scratch);
                uniform = device.createBuffer(() -> "Cubeon camera blur exposure", GpuBuffer.USAGE_UNIFORM | GpuBuffer.USAGE_COPY_DST, 16);
                resources = client.getResourceManager(); width = main.width; height = main.height;
            }
            var encoder = device.createCommandEncoder();
            encoder.copyTextureToTexture(color, scratch, 0, 0, 0, 0, 0, width, height);
            DATA.clear(); DATA.putFloat(blur.x()).putFloat(blur.y()).putFloat(0).putFloat(0).flip();
            encoder.writeToBuffer(uniform.slice(), DATA);
            try (var pass = encoder.createRenderPass(() -> "Cubeon camera blur", main.getColorTextureView(), java.util.OptionalInt.empty())) {
                pass.setPipeline(pipeline);
                pass.bindTexture("InSampler", scratchView, RenderSystem.getSamplerCache().getClampToEdge(FilterMode.LINEAR));
                pass.setUniform("CameraBlur", uniform);
                pass.draw(0, 3);
            }

        } catch (Exception | LinkageError error) {
            release(); failed = true; blur.reset();
            LOG.warn("Camera blur disabled for this session; renderer could not apply the optional effect", error);
        }
    }
    private static void createPipeline() {
        pipeline = RenderPipeline.builder()
                .withLocation(Identifier.parse("cubeon-client:pipeline/camera_blur"))
                .withVertexShader(Identifier.parse("cubeon-client:core/camera_blur"))
                .withFragmentShader(Identifier.parse("cubeon-client:core/camera_blur"))
                .withCull(false)
                .withSampler("InSampler")
                .withUniform("CameraBlur", UniformType.UNIFORM_BUFFER)
                .withDepthStencilState(java.util.Optional.empty())
                .withColorTargetState(ColorTargetState.DEFAULT)
                .withVertexFormat(VertexFormat.builder().build(), VertexFormat.Mode.TRIANGLES).build();

    }
    private static void release() {
        if (uniform != null) { try { uniform.close(); } catch (Exception | LinkageError ignored) {} uniform = null; }
        if (scratchView != null) { try { scratchView.close(); } catch (Exception | LinkageError ignored) {} scratchView = null; }
        if (scratch != null) { try { scratch.close(); } catch (Exception | LinkageError ignored) {} scratch = null; }
        // Keep the immutable descriptor: native caches key pipelines by identity.
        resources = null; width = height = 0;
    }
}
