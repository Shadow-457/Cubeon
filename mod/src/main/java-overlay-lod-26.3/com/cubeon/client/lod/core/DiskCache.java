package com.cubeon.client.lod.core;

import com.cubeon.client.lod.LodOptions;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/** Private, replaceable chunk summaries. All calls belong to the terrain worker, never rendering. */
public final class DiskCache {
    private static final int MAGIC = 0x434c4f44, FORMAT = 1, MAX_RECORD = 4 << 20, MAX_SPANS = 262144;
    private static final int MAX_FILES = 32768;
    private final Path root, directory;
    private final Map<Long, Path> current = new HashMap<>();
    private final LinkedHashMap<Path, Long> files = new LinkedHashMap<>();
    private long bytes;
    public DiskCache(Path root, String identity) throws IOException {
        this.root = root.toAbsolutePath().normalize(); directory = this.root.resolve(identity).normalize();
        if (!directory.startsWith(this.root)) throw new IOException("Cache identity outside private root");
        if (!Files.exists(root)) return;
        List<Path> found;
        try (var stream = Files.walk(root)) {
            found = stream.filter(p -> p.getFileName().toString().endsWith(".clod") && Files.isRegularFile(p, LinkOption.NOFOLLOW_LINKS))
                    .sorted(Comparator.comparingLong(DiskCache::modified)).toList();
        }
        for (Path p : found) {
            long size = Files.size(p); files.put(p, size); bytes += size;
            if (p.getParent().equals(directory)) {
                String[] at = p.getFileName().toString().replace(".clod", "").split("_");
                try { if (at.length == 2) current.put(Terrain.key(Integer.parseInt(at[0]), Integer.parseInt(at[1])), p); }
                catch (NumberFormatException ignored) { /* Foreign names are never decoded. */ }
            }
        }
        prune();
    }
    public Set<Long> keys() { return Set.copyOf(current.keySet()); }
    public long bytes() { return bytes; }
    public Terrain.Chunk read(long key) throws IOException {
        Path path = current.get(key);
        if (path == null) return null;
        try {
            long size = Files.size(path);
            if (size > MAX_RECORD) throw new IOException("Oversized cached chunk");
            try (var input = new DataInputStream(new InflaterInputStream(Files.newInputStream(path)))) {
                if (input.readInt() != MAGIC || input.readInt() != FORMAT) throw new IOException("LOD cache format mismatch");
                int x = input.readInt(), z = input.readInt(); long revision = input.readLong();
                if (Terrain.key(x, z) != key) throw new IOException("LOD cache coordinate mismatch");
                Terrain.Column[] columns = new Terrain.Column[256]; int total = 0;
                for (int i = 0; i < 256; i++) {
                    int count = input.readUnsignedShort(); total += count;
                    if (count > 4096 || total > MAX_SPANS) throw new IOException("Too many cached spans");
                    List<Terrain.Span> spans = new ArrayList<>(count); int last = Integer.MIN_VALUE;
                    for (int j = 0; j < count; j++) {
                        int min = input.readInt(), max = input.readInt();
                        Terrain.Material material = new Terrain.Material(input.readInt(), input.readInt(), input.readInt(), input.readInt());
                        if (min < last || min < -32768 || max > 32768 || max <= min) throw new IOException("Invalid cached material run");
                        spans.add(new Terrain.Span(min, max, material)); last = max;
                    }
                    columns[i] = new Terrain.Column(spans);
                }
                if (input.read() != -1) throw new IOException("Trailing cached chunk data");
                return new Terrain.Chunk(x, z, revision, columns);
            }
        } catch (IOException | IllegalArgumentException ex) {
            remove(path); current.remove(key);
            throw new IOException("Discarded damaged LOD summary: " + ex.getMessage(), ex);
        }
    }
    public void write(Terrain.Chunk chunk) throws IOException {
        ByteArrayOutputStream bytesOut = new ByteArrayOutputStream();
        try (var out = new DataOutputStream(new DeflaterOutputStream(bytesOut))) {
            out.writeInt(MAGIC); out.writeInt(FORMAT); out.writeInt(chunk.x); out.writeInt(chunk.z); out.writeLong(chunk.revision);
            for (int z = 0; z < 16; z++) for (int x = 0; x < 16; x++) {
                var spans = chunk.at(x, z).spans();
                if (spans.size() > 4096) throw new IOException("Oversized source column");
                out.writeShort(spans.size());
                for (var s : spans) {
                    out.writeInt(s.min()); out.writeInt(s.max()); out.writeInt(s.material().state());
                    out.writeInt(s.material().color()); out.writeInt(s.material().light()); out.writeInt(s.material().flags());
                }
            }
        }
        if (bytesOut.size() > MAX_RECORD) throw new IOException("Oversized source summary");
        Files.createDirectories(directory);
        Path target = directory.resolve(chunk.x + "_" + chunk.z + ".clod");
        Path temp = Files.createTempFile(directory, ".chunk-", ".tmp");
        try {
            Files.write(temp, bytesOut.toByteArray());
            Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temp); }
        Long old = files.remove(target); if (old != null) bytes -= old;
        files.put(target, (long)bytesOut.size()); bytes += bytesOut.size(); current.put(chunk.key(), target);
        prune();
    }
    public void clear() throws IOException {
        for (Path path : List.copyOf(current.values())) remove(path);
        current.clear();
    }
    private void prune() throws IOException {
        while (bytes > LodOptions.DISK_LIMIT || files.size() > MAX_FILES) remove(files.keySet().iterator().next());
    }
    private void remove(Path p) throws IOException {
        Files.deleteIfExists(p);
        Long size = files.remove(p); if (size != null) bytes -= size;
        if (p.getParent().equals(directory)) current.values().removeIf(v -> v.equals(p));
    }
    private static long modified(Path p) { try { return Files.getLastModifiedTime(p).toMillis(); } catch (IOException ex) { return 0; } }
}
