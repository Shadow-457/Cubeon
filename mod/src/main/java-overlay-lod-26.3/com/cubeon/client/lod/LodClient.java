package com.cubeon.client.lod;

import com.cubeon.client.lod.core.Terrain;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.world.level.chunk.status.ChunkStatus;
import org.slf4j.*;

/** Optional 26.3 subsystem. Disabled events return before touching worlds, files or executors. */
public final class LodClient implements ClientModInitializer {
    public static final Logger LOG = LoggerFactory.getLogger("CubeonLOD");
    private static LodOptions options;
    private static volatile boolean enabled, reset;
    private static boolean sodium, iris, otherLod;
    private static Object level;
    private static TextureCatalog textures;
    private static TerrainWorker worker;
    private static long generation, revision;
    private static final LinkedHashMap<Long, Long> dirty = new LinkedHashMap<>();
    private static final Map<Long, Long> captured = new HashMap<>();
    private static ChunkSnapshot snapshot;
    private static int scan, scanX = Integer.MIN_VALUE, scanZ = Integer.MIN_VALUE, scanRadius;
    private static String status = "LOD is off";
    public void onInitializeClient() {
        var loader = FabricLoader.getInstance();
        sodium = loader.isModLoaded("sodium"); iris = loader.isModLoaded("iris");
        otherLod = loader.isModLoaded("distanthorizons") || loader.isModLoaded("voxy");
        options = new LodOptions(loader.getConfigDir().resolve("cubeon-client-lod.json"));
        options.load(); enabled = sodium && options.active().enabled();
    }
    public static LodOptions options() {
        if (options == null) new LodClient().onInitializeClient();
        return options;
    }
    public static boolean enabled() { return enabled; }
    public static void applied() {
        enabled = sodium && options().active().enabled();
        if (!options().active().backgroundUpdates()) { snapshot = null; dirty.clear(); }
    }
    public static String status() {
        if (!options().error().isEmpty()) return options().error();
        if (!options().active().enabled()) return "LOD is off";
        if (!sodium) return "LOD requires Sodium";
        return status + (worker == null ? "" : " · " + worker.frame().status());
    }
    public static void dirty(int x, int z) {
        if (!enabled || !options.active().backgroundUpdates()) return;
        long key = Terrain.key(x, z);
        dirty.put(key, ++revision);
        while (dirty.size() > 1024) dirty.remove(dirty.keySet().iterator().next());
    }
    public static void reload() { if (enabled) reset = true; }
    public static void tick() {
        if (!enabled) { if (worker != null) stop(); return; }
        var mc = Minecraft.getInstance(); var value = options.active();
        if (mc.level == null || otherLod) {
            status = otherLod ? "Paused: another LOD renderer is active" : "Enter a world to build explored terrain";
            if (worker != null) stop(); return;
        }
        if (iris && !IrisAdapter.allowed(value)) { status = IrisAdapter.reason(); if (worker != null) stop(); return; }
        if (level != mc.level || reset) {
            stop(); reset = false; level = mc.level; textures = new TextureCatalog();
            CacheIdentity identity = CacheIdentity.capture(mc);
            worker = new TerrainWorker(++generation, mc.gameDirectory.toPath().resolve("cubeon-lod"), identity, textures, value.terrainCache());
        }
        int near = mc.options.renderDistance().get();
        boolean gpu = LodRenderer.gpu(value.processing());
        status = (gpu ? "GPU geometry" : "CPU geometry") + LodRenderer.reason();
        if (value.distance() <= near) { status = "LOD distance is inside full-detail range; no additional terrain needed"; return; }
        int cx = mc.player == null ? 0 : mc.player.chunkPosition().x(), cz = mc.player == null ? 0 : mc.player.chunkPosition().z();
        worker.request(new TerrainWorker.Request(cx * 16 + 8, cz * 16 + 8, near, value, gpu, textures.revision()));
        if (!value.backgroundUpdates()) { status += " · Background updates paused"; return; }
        long deadline = System.nanoTime() + 500_000;
        textures.drain(deadline);
        int radius = Math.min(64, near + 2);
        if (cx != scanX || cz != scanZ || radius != scanRadius) { scanX = cx; scanZ = cz; scanRadius = radius; scan = 0; }
        // Enabling LOD mid-session discovers already loaded chunks without requesting any new ones.
        int side = radius * 2 + 1;
        for (int count = 0; count < 16 && scan < side * side && System.nanoTime() < deadline; count++, scan++) {
            int x = cx - radius + scan % side, z = cz - radius + scan / side;
            long key = Terrain.key(x, z);
            if (!captured.containsKey(key) && mc.level.getChunkSource().getChunk(x, z, ChunkStatus.FULL, false) != null) dirty(x, z);
        }
        if (snapshot == null && worker.pending() < 8 && !dirty.isEmpty()) {
            long key = dirty.keySet().iterator().next();
            var chunk = mc.level.getChunkSource().getChunk(Terrain.x(key), Terrain.z(key), ChunkStatus.FULL, false);
            long rev = dirty.remove(key);
            if (chunk != null) snapshot = new ChunkSnapshot(chunk, rev);
        }
        while (snapshot != null && System.nanoTime() < deadline) {
            if (snapshot.step(textures)) {
                ChunkSnapshot finished = snapshot; snapshot = null;
                long key = Terrain.key(finished.chunk.getPos().x(), finished.chunk.getPos().z());
                TerrainWorker owner = worker;
                if (!dirty.containsKey(key) && owner.submit(() -> owner.accept(finished.summarize()))) captured.put(key, finished.revision);
                else dirty(Terrain.x(key), Terrain.z(key));
                break;
            }
        }
        if (captured.size() > 16384) captured.clear();
        worker.request(new TerrainWorker.Request(cx * 16 + 8, cz * 16 + 8, near, value, gpu, textures.revision()));
    }
    public static TerrainWorker.Frame frame() { return worker == null ? null : worker.frame(); }
    private static final java.util.concurrent.ExecutorService CACHE_ACTIONS = java.util.concurrent.Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "cubeon-lod-cache-action"); t.setDaemon(true); return t;
    });
    private static boolean clearing;
    public static void clearCache() {
        if (worker != null) { worker.clearCache(); captured.clear(); scan = 0; return; }
        var mc = Minecraft.getInstance();
        if (mc.level == null) { status = "Enter a world to clear its terrain cache"; return; }
        if (clearing) return;
        clearing = true;
        CacheIdentity identity = CacheIdentity.capture(mc); Path root = mc.gameDirectory.toPath().resolve("cubeon-lod");
        CACHE_ACTIONS.execute(() -> {
            try { new com.cubeon.client.lod.core.DiskCache(root, identity.fingerprint()).clear(); status = "Current terrain cache cleared"; }
            catch (java.io.IOException ex) { status = "Could not clear terrain cache: " + ex.getMessage(); }
            finally { clearing = false; }
        });
    }
    public static void stop() {
        if (worker != null) worker.close(); worker = null; level = null; snapshot = null;
        dirty.clear(); captured.clear(); scanX = Integer.MIN_VALUE; reset = true;
        LodRenderer.requestReset();
    }
}
