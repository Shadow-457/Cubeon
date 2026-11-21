package com.cubeon.client.lod;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import net.minecraft.client.Minecraft;
import net.minecraft.world.level.block.Block;

/** Resolve Minecraft models only on the client thread; mesh workers see immutable UV records. */
public final class TextureCatalog {
    public record Uv(float u, float v, float width, float height) { }
    private final Map<Integer, Uv[]> entries = new ConcurrentHashMap<>();
    private final Set<Integer> requested = ConcurrentHashMap.newKeySet();
    private volatile long revision;
    public Uv get(int state, int face) {
        Uv[] uv = entries.get(state); if (uv == null) requested.add(state); return uv == null ? null : uv[face];
    }
    public long revision() { return revision; }
    public void resolve(int state) {
        if (entries.containsKey(state)) return;
        var mc = Minecraft.getInstance();
        var block = Block.stateById(state);
        var models = mc.getModelManager();
        var sprite = models.getBlockStateModelSet().getParticleMaterial(block).sprite();
        var faces = new Uv[6];
        java.util.Arrays.fill(faces, uv(sprite));
        if (block.getRenderShape() == net.minecraft.world.level.block.RenderShape.INVISIBLE && !block.getFluidState().isEmpty()) {
            var fluid = models.getFluidStateModelSet().get(block.getFluidState());
            for (int i = 0; i < 6; i++) faces[i] = uv((i == 2 || i == 3 ? fluid.stillMaterial() : fluid.flowingMaterial()).sprite());
        } else {
            var parts = new java.util.ArrayList<net.minecraft.client.renderer.block.dispatch.BlockStateModelPart>();
            models.getBlockStateModelSet().get(block).collectParts(net.minecraft.util.RandomSource.create(0), parts);
            var directions = new net.minecraft.core.Direction[]{net.minecraft.core.Direction.WEST, net.minecraft.core.Direction.EAST,
                    net.minecraft.core.Direction.DOWN, net.minecraft.core.Direction.UP, net.minecraft.core.Direction.NORTH, net.minecraft.core.Direction.SOUTH};
            for (int i = 0; i < 6; i++) for (var part : parts) {
                var quads = part.getQuads(directions[i]);
                if (!quads.isEmpty()) { faces[i] = uv(quads.get(0).materialInfo().sprite()); break; }
            }
        }
        entries.put(state, faces);
        requested.remove(state); revision++;
    }
    private static Uv uv(net.minecraft.client.renderer.texture.TextureAtlasSprite sprite) {
        return new Uv(sprite.getU0(), sprite.getV0(), sprite.getU1() - sprite.getU0(), sprite.getV1() - sprite.getV0());
    }
    public void drain(long deadline) {
        int count = 0;
        for (int state : requested) {
            resolve(state);
            if (++count >= 16 || System.nanoTime() >= deadline) break;
        }
    }
}
