package com.cubeon.client.cosmetics;

import com.cubeon.client.Json;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Bounded, read-only peer lookup. Network and parsing never run on the render thread. */
public final class RemoteCosmetics {
    private static final String BASE = "https://cubeon-skins.hamza-457-shahbaz.workers.dev";
    private static final long TTL = 60_000_000_000L;
    private static final CosmeticSelection.Items EMPTY = new CosmeticSelection.Items(null, null);
    private static final ThreadPoolExecutor WORKERS = new ThreadPoolExecutor(2, 2, 10,
            TimeUnit.SECONDS, new ArrayBlockingQueue<>(64), job -> {
                Thread thread = new Thread(job, "cubeon-peer-cosmetics");
                thread.setDaemon(true); return thread;
            });
    private record Entry(CosmeticSelection.Items items, long expires, boolean pending) { }
    private static final LinkedHashMap<String, Entry> CACHE = new LinkedHashMap<>();
    private static Object world;
    private static boolean enabled;
    private static long generation;
    static { WORKERS.allowCoreThreadTimeOut(true); }
    private RemoteCosmetics() { }

    public static synchronized void context(Object currentWorld, boolean show) {
        if (world != currentWorld || enabled != show) {
            world = currentWorld; enabled = show; generation++; CACHE.clear(); WORKERS.getQueue().clear();
        }
    }

    /** Null slots while loading, absent, invalid, disabled or offline. */
    public static synchronized CosmeticSelection.Items get(String username) {
        if (!enabled || world == null || username == null || !username.matches("[A-Za-z0-9_]{3,16}")) return EMPTY;
        String key = username.toLowerCase(Locale.ROOT);
        long now = System.nanoTime();
        Entry found = CACHE.get(key);
        if (found != null && (found.pending || now < found.expires)) return found.items;
        if (CACHE.size() >= 128) {
            var iterator = CACHE.entrySet().iterator(); iterator.next(); iterator.remove();
        }
        CACHE.put(key, new Entry(EMPTY, now + TTL, true));
        long requestGeneration = generation;
        try { WORKERS.execute(() -> fetch(key, requestGeneration)); }
        catch (java.util.concurrent.RejectedExecutionException full) {
            CACHE.put(key, new Entry(EMPTY, now + TTL, false));
        }
        return EMPTY;
    }

    private static void fetch(String key, long requestGeneration) {
        CosmeticSelection.Items items = EMPTY;
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) URI.create(BASE + "/cosmetics/" + key + ".json").toURL().openConnection();
            connection.setConnectTimeout(3000); connection.setReadTimeout(3000);
            connection.setInstanceFollowRedirects(false);
            if (connection.getResponseCode() == 200) {
                try (var stream = connection.getInputStream()) {
                    byte[] bytes = stream.readNBytes(4097);
                    if (bytes.length <= 4096) items = CosmeticSelection.Items.parse(
                            Json.parseObject(new String(bytes, StandardCharsets.UTF_8)));
                }
            }
        } catch (Exception ignored) {
            // An outage costs peer decorations only; negative results also get a cooldown.
        } finally { if (connection != null) connection.disconnect(); }
        synchronized (RemoteCosmetics.class) {
            if (generation == requestGeneration && CACHE.containsKey(key))
                CACHE.put(key, new Entry(items, System.nanoTime() + TTL, false));
        }
    }
}
