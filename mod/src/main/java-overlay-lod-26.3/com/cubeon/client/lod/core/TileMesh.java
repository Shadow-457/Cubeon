package com.cubeon.client.lod.core;

import java.util.*;

/** Shared faces for CPU expansion and GPU instancing; hidden material boundaries emit no faces. */
public record TileMesh(TilePlan.Key key, List<TileMesh.Face> faces, int minY, int maxY) {
    public record Face(float x, float y, float z, float width, float height, int direction, Terrain.Material material) { }
    public TileMesh { faces = List.copyOf(faces); }
    public long bytes() { return 96L + faces.size() * 96L; }
    public static final class BudgetExceeded extends RuntimeException { }
    public static TileMesh build(TilePlan.Key key, Terrain.Column[] grid) { return build(key, grid, 32768); }
    public static TileMesh build(TilePlan.Key key, Terrain.Column[] grid, int limit) {
        List<Face> faces = new ArrayList<>() {
            public boolean add(Face f) { if (size() >= limit) throw new BudgetExceeded(); return super.add(f); }
        };
        int step = 1 << key.level(), minY = Integer.MAX_VALUE, maxY = Integer.MIN_VALUE;
        for (int z = 0; z < 16; z++) for (int x = 0; x < 16; x++) {
            Terrain.Column column = grid[z * 16 + x];
            if (column == null) continue;
            List<Terrain.Span> spans = column.spans();
            for (int i = 0; i < spans.size(); i++) {
                Terrain.Span s = spans.get(i);
                minY = Math.min(minY, s.min()); maxY = Math.max(maxY, s.max());
                int bx = x * step, bz = z * step;
                if (i == 0 || spans.get(i - 1).max() != s.min()
                        || !occludes(spans.get(i - 1).material(), s.material()))
                    faces.add(new Face(bx, s.min(), bz, step, step, 2, s.material()));
                if (i + 1 == spans.size() || spans.get(i + 1).min() != s.max()
                        || !occludes(spans.get(i + 1).material(), s.material()))
                    faces.add(new Face(bx, s.max(), bz + step, step, step, 3, s.material()));
                side(faces, s, x > 0 ? grid[z * 16 + x - 1] : null, bx, bz, step, 0);
                side(faces, s, x < 15 ? grid[z * 16 + x + 1] : null, bx + step, bz + step, step, 1);
                side(faces, s, z > 0 ? grid[(z - 1) * 16 + x] : null, bx + step, bz, step, 4);
                side(faces, s, z < 15 ? grid[(z + 1) * 16 + x] : null, bx, bz + step, step, 5);
            }
        }
        return new TileMesh(key, merge(faces), minY == Integer.MAX_VALUE ? 0 : minY, maxY == Integer.MIN_VALUE ? 0 : maxY);
    }
    private static boolean occludes(Terrain.Material neighbour, Terrain.Material material) {
        return (neighbour.flags() & (Terrain.FLUID | Terrain.CUTOUT)) == 0
                || (material.flags() & Terrain.FLUID) != 0 && neighbour.state() == material.state();
    }
    private static void side(List<Face> out, Terrain.Span span, Terrain.Column neighbour,
                             int x, int z, int step, int direction) {
        int at = span.min();
        if (neighbour != null) for (Terrain.Span other : neighbour.spans()) {
            if (!occludes(other.material(), span.material()) || other.max() <= at || other.min() >= span.max()) continue;
            if (other.min() > at) out.add(new Face(x, at, z, step, other.min() - at, direction, span.material()));
            at = Math.max(at, other.max());
            if (at >= span.max()) return;
        }
        if (at < span.max()) out.add(new Face(x, at, z, step, span.max() - at, direction, span.material()));
    }
    /** Merge neighbouring equal coplanar faces along their U direction. */
    private static List<Face> merge(List<Face> faces) {
        record Row(int dir, float y, float perpendicular, float height, Terrain.Material material) { }
        Map<Row, TreeMap<Float, Face>> rows = new LinkedHashMap<>();
        for (Face f : faces) {
            float perpendicular = f.direction < 2 ? f.x : f.direction < 4 ? f.z : f.z;
            float along = f.direction < 2 ? f.z : f.x;
            float sign = f.direction == 1 || f.direction == 4 ? -1 : 1;
            Row row = new Row(f.direction, f.y, perpendicular, f.height, f.material);
            // Different faces in the same row retain distinct U positions.
            rows.computeIfAbsent(row, k -> new TreeMap<>()).put(along * sign, f);
        }
        List<Face> result = new ArrayList<>();
        for (var row : rows.values()) {
            Face last = null; float end = 0;
            for (var entry : row.entrySet()) {
                Face f = entry.getValue();
                if (last != null && entry.getKey() == end)
                    last = new Face(last.x, last.y, last.z, last.width + f.width, last.height, last.direction, last.material);
                else { if (last != null) result.add(last); last = f; }
                end = entry.getKey() + f.width;
            }
            if (last != null) result.add(last);
        }
        return result;
    }
    /** Exact shared corner construction. The shader uses the same direction basis. */
    public static float[] corner(Face f, int corner) {
        float u = (corner == 1 || corner == 2) ? f.width : 0;
        float v = corner >= 2 ? f.height : 0;
        return switch (f.direction) {
            case 0 -> new float[]{f.x, f.y + v, f.z + u};
            case 1 -> new float[]{f.x, f.y + v, f.z - u};
            case 2 -> new float[]{f.x + u, f.y, f.z + v};
            case 3 -> new float[]{f.x + u, f.y, f.z - v};
            case 4 -> new float[]{f.x - u, f.y + v, f.z};
            case 5 -> new float[]{f.x + u, f.y + v, f.z};
            default -> throw new IllegalArgumentException("Face direction");
        };
    }
}
