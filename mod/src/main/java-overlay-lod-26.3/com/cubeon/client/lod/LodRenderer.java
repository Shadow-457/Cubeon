package com.cubeon.client.lod;

import com.cubeon.client.lod.core.TilePlan;
import com.mojang.blaze3d.systems.RenderSystem;
import com.mojang.renderpearl.api.GpuFormat;
import com.mojang.renderpearl.api.buffers.GpuBuffer;
import com.mojang.renderpearl.api.commands.*;
import com.mojang.renderpearl.api.device.DeviceType;
import com.mojang.renderpearl.api.pipeline.*;
import com.mojang.renderpearl.api.textures.*;
import com.mojang.renderpearl.api.vertex.VertexFormat;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.GameRenderer;
import net.minecraft.data.AtlasIds;
import net.minecraft.resources.Identifier;
import org.joml.*;
import java.nio.*;
import java.util.*;

/** Far projection and depth-aware composition, before hands/post effects. All GPU ownership stays here. */
public final class LodRenderer {
    private record Resident(PackedMesh source, BufferArena.Slice solid, BufferArena.Slice fluid) { }
    private static final BufferArena ARENA = new BufferArena();
    private static Map<TilePlan.Key, Resident> active = new LinkedHashMap<>(), pending = new LinkedHashMap<>();
    private static TerrainWorker.Frame target;
    private static int uploading, uploadOffset;
    private static boolean uploadComplete;
    private static long generation = -1;
    private static GpuBuffer frameUniform, indirect;
    private static GpuTexture farColor, farDepth;
    private static GpuTextureView colorView, depthView;
    private static int width, height;
    private static final int UPLOAD = 2 << 20, FRAME_BYTES = 256;
    private static final ByteBuffer STAGING = ByteBuffer.allocateDirect(UPLOAD).order(ByteOrder.nativeOrder());
    private static final ByteBuffer UNIFORMS = ByteBuffer.allocateDirect(FRAME_BYTES).order(ByteOrder.nativeOrder());
    private static RenderPipeline cpuSolid, cpuFluid, gpuSolid, gpuFluid, composite;
    private static volatile boolean resetRequested, supported, discrete, gpuFailed;
    private static boolean failed;
    private static volatile String reason = "";
    public static boolean gpu(LodOptions.Processing mode) {
        return !gpuFailed && supported && (mode == LodOptions.Processing.GPU || mode == LodOptions.Processing.AUTO && discrete);
    }
    public static String reason() { return reason; }
    public static boolean paused() { return failed; }
    public static void requestReset() { resetRequested = true; }
    public static void beginFrame() {
        if (resetRequested) { shutdown(); resetRequested = false; gpuFailed = false; reason = ""; }
    }
    public static void render(GameRenderer renderer) {
        beginFrame();
        if (failed || !LodClient.enabled()) return;
        var frame = LodClient.frame();
        if (frame == null) return;
        try {
            var mc = Minecraft.getInstance(); var options = LodClient.options().active();
            if (options.distance() <= mc.options.renderDistance().get()) return;
            var camera = renderer.gameRenderState().levelRenderState.cameraRenderState;
            if (camera == null || !camera.initialized) return;
            if (frame.generation() != generation) { shutdown(); generation = frame.generation(); }
            init();
            var encoder = RenderSystem.getDevice().createCommandEncoder();
            upload(frame, encoder);
            if (active.isEmpty()) { encoder.submit(); return; }
            if (IrisAdapter.active()) {
                IrisAdapter.render(renderer, active.values().stream().map(r -> r.source).toList());
                encoder.submit(); return;
            }
            var main = renderer.mainRenderTarget();
            resize(main.width, main.height, main.getColorTexture().getFormat());
            int nearBlocks = java.lang.Math.max(16, (mc.options.renderDistance().get() - 1) * 16);
            int farBlocks = options.distance() * 16;
            boolean zeroToOne = RenderSystem.getDevice().getDeviceInfo().isZZeroToOne();
            // The full-detail radius is horizontal, not a camera-space clipping plane.
            // A distant hillside can be much closer along the camera's forward axis.
            var depthProjection = new Matrix4f().setPerspective(2 * (float)java.lang.Math.atan(1 / camera.projectionMatrix.m11()),
                    (float)width / height, farBlocks, .05f, zeroToOne);
            var projection = new Matrix4f(camera.projectionMatrix)
                    .m22(depthProjection.m22()).m32(depthProjection.m32());
            var viewProjection = new Matrix4f(projection).mul(camera.viewRotationMatrix);
            var inverseFar = new Matrix4f(projection).invert();
            var inverseNear = new Matrix4f(camera.projectionMatrix).invert();
            UNIFORMS.clear();
            viewProjection.get(0, UNIFORMS); inverseFar.get(64, UNIFORMS); inverseNear.get(128, UNIFORMS);
            int baseX = (int)java.lang.Math.floor(camera.pos.x), baseY = (int)java.lang.Math.floor(camera.pos.y), baseZ = (int)java.lang.Math.floor(camera.pos.z);
            UNIFORMS.position(192).putInt(baseX).putInt(baseY).putInt(baseZ).putInt(zeroToOne ? 1 : 0);
            UNIFORMS.putFloat((float)(camera.pos.x - baseX)).putFloat((float)(camera.pos.y - baseY)).putFloat((float)(camera.pos.z - baseZ)).putFloat(nearBlocks);
            var fogData = camera.fogData;
            var fog = fogData == null ? new Vector4f(.6f, .7f, .8f, 1) : fogData.color;
            UNIFORMS.putFloat(fog.x).putFloat(fog.y).putFloat(fog.z).putFloat(farBlocks);
            UNIFORMS.putFloat(1).putFloat(fogData == null ? Float.MAX_VALUE : fogData.environmentalStart)
                    .putFloat(fogData == null ? Float.MAX_VALUE : fogData.environmentalEnd)
                    .putFloat(fogData == null ? farBlocks * .6f : fogData.renderDistanceStart).flip();
            encoder.writeToBuffer(frameUniform.slice(), UNIFORMS);
            encoder.clearColorAndDepthTextures(farColor, new Vector4f(), farDepth, 0);
            var frustum = new FrustumIntersection(viewProjection);
            draw(encoder, false, frustum, camera.pos.x, camera.pos.y, camera.pos.z);
            draw(encoder, true, frustum, camera.pos.x, camera.pos.y, camera.pos.z);
            try (var pass = encoder.createRenderPass(() -> "Cubeon LOD depth composition", main.getColorTextureView(), Optional.empty())) {
                pass.setPipeline(RenderSystem.getCompiledPipeline(composite));
                pass.setUniform("LodFrame", frameUniform);
                var sampler = RenderSystem.getSamplerCache().getClampToEdge(FilterMode.NEAREST);
                pass.setUniform("FarColor", colorView, sampler); pass.setUniform("FarDepth", depthView, sampler);
                pass.setUniform("NearDepth", main.getDepthTextureView(), sampler);
                // RenderPearl orders counts before offsets: vertices, instances, first vertex, first instance.
                pass.draw(3, 1, 0, 0);
            }
            encoder.submit();
        } catch (Exception | LinkageError ex) {
            boolean usedGpu = active.values().stream().anyMatch(r -> r.source.gpu());
            shutdown();
            if (usedGpu && !gpuFailed) { gpuFailed = true; reason = " · GPU path failed; using CPU"; }
            else { failed = true; reason = " · LOD rendering paused: " + ex.getMessage(); }
            LodClient.LOG.warn("Optional LOD renderer could not draw terrain", ex);
        }
    }
    private static void init() {
        var device = RenderSystem.getDevice(); var info = device.getDeviceInfo();
        supported = info.features().nonZeroFirstInstance() && info.features().drawIndirect();
        discrete = info.type() == DeviceType.DISCRETE;
        if (!supported && LodClient.options().active().processing() == LodOptions.Processing.GPU) reason = " · GPU geometry unsupported; using CPU";
        if (frameUniform == null) frameUniform = device.createBuffer(() -> "Cubeon LOD frame", GpuBuffer.USAGE_UNIFORM | GpuBuffer.USAGE_COPY_DST, FRAME_BYTES);
        if (indirect == null) indirect = device.createBuffer(() -> "Cubeon LOD draw list", GpuBuffer.USAGE_INDIRECT_PARAMETERS | GpuBuffer.USAGE_COPY_DST, 1 << 20);
        if (cpuSolid == null) {
            cpuSolid = terrain(false, false); cpuFluid = terrain(false, true);
            gpuSolid = terrain(true, false); gpuFluid = terrain(true, true);
            composite = RenderPipeline.builder().withLocation(id("pipeline/lod_compose"))
                    .withVertexShader(id("core/lod_compose")).withFragmentShader(id("core/lod_compose"))
                    .withBindGroupLayout(BindGroupLayout.builder().withUniform("LodFrame", UniformType.UNIFORM_BUFFER)
                            .withUniform("FarColor", UniformType.COMBINED_IMAGE_SAMPLER).withUniform("FarDepth", UniformType.COMBINED_IMAGE_SAMPLER)
                            .withUniform("NearDepth", UniformType.COMBINED_IMAGE_SAMPLER).build())
                    .withCull(false).withPrimitiveTopology(PrimitiveTopology.TRIANGLES)
                    .withColorTargetState(new ColorTargetState(BlendFunction.TRANSLUCENT_PREMULTIPLIED_ALPHA))
                    .withDepthStencilState(Optional.empty()).build();
        }
    }
    private static RenderPipeline terrain(boolean gpu, boolean fluid) {
        var format = VertexFormat.builder(gpu ? 1 : 0).addAttribute("TileOrigin", GpuFormat.RG32_SINT)
                .addAttribute("FacePosition", GpuFormat.RGB32_FLOAT).addAttribute("FaceUv", GpuFormat.RG32_FLOAT)
                .addAttribute("FaceDirection", GpuFormat.R32_UINT).addAttribute("FaceColor", GpuFormat.RGBA8_UNORM)
                .addAttribute("AtlasRect", GpuFormat.RGBA32_FLOAT).addAttribute("FaceLight", GpuFormat.R32_UINT)
                .addAttribute("FaceFlags", GpuFormat.R32_UINT).addAttribute("FaceMaterial", GpuFormat.R32_UINT).build();
        var builder = RenderPipeline.builder().withLocation(id("pipeline/lod_" + (gpu ? "gpu" : "cpu") + (fluid ? "_water" : "_solid")))
                .withVertexShader(id("core/lod_terrain")).withFragmentShader(id("core/lod_terrain"))
                .withVertexBinding(0, format).withPrimitiveTopology(PrimitiveTopology.TRIANGLES).withCull(true)
                .withBindGroupLayout(BindGroupLayout.builder().withUniform("LodFrame", UniformType.UNIFORM_BUFFER)
                        .withUniform("BlockAtlas", UniformType.COMBINED_IMAGE_SAMPLER).build())
                .withDepthStencilState(new DepthStencilState(CompareOp.GREATER_THAN_OR_EQUAL, true));
        if (gpu) builder.withShaderDefine("LOD_GPU");
        if (fluid) builder.withColorTargetState(new ColorTargetState(BlendFunction.TRANSLUCENT));
        else builder.withColorTargetState(ColorTargetState.DEFAULT);
        return builder.build();
    }
    private static void resize(int w, int h, GpuFormat format) {
        if (w == width && h == height && farColor != null && farColor.getFormat() == format) return;
        releaseTargets(); width = w; height = h;
        var device = RenderSystem.getDevice();
        if ((long)w * h * (format.blockSize() + 4) > LodOptions.GPU_LIMIT / 2) throw new IllegalStateException("LOD frame targets exceed GPU budget");
        farColor = device.createTexture("Cubeon far terrain", GpuTexture.USAGE_RENDER_ATTACHMENT | GpuTexture.USAGE_TEXTURE_BINDING | GpuTexture.USAGE_COPY_DST, format, w, h, 1, 1);
        farDepth = device.createTexture("Cubeon far depth", GpuTexture.USAGE_RENDER_ATTACHMENT | GpuTexture.USAGE_TEXTURE_BINDING | GpuTexture.USAGE_COPY_DST, GpuFormat.D32_FLOAT, w, h, 1, 1);
        colorView = device.createTextureView(farColor); depthView = device.createTextureView(farDepth);
    }
    private static void upload(TerrainWorker.Frame frame, CommandEncoder encoder) {
        if (target == frame && uploadComplete) return;
        // Complete the current replacement before consuming newer publications.
        if (target == null || uploadComplete) {
            pending = new LinkedHashMap<>(); target = frame; uploading = 0; uploadOffset = 0; uploadComplete = false;
        }
        frame = target;
        int budget = UPLOAD;
        var device = RenderSystem.getDevice();
        while (uploading < frame.meshes().size() && budget > 0) {
            var mesh = frame.meshes().get(uploading);
            var resident = pending.get(mesh.key());
            if (resident == null) {
                var old = active.get(mesh.key());
                if (old != null && old.source.stamp() == mesh.stamp() && old.source.gpu() == mesh.gpu()) {
                    pending.put(mesh.key(), old); uploading++; continue;
                }
                long limit = java.lang.Math.min(LodOptions.GPU_LIMIT / 2, device.getDeviceInfo().limits().maxMemoryAllocationSize());
                var solid = ARENA.allocate(device, mesh.solid().length, limit);
                var fluid = ARENA.allocate(device, mesh.fluid().length, limit);
                if ((solid == null && mesh.solid().length != 0) || (fluid == null && mesh.fluid().length != 0)) {
                    ARENA.release(solid); ARENA.release(fluid); reason = " · GPU terrain budget reached; keeping previous coverage"; return;
                }
                resident = new Resident(mesh, solid, fluid); pending.put(mesh.key(), resident);
            }
            int total = mesh.solid().length + mesh.fluid().length;
            while (uploadOffset < total && budget > 0) {
                boolean solid = uploadOffset < mesh.solid().length;
                byte[] source = solid ? mesh.solid() : mesh.fluid();
                var slice = solid ? resident.solid : resident.fluid;
                int offset = solid ? uploadOffset : uploadOffset - mesh.solid().length;
                int count = java.lang.Math.min(budget, source.length - offset);
                STAGING.clear(); STAGING.put(source, offset, count).flip();
                encoder.writeToBuffer(slice.page().buffer.slice(slice.offset() + offset, count), STAGING);
                uploadOffset += count; budget -= count;
            }
            if (uploadOffset == total) { uploadOffset = 0; uploading++; }
        }
        if (uploading == frame.meshes().size()) {
            for (Resident old : active.values()) if (!pending.containsValue(old)) release(old);
            active = pending; pending = new LinkedHashMap<>(); uploadComplete = true; ARENA.trim();
        }
    }
    private static void draw(CommandEncoder encoder, boolean fluid, FrustumIntersection frustum, double x, double y, double z) {
        Map<BufferArena.Page, List<Resident>> batches = new LinkedHashMap<>();
        for (Resident r : active.values()) {
            var slice = fluid ? r.fluid : r.solid;
            if (slice == null) continue;
            var key = r.source.key();
            if (!frustum.testAab((float)(key.blockX() - x), (float)(r.source.minY() - y), (float)(key.blockZ() - z),
                    (float)(key.blockX() + key.size() - x), (float)(r.source.maxY() - y), (float)(key.blockZ() + key.size() - z))) continue;
            batches.computeIfAbsent(slice.page(), p -> new ArrayList<>()).add(r);
        }
        int indirectOffset = fluid ? (1 << 19) : 0;
        record Commands(int offset, int bytes, int count) { }
        Map<BufferArena.Page, Commands> commands = new HashMap<>();
        if (RenderSystem.getDevice().getDeviceInfo().features().drawIndirect()) {
            for (var batch : batches.entrySet()) {
                STAGING.clear(); boolean gpu = batch.getValue().get(0).source.gpu();
                for (var r : batch.getValue()) {
                    var slice = fluid ? r.fluid : r.solid;
                    int count = fluid ? r.source.fluidCount() : r.source.solidCount();
                    STAGING.putInt(gpu ? 6 : count).putInt(gpu ? count : 1)
                            .putInt(gpu ? 0 : (int)(slice.offset() / PackedMesh.STRIDE))
                            .putInt(gpu ? (int)(slice.offset() / PackedMesh.STRIDE) : 0);
                }
                STAGING.flip(); int bytes = STAGING.remaining();
                if (indirectOffset + bytes > (fluid ? indirect.size() : 1 << 19)) break;
                encoder.writeToBuffer(indirect.slice(indirectOffset, bytes), STAGING);
                commands.put(batch.getKey(), new Commands(indirectOffset, bytes, batch.getValue().size()));
                indirectOffset += bytes;
            }
        }
        var device = RenderSystem.getDevice();
        var atlas = Minecraft.getInstance().getAtlasManager().getAtlasOrThrow(AtlasIds.BLOCKS);
        try (var pass = encoder.createRenderPass(() -> fluid ? "Cubeon LOD fluids" : "Cubeon LOD opaque", colorView, Optional.empty(), depthView, OptionalDouble.empty())) {
            for (var batch : batches.entrySet()) {
                var first = batch.getValue().get(0); boolean gpu = first.source.gpu();
                pass.setPipeline(RenderSystem.getCompiledPipeline(gpu ? fluid ? gpuFluid : gpuSolid : fluid ? cpuFluid : cpuSolid));
                pass.setUniform("LodFrame", frameUniform);
                pass.setUniform("BlockAtlas", atlas.getTextureView(), atlas.getSampler());
                pass.setVertexBuffer(0, batch.getKey().buffer.slice());
                if (device.getDeviceInfo().features().drawIndirect()) {
                    Commands command = commands.get(batch.getKey());
                    if (command == null) continue;
                    pass.drawIndirect(indirect.slice(command.offset(), command.bytes()), command.count());
                } else for (var r : batch.getValue()) {
                    var slice = fluid ? r.fluid : r.solid; int count = fluid ? r.source.fluidCount() : r.source.solidCount();
                    pass.draw(gpu ? 6 : count, gpu ? count : 1,
                            gpu ? 0 : (int)(slice.offset() / PackedMesh.STRIDE),
                            gpu ? (int)(slice.offset() / PackedMesh.STRIDE) : 0);
                }
            }
        }
    }
    private static void release(Resident resident) { ARENA.release(resident.solid); ARENA.release(resident.fluid); }
    private static void releaseTargets() {
        if (colorView != null) colorView.close(); if (depthView != null) depthView.close();
        if (farColor != null) farColor.close(); if (farDepth != null) farDepth.close();
        colorView = depthView = null; farColor = farDepth = null; width = height = 0;
    }
    public static void shutdown() {
        ARENA.close(); active.clear(); pending.clear(); target = null; uploadComplete = false; generation = -1;
        releaseTargets(); if (frameUniform != null) frameUniform.close(); if (indirect != null) indirect.close();
        frameUniform = indirect = null; failed = false;
    }
    private static Identifier id(String path) { return Identifier.parse("cubeon-client:" + path); }
}
