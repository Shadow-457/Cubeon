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
import java.util.function.LongSupplier;

/** Bounded, read-only peer lookup. Network and parsing never run on the render thread. */
public final class RemoteCosmetics {
    private static final String BASE = "https://cubeon-skins.hamza-457-shahbaz.workers.dev";
    private static final long TTL = TimeUnit.MINUTES.toNanos(5);
    private static final long MISSING_TTL = TimeUnit.MINUTES.toNanos(15);
    private static LongSupplier clock = System::nanoTime;
    private static long retryAt;
    private static int failures;
    private static long budgetTime;
    private static double requestTokens = 40;
    private static final CosmeticSelection.Items EMPTY = new CosmeticSelection.Items(null, null);
    private static final ThreadPoolExecutor WORKERS = new ThreadPoolExecutor(2, 2, 10,
            TimeUnit.SECONDS, new ArrayBlockingQueue<>(64), job -> {
                Thread thread = new Thread(job, "cubeon-peer-cosmetics");
                thread.setDaemon(true); return thread;
            });
    private record Entry(CosmeticSelection.Items items, long expires, boolean pending) { }
    private static final LinkedHashMap<String, Entry> CACHE = new LinkedHashMap<>(128, .75f, true);
    private static Object world;
    private static boolean enabled;
    private static long generation;
    static { WORKERS.allowCoreThreadTimeOut(true); }
    private RemoteCosmetics() { }

    public static synchronized void context(Object currentWorld, boolean show) {
        if (world != currentWorld || enabled != show) {
            world = currentWorld; enabled = show; generation++;
            CACHE.entrySet().removeIf(entry -> entry.getValue().pending);
            WORKERS.getQueue().clear();
        }
    }

    /** Null slots while loading, absent, invalid, disabled or offline. */
    public static synchronized CosmeticSelection.Items get(String username) {
        if (!enabled || world == null || username == null || !username.matches("[A-Za-z0-9_]{3,16}")) return EMPTY;
        String key = username.toLowerCase(Locale.ROOT);
        long now = clock.getAsLong();
        Entry found = CACHE.get(key);
        if (found != null && (found.pending || now < found.expires)) return found.items;
        if (now < retryAt) return found == null ? EMPTY : found.items;
        if (budgetTime != 0) requestTokens = Math.min(40,
                requestTokens + Math.max(0, now - budgetTime) / 1_500_000_000.0);
        budgetTime = now;
        if (requestTokens < 1) return found == null ? EMPTY : found.items;
        requestTokens--;
        if (found == null && CACHE.size() >= 128) {
            var iterator = CACHE.entrySet().iterator();
            boolean removed = false;
            while (iterator.hasNext()) {
                if (!iterator.next().getValue().pending) { iterator.remove(); removed = true; break; }
            }
            if (!removed) return EMPTY;
        }
        CosmeticSelection.Items previous = found == null ? EMPTY : found.items;
        CACHE.put(key, new Entry(previous, now + TTL, true));
        long requestGeneration = generation;
        try { WORKERS.execute(() -> fetch(key, requestGeneration)); }
        catch (java.util.concurrent.RejectedExecutionException full) {
            CACHE.put(key, new Entry(previous, now + TimeUnit.MINUTES.toNanos(1), false));
        }
        return previous;
    }

    private static void fetch(String key, long requestGeneration) {
        synchronized (RemoteCosmetics.class) {
            if (generation != requestGeneration || clock.getAsLong() < retryAt) {
                if (generation == requestGeneration && CACHE.containsKey(key)) {
                    Entry entry = CACHE.get(key);
                    CACHE.put(key, new Entry(entry.items, retryAt, false));
                }
                return;
            }
        }
        CosmeticSelection.Items items = EMPTY;
        long ttl = TTL;
        boolean failed = true, answered = false;
        long serverDelay = 0;
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) URI.create(BASE + "/cosmetics/" + key + ".json").toURL().openConnection();
            connection.setConnectTimeout(3000); connection.setReadTimeout(3000);
            connection.setInstanceFollowRedirects(false);
            int status = connection.getResponseCode();
            if (status == 200) {
                try (var stream = connection.getInputStream()) {
                    byte[] bytes = stream.readNBytes(4097);
                    if (bytes.length <= 4096) {
                        items = CosmeticSelection.Items.parse(Json.parseObject(new String(bytes, StandardCharsets.UTF_8)));
                        failed = false; answered = true;
                        if (items.back() == null && items.shoulder() == null) ttl = MISSING_TTL;
                    }
                }
            } else if (status == 404 || status == 403) {
                failed = false; answered = true; ttl = MISSING_TTL;
            } else {
                try {
                    String value = connection.getHeaderField("Retry-After");
                    long seconds;
                    try { seconds = Long.parseLong(value); }
                    catch (NumberFormatException numeric) {
                        seconds = java.time.ZonedDateTime.parse(value,
                                java.time.format.DateTimeFormatter.RFC_1123_DATE_TIME).toEpochSecond()
                                - java.time.Instant.now().getEpochSecond();
                    }
                    serverDelay = TimeUnit.SECONDS.toNanos(Math.min(86400, Math.max(0, seconds)));
                } catch (Exception ignored) { }
            }
        } catch (Exception ignored) {
            // An outage costs peer decorations only; negative results also get a cooldown.
        } finally { if (connection != null) connection.disconnect(); }
        synchronized (RemoteCosmetics.class) {
            if (generation != requestGeneration) return;
            long now = clock.getAsLong();
            if (failed) {
                failures = Math.min(5, failures + 1);
                ttl = Math.max(TimeUnit.SECONDS.toNanos(60L << (failures - 1)), serverDelay);
                retryAt = Math.max(retryAt, now + ttl);
            } else if (answered && now >= retryAt) failures = 0;
            Entry entry = CACHE.get(key);
            if (entry != null)
                CACHE.put(key, new Entry(failed ? entry.items : items, now + ttl, false));
        }
    }
}
