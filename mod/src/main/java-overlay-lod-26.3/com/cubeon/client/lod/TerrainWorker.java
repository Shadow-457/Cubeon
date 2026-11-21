package com.cubeon.client.lod;

import com.cubeon.client.lod.core.*;
import java.io.IOException;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** A bounded owner for summaries, disk and meshing. Publications belong to one world generation. */
public final class TerrainWorker implements AutoCloseable {
    public record Request(int x, int z, int near, LodOptions.Value options, boolean gpu, long textures) { }
    public record Frame(long generation, List<PackedMesh> meshes, String status, long cpuBytes) {
        public Frame { meshes = List.copyOf(meshes); }
    }
    private final long generation;
    private final ThreadPoolExecutor executor;
    private final TextureCatalog catalog;
    private final LinkedHashMap<Long, Terrain.Chunk> chunks = new LinkedHashMap<>(64, .75f, true);
    private final AtomicReference<Request> latest = new AtomicReference<>();
    private final AtomicBoolean planning = new AtomicBoolean();
    private final Map<TilePlan.Key, PackedMesh> meshes = new HashMap<>();
    private final Map<TilePlan.Key, Long> stamps = new HashMap<>();
    private volatile Frame frame;
    private volatile boolean closed;
    private DiskCache disk;
    private final Path root;
    private final CacheIdentity identity;
    private String fingerprint;
    private Set<Long> cached = new HashSet<>();
    private final Set<Long> deferred = new HashSet<>();
    private int residencyX, residencyZ;
    private boolean residencyAnchored;
    private long chunkBytes, revision, plannedRevision = -1;
    private Request planned;
    private String error = "";
    public TerrainWorker(long generation, Path root, CacheIdentity identity, TextureCatalog catalog, boolean useCache) {
        this.generation = generation; this.catalog = catalog; this.root = root; this.identity = identity;
        frame = new Frame(generation, List.of(), "Waiting for explored terrain", 0);
        executor = new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(64), r -> {
            Thread t = new Thread(r, "cubeon-lod-terrain"); t.setDaemon(true); t.setPriority(Thread.MIN_PRIORITY); return t;
        });
        if (useCache) submit(() -> {
            try { disk = openCache(); cached = new HashSet<>(disk.keys()); }
            catch (IOException ex) { error = "Terrain cache unavailable: " + ex.getMessage(); }
        });
    }
    private DiskCache openCache() throws IOException {
        if (fingerprint == null) fingerprint = identity.fingerprint();
        return new DiskCache(root, fingerprint);
    }
    public Frame frame() { return frame; }
    public int pending() { return executor.getQueue().size(); }
    public boolean submit(Runnable task) {
        if (closed) return false;
        try { executor.execute(() -> { if (!closed) task.run(); }); return true; }
        catch (RejectedExecutionException rejected) { return false; }
    }
    public void accept(Terrain.Chunk chunk) {
        if (closed || latest.get() != null && !latest.get().options.backgroundUpdates()) return;
        Terrain.Chunk previous = chunks.get(chunk.key());
        if (previous != null && previous.revision > chunk.revision) return;
        if (previous != null) chunkBytes -= previous.bytes();
        chunks.put(chunk.key(), chunk); chunkBytes += chunk.bytes(); revision++;
        // A new chunk invalidates exactly its pyramid ancestors, never every cached mesh.
        var key = new TilePlan.Key(chunk.x, chunk.z, 0);
        for (int i = 0; i <= 12; i++) { stamps.merge(key, 1L, Long::sum); key = key.parent(); }
        while (chunkBytes > LodOptions.CPU_LIMIT / 4 && !chunks.isEmpty()) {
            Request request = latest.get();
            int x = request == null ? chunk.x * 16 : request.x, z = request == null ? chunk.z * 16 : request.z;
            Terrain.Chunk evicted = chunks.values().stream().max(Comparator
                    .comparingDouble((Terrain.Chunk c) -> TilePlan.distance(new TilePlan.Key(c.x, c.z, 0), x, z))
                    .thenComparingLong(Terrain.Chunk::key)).orElseThrow();
            chunkBytes -= evicted.bytes(); chunks.remove(evicted.key()); deferred.add(evicted.key());
            var old = new TilePlan.Key(evicted.x, evicted.z, 0);
            for (int i = 0; i <= 12; i++) { stamps.merge(old, 1L, Long::sum); old = old.parent(); }
        }
        if (disk != null && !closed && latest.get() != null && latest.get().options.terrainCache()) {
            try { disk.write(chunk); cached = new HashSet<>(disk.keys()); }
            catch (IOException ex) { error = "Terrain cache write failed: " + ex.getMessage(); }
        }
    }
    public void request(Request request) {
        latest.set(request);
        if (closed || !planning.compareAndSet(false, true)) return;
        if (!submit(this::plan)) planning.set(false);
    }
    private void plan() {
        try {
            Request r = latest.get();
            if (r == null || closed) return;
            if (!residencyAnchored || residencyX != r.x || residencyZ != r.z) {
                deferred.clear(); residencyX = r.x; residencyZ = r.z; residencyAnchored = true;
            }
            if (disk == null && r.options.terrainCache() && r.options.backgroundUpdates()) {
                try { disk = openCache(); cached = new HashSet<>(disk.keys()); }
                catch (IOException ex) { error = "Terrain cache unavailable: " + ex.getMessage(); }
            }
            if (disk != null && r.options.terrainCache() && r.options.backgroundUpdates() && !cached.isEmpty()) {
                List<Long> nearest = cached.stream().filter(k -> !chunks.containsKey(k) && !deferred.contains(k)).filter(k -> {
                    double dx = (double)Terrain.x(k) * 16 - r.x, dz = (double)Terrain.z(k) * 16 - r.z;
                    return dx * dx + dz * dz <= Math.pow(r.options.distance() * 16.0, 2);
                }).sorted(Comparator.comparingDouble(k -> Math.pow((double)Terrain.x(k) * 16 - r.x, 2)
                        + Math.pow((double)Terrain.z(k) * 16 - r.z, 2))).limit(4).toList();
                for (long key : nearest) {
                    try { Terrain.Chunk chunk = disk.read(key); if (chunk != null) acceptCached(chunk); else cached.remove(key); }
                    catch (IOException ex) { cached.remove(key); error = ex.getMessage(); }
                    if (closed) return;
                }
            }
            if (r.equals(planned) && revision == plannedRevision) return;
            List<Terrain.Chunk> snapshot = List.copyOf(chunks.values());
            List<TilePlan.Key> keys = TilePlan.select(snapshot, r.x, r.z, r.near, r.options.distance(), r.options.detail());
            List<PackedMesh> out = new ArrayList<>(); long bytes = 0; boolean limited = false, waiting = false;
            for (var key : keys) {
                if (closed || !r.equals(latest.get())) return;
                long stamp = stamps.getOrDefault(key, 0L);
                PackedMesh packed = meshes.get(key);
                if (packed == null || packed.stamp() != stamp || packed.gpu() != r.gpu) {
                    TileMesh mesh;
                    try { mesh = TileMesh.build(key, TilePlan.grid(key, snapshot), 32768); }
                    catch (TileMesh.BudgetExceeded ex) { limited = true; continue; }
                    packed = PackedMesh.pack(mesh, r.gpu, catalog, stamp, LodOptions.CPU_LIMIT / 4 - bytes);
                    if (packed == null) { waiting = true; continue; }
                }
                if (bytes + packed.bytes() > LodOptions.CPU_LIMIT / 4) { limited = true; break; }
                out.add(packed); bytes += packed.bytes();
            }
            // Preserve an existing tile while its replacement waits on material preparation.
            if (waiting && !frame.meshes.isEmpty()) {
                frame = new Frame(generation, frame.meshes(), "Preparing replacement materials; previous coverage retained", frame.cpuBytes());
                return;
            }
            meshes.clear(); for (PackedMesh packed : out) meshes.put(packed.key(), packed);
            String status = limited ? "CPU terrain budget reached; nearest tiles kept" : waiting ? "Preparing cached terrain materials"
                    : chunks.isEmpty() ? "Waiting for explored terrain" : out.size() + " LOD tiles · " + (chunkBytes + bytes) / (1 << 20) + " MiB CPU";
            if (!error.isEmpty()) status += " · " + error;
            if (!deferred.isEmpty()) status += " · CPU summary budget reached; nearest terrain retained";
            frame = new Frame(generation, out, status, chunkBytes + bytes);
            planned = r; plannedRevision = revision;
            if (stamps.size() > 65536) { stamps.keySet().retainAll(meshes.keySet()); }
        } catch (RuntimeException ex) {
            frame = new Frame(generation, frame.meshes, "LOD terrain work failed: " + ex.getMessage(), frame.cpuBytes);
            LodClient.LOG.warn("LOD terrain work failed", ex);
        } finally { planning.set(false); }
    }
    private void acceptCached(Terrain.Chunk chunk) {
        DiskCache saved = disk; disk = null;
        try { accept(chunk.withRevision(0)); } finally { disk = saved; }
    }
    public void clearCache() {
        submit(() -> {
            try { if (disk == null) disk = openCache(); disk.clear(); cached.clear(); deferred.clear(); chunks.clear(); meshes.clear(); stamps.clear(); chunkBytes = 0; revision++;
                frame = new Frame(generation, List.of(), "Cache cleared; exploring builds new terrain", 0); }
            catch (IOException ex) { error = "Could not clear terrain cache: " + ex.getMessage(); }
        });
    }
    public void close() { closed = true; executor.shutdownNow(); }
}
