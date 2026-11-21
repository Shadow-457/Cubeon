package com.cubeon.client.lod.core;

import java.util.*;

/** Minecraft-free, immutable material runs. Unknown columns are distinct from known air. */
public final class Terrain {
    private Terrain() { }
    public static final int FLUID = 1, CUTOUT = 2;
    public record Material(int state, int color, int light, int flags) { }
    public record Span(int min, int max, Material material) {
        public Span { if (max <= min) throw new IllegalArgumentException("Empty material run"); }
    }
    public record Column(List<Span> spans) {
        public Column { spans = List.copyOf(spans); }
        public static final Column AIR = new Column(List.of());
        public long bytes() { return 32L + spans.size() * 64L; }
    }
    public static final class Chunk {
        public final int x, z;
        public final long revision;
        private final Column[] columns;
        public Chunk(int x, int z, long revision, Column[] columns) {
            if (columns.length != 256) throw new IllegalArgumentException("256 columns required");
            this.x = x; this.z = z; this.revision = revision; this.columns = columns.clone();
            for (Column c : this.columns) Objects.requireNonNull(c);
        }
        public Column at(int x, int z) { return columns[z * 16 + x]; }
        public long bytes() {
            long bytes = 1100;
            for (Column c : columns) bytes += c.bytes();
            return bytes;
        }
        public Chunk withRevision(long value) { return new Chunk(x, z, value, columns); }
        public long key() { return Terrain.key(x, z); }
    }
    public static long key(int x, int z) { return (long)x << 32 | (z & 0xffffffffL); }
    public static int x(long key) { return (int)(key >> 32); }
    public static int z(long key) { return (int)key; }

    /** Union footprints, choosing their dominant material at each height interval. */
    public static Column reduce(Collection<Column> columns) {
        if (columns.size() == 1) return columns.iterator().next();
        TreeMap<Integer, Map<Material, Integer>> events = new TreeMap<>();
        for (Column c : columns) for (Span s : c.spans()) {
            events.computeIfAbsent(s.min(), k -> new HashMap<>()).merge(s.material(), 1, Integer::sum);
            events.computeIfAbsent(s.max(), k -> new HashMap<>()).merge(s.material(), -1, Integer::sum);
        }
        List<Span> out = new ArrayList<>();
        Map<Material, Integer> counts = new HashMap<>();
        Integer previous = null;
        for (var event : events.entrySet()) {
            if (previous != null && previous < event.getKey()) {
                Material winner = null; int best = 0;
                for (var count : counts.entrySet()) {
                    Material m = count.getKey();
                    if (count.getValue() > best || count.getValue() == best && best > 0
                            && compare(m, winner) < 0) { best = count.getValue(); winner = m; }
                }
                if (winner != null) append(out, previous, event.getKey(), winner);
            }
            event.getValue().forEach((m, n) -> counts.merge(m, n, Integer::sum));
            counts.values().removeIf(n -> n <= 0);
            previous = event.getKey();
        }
        return new Column(out);
    }
    private static int compare(Material a, Material b) {
        if (b == null) return -1;
        int n = Integer.compare(a.state(), b.state());
        return n == 0 ? Integer.compareUnsigned(a.color(), b.color()) : n;
    }
    public static void append(List<Span> out, int min, int max, Material material) {
        if (!out.isEmpty()) {
            Span last = out.get(out.size() - 1);
            if (last.max() == min && last.material().equals(material)) {
                out.set(out.size() - 1, new Span(last.min(), max, material)); return;
            }
        }
        out.add(new Span(min, max, material));
    }
}
