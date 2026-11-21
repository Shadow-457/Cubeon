package com.cubeon.client.lod;

import com.cubeon.client.lod.core.Terrain;
import java.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.core.*;
import net.minecraft.world.level.LightLayer;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.RenderShape;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.*;

/** Each step copies one bounded unit on the client thread. Workers only read private copies. */
public final class ChunkSnapshot {
    private record Section(int y, PalettedContainer<BlockState> states) { }
    private record Light(DataLayer sky, DataLayer block) { }
    private record Material(int id, int flags, int[] colors) { }
    private final List<Section> sections = new ArrayList<>();
    private final Map<SectionPos, Light> lights = new HashMap<>();
    private final Map<BlockState, Material> palette = new HashMap<>();
    public final LevelChunk chunk;
    public final long revision;
    public final int chunkX, chunkZ;
    private int index, halo, colorAt;
    private Section current;
    private final ArrayDeque<BlockState> paletteWork = new ArrayDeque<>();
    private BlockState tinting;
    private Material material;
    public ChunkSnapshot(LevelChunk chunk, long revision) {
        this.chunk = chunk; this.revision = revision; chunkX = chunk.getPos().x(); chunkZ = chunk.getPos().z();
    }
    public boolean step(TextureCatalog textures) {
        var mc = Minecraft.getInstance();
        if (current == null) {
            if (index >= chunk.getSections().length) return true;
            current = new Section(chunk.getMinY() + index * 16, chunk.getSections()[index++].getStates().copy());
            current.states.forEachInPalette(s -> { if (!palette.containsKey(s) && !s.isAir()) paletteWork.add(s); });
            halo = 0;
            return false;
        }
        if (halo < 27) {
            int n = halo++;
            var pos = SectionPos.of(chunkX + n % 3 - 1, Math.floorDiv(current.y, 16) + n / 9 - 1, chunkZ + n / 3 % 3 - 1);
            if (!lights.containsKey(pos)) {
                var engine = mc.level.getChunkSource().getLightEngine();
                DataLayer sky = engine.getLayerListener(LightLayer.SKY).getDataLayerData(pos);
                DataLayer block = engine.getLayerListener(LightLayer.BLOCK).getDataLayerData(pos);
                lights.put(pos, new Light(sky == null ? null : sky.copy(), block == null ? null : block.copy()));
            }
            return false;
        }
        if (tinting == null && !paletteWork.isEmpty()) {
            tinting = paletteWork.remove();
            int id = Block.getId(tinting); textures.resolve(id);
            boolean fluid = tinting.getRenderShape() == RenderShape.INVISIBLE && !tinting.getFluidState().isEmpty();
            material = new Material(id, fluid ? Terrain.FLUID : tinting.canOcclude() ? 0 : Terrain.CUTOUT, new int[256]);
            colorAt = 0;
            return false;
        }
        if (tinting != null) {
            boolean fluid = (material.flags & Terrain.FLUID) != 0;
            var tint = fluid ? mc.getModelManager().getFluidStateModelSet().get(tinting.getFluidState()).tintSource()
                    : mc.getBlockColors().getTintSource(tinting, 0);
            // Retain each column's biome tint. Small batches fit the tick capture budget.
            for (int i = 0; i < 8 && colorAt < 256; i++, colorAt++) {
                int x = colorAt % 16, z = colorAt / 16;
                var pos = new BlockPos(chunkX * 16 + x, chunk.getHeight(net.minecraft.world.level.levelgen.Heightmap.Types.WORLD_SURFACE, x, z), chunkZ * 16 + z);
                int rgb = tint == null ? 0xffffff : tint.colorInWorld(tinting, mc.level, pos);
                if (rgb == -1) rgb = 0xffffff;
                material.colors[colorAt] = (fluid ? 0xa6000000 : 0xff000000) | (rgb & 255) << 16 | rgb & 0xff00 | (rgb >>> 16 & 255);
            }
            if (colorAt == 256) { palette.put(tinting, material); tinting = null; }
            return false;
        }
        sections.add(current); current = null;
        return index >= chunk.getSections().length;
    }
    private static final int[][] OFFSETS = {{0,0,0},{-1,0,0},{1,0,0},{0,-1,0},{0,1,0},{0,0,-1},{0,0,1}};
    public Terrain.Chunk summarize() {
        Terrain.Column[] columns = new Terrain.Column[256];
        for (int z = 0; z < 16; z++) for (int x = 0; x < 16; x++) {
            List<Terrain.Span> spans = new ArrayList<>();
            for (Section section : sections) for (int y = 0; y < 16; y++) {
                BlockState state = section.states.get(x, y, z);
                if (state.isAir()) continue;
                Material base = palette.get(state);
                int sky = 0, block = 0;
                for (int[] d : OFFSETS) {
                    int sx = x + d[0], sy = section.y + y + d[1], sz = z + d[2];
                    Light light = lights.get(SectionPos.of(chunkX + Math.floorDiv(sx, 16), Math.floorDiv(sy, 16), chunkZ + Math.floorDiv(sz, 16)));
                    if (light != null) {
                        if (light.sky != null) sky = Math.max(sky, light.sky.get(Math.floorMod(sx, 16), Math.floorMod(sy, 16), Math.floorMod(sz, 16)));
                        if (light.block != null) block = Math.max(block, light.block.get(Math.floorMod(sx, 16), Math.floorMod(sy, 16), Math.floorMod(sz, 16)));
                    }
                }
                Terrain.append(spans, section.y + y, section.y + y + 1,
                        new Terrain.Material(base.id, base.colors[z * 16 + x], sky << 4 | block, base.flags));
            }
            columns[z * 16 + x] = new Terrain.Column(spans);
        }
        return new Terrain.Chunk(chunkX, chunkZ, revision, columns);
    }
}
