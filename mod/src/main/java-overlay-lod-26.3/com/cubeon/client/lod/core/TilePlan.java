package com.cubeon.client.lod.core;

import com.cubeon.client.lod.LodOptions;
import java.util.*;

/** Sparse quadtree: distance never allocates the millions of chunks inside its circle. */
public final class TilePlan {
    public record Key(int x, int z, int level) {
        public int size() { return 16 << level; }
        public int blockX() { return x * size(); }
        public int blockZ() { return z * size(); }
        public Key parent() { return new Key(Math.floorDiv(x, 2), Math.floorDiv(z, 2), level + 1); }
    }
    public static List<Key> select(Collection<Terrain.Chunk> chunks, int cameraX, int cameraZ,
                                   int nearChunks, int distance, LodOptions.Detail quality) {
        Map<Key, Integer> known = new HashMap<>();
        Set<Key> roots = new HashSet<>();
        for (Terrain.Chunk chunk : chunks) {
            Key key = new Key(chunk.x, chunk.z, 0);
            for (int level = 0; level <= 12; level++) {
                known.merge(key, 1, Integer::sum);
                if (level == 12) roots.add(key);
                key = key.parent();
            }
        }
        List<Key> result = new ArrayList<>();
        int split = quality == LodOptions.Detail.FULL ? 8 : quality == LodOptions.Detail.MEDIUM ? 4 : 2;
        long range = (long)Math.min(LodOptions.MAX_DISTANCE, Math.max(0, distance)) * 16;
        for (Key key : roots) visit(key, known, result, cameraX, cameraZ, nearChunks * 16, range, split);
        result.sort(Comparator.comparingDouble(k -> distance(k, cameraX, cameraZ)));
        return result;
    }
    private static void visit(Key k, Map<Key, Integer> known, List<Key> out, int x, int z, int near, long range, int split) {
        if (!known.containsKey(k) || distance(k, x, z) > range * range) return;
        // Every quality keeps block-sized cells at the seam; no coarse tile reaches over it.
        if (k.level > 0 && (known.get(k) != (1 << (k.level * 2))
                || distance(k, x, z) < Math.pow(Math.max(near + 32, k.size() * split), 2))) {
            for (int dz = 0; dz < 2; dz++) for (int dx = 0; dx < 2; dx++)
                visit(new Key(k.x * 2 + dx, k.z * 2 + dz, k.level - 1), known, out, x, z, near, range, split);
        } else out.add(k);
    }
    public static double distance(Key k, double x, double z) {
        double dx = Math.max(Math.max(k.blockX() - x, x - (k.blockX() + k.size())), 0);
        double dz = Math.max(Math.max(k.blockZ() - z, z - (k.blockZ() + k.size())), 0);
        return dx * dx + dz * dz;
    }
    public static Terrain.Column[] grid(Key tile, Collection<Terrain.Chunk> chunks) {
        @SuppressWarnings("unchecked") List<Terrain.Column>[] cells = (List<Terrain.Column>[])new List<?>[256];
        int width = 1 << tile.level;
        for (Terrain.Chunk chunk : chunks) {
            if (Math.floorDiv(chunk.x, width) != tile.x || Math.floorDiv(chunk.z, width) != tile.z) continue;
            for (int z = 0; z < 16; z++) for (int x = 0; x < 16; x++) {
                int cellX = (chunk.x * 16 + x - tile.blockX()) / width;
                int cellZ = (chunk.z * 16 + z - tile.blockZ()) / width;
                int index = cellZ * 16 + cellX;
                if (cells[index] == null) cells[index] = new ArrayList<>();
                cells[index].add(chunk.at(x, z));
            }
        }
        Terrain.Column[] grid = new Terrain.Column[256];
        for (int i = 0; i < 256; i++) if (cells[i] != null) grid[i] = Terrain.reduce(cells[i]);
        return grid;
    }
}
