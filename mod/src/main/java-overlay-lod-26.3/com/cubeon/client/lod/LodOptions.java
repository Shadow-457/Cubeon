package com.cubeon.client.lod;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Objects;

/** The renderer reads committed immutable values; Sodium owns the editing draft. */
public final class LodOptions {
    public static final int MAX_DISTANCE = 4096;
    public static final long CPU_LIMIT = 128L << 20, GPU_LIMIT = 128L << 20, DISK_LIMIT = 1L << 30;
    public static final int[] DISTANCES = {32, 64, 128, 256, 512, 1024, 2048, 4096};
    public enum Detail { FULL, MEDIUM, MAXIMUM_FPS }
    public enum Processing { AUTO, CPU, GPU }
    public record Value(boolean enabled, int distance, Detail detail, Processing processing,
                        boolean backgroundUpdates, boolean terrainCache,
                        boolean shaderIntegration, boolean shadows) {
        public Value normalized() {
            int d = 32;
            for (int step : DISTANCES) if (step <= Math.min(distance, MAX_DISTANCE)) d = step;
            return new Value(enabled, d, detail == null ? Detail.MEDIUM : detail,
                    processing == null ? Processing.AUTO : processing,
                    backgroundUpdates, terrainCache, shaderIntegration, shadows);
        }
    }
    public static final Value DEFAULT = new Value(false, 128, Detail.MEDIUM, Processing.AUTO, true, true, true, false);
    private static final Gson JSON = new GsonBuilder().setPrettyPrinting().create();
    private final Path file;
    private volatile Value active = DEFAULT;
    private volatile String error = "";
    public LodOptions(Path file) { this.file = file; }
    public Value active() { return active; }
    public String error() { return error; }
    public void load() {
        if (!Files.exists(file)) return;
        try {
            if (Files.size(file) > 65536) throw new IOException("LOD options exceed 64 KiB");
            // Merge missing fields into defaults, including booleans in partial old files.
            var base = JSON.toJsonTree(DEFAULT).getAsJsonObject();
            var saved = com.google.gson.JsonParser.parseString(Files.readString(file)).getAsJsonObject();
            saved.entrySet().forEach(e -> base.add(e.getKey(), e.getValue()));
            active = Objects.requireNonNull(JSON.fromJson(base, Value.class)).normalized();
            error = "";
        } catch (IOException | RuntimeException ex) { error = "Could not read LOD options: " + ex.getMessage(); }
    }
    public synchronized void commit(Value next) throws IOException {
        next = next.normalized();
        Path parent = file.toAbsolutePath().getParent();
        Files.createDirectories(parent);
        Path temp = Files.createTempFile(parent, ".cubeon-lod-", ".tmp");
        try {
            Files.writeString(temp, JSON.toJson(next) + "\n", StandardCharsets.UTF_8);
            Files.move(temp, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            active = next;
            error = "";
        } catch (IOException ex) { error = "Could not save LOD options: " + ex.getMessage(); throw ex; }
        finally { Files.deleteIfExists(temp); }
    }
}
