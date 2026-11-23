package com.cubeon.client.skins;

import com.cubeon.client.Json;

import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;

/**
 * Bounded native fallback for Cubeon player skins.
 *
 * <p>CustomSkinLoader remains the offline/local source, but peer visibility no
 * longer depends on another mod successfully replacing Minecraft's skin
 * service. Lookups and PNG reads happen on two daemon workers; render calls
 * only inspect immutable cached values and enqueue bounded work.
 */
public final class RemoteSkins {
    private static final String BASE = "https://cubeon-skins.hamza-457-shahbaz.workers.dev";
    private static final long TTL = TimeUnit.MINUTES.toNanos(5);
    private static final long MISSING_TTL = TimeUnit.MINUTES.toNanos(15);
    private static final int MAX_PROFILE_BYTES = 4096;
    private static final int MAX_SKIN_BYTES = 24 * 1024;
    private static LongSupplier clock = System::nanoTime;
    private static long retryAt;
    private static int failures;
    private static long budgetTime;
    private static double requestTokens = 40;
    private static final ThreadPoolExecutor WORKERS = new ThreadPoolExecutor(2, 2, 10,
            TimeUnit.SECONDS, new ArrayBlockingQueue<>(64), job -> {
                Thread thread = new Thread(job, "cubeon-peer-skins");
                thread.setDaemon(true);
                return thread;
            });
    public record Skin(byte[] png, boolean slim, String id) { }
    private record Entry(Skin skin, boolean cubeonPlayer, long expires, boolean pending) { }
    private static final LinkedHashMap<String, Entry> CACHE = new LinkedHashMap<>(128, .75f, true);
    private static Object world;
    private static long generation;
    static { WORKERS.allowCoreThreadTimeOut(true); }
    private RemoteSkins() { }

    /** Retires queued work from an old world without discarding completed skins. */
    public static synchronized void context(Object currentWorld) {
        if (world != currentWorld) {
            world = currentWorld;
            generation++;
            CACHE.entrySet().removeIf(entry -> entry.getValue().pending);
            WORKERS.getQueue().clear();
        }
    }

    /**
     * A published Cubeon profile, including cape-only/default-skin players.
     * Shares the skin lookup's workers, cache and request budget; never waits
     * for HTTP. A skin texture failure does not erase a confirmed identity.
     */
    public static synchronized boolean isCubeonPlayer(String username) {
        if (world == null || username == null || !username.matches("[A-Za-z0-9_]{3,16}")) return false;
        get(username);
        Entry entry = CACHE.get(username.toLowerCase(Locale.ROOT));
        return entry != null && entry.cubeonPlayer;
    }

    /** Cached skin or {@code null}; a miss queues one non-blocking lookup. */
    public static synchronized Skin get(String username) {
        if (world == null || username == null || !username.matches("[A-Za-z0-9_]{3,16}")) return null;
        String key = username.toLowerCase(Locale.ROOT);
        long now = clock.getAsLong();
        Entry found = CACHE.get(key);
        if (found != null && (found.pending || now < found.expires)) return found.skin;
        if (now < retryAt) return found == null ? null : found.skin;
        if (budgetTime != 0) requestTokens = Math.min(40,
                requestTokens + Math.max(0, now - budgetTime) / 1_500_000_000.0);
        budgetTime = now;
        if (requestTokens < 1) return found == null ? null : found.skin;
        requestTokens--;
        if (found == null && CACHE.size() >= 128) {
            var iterator = CACHE.entrySet().iterator();
            boolean removed = false;
            while (iterator.hasNext()) {
                if (!iterator.next().getValue().pending) { iterator.remove(); removed = true; break; }
            }
            if (!removed) return null;
        }
        Skin previous = found == null ? null : found.skin;
        boolean previousIdentity = found != null && found.cubeonPlayer;
        CACHE.put(key, new Entry(previous, previousIdentity, now + TTL, true));
        long requestGeneration = generation;
        try { WORKERS.execute(() -> fetch(key, requestGeneration)); }
        catch (java.util.concurrent.RejectedExecutionException full) {
            CACHE.put(key, new Entry(previous, previousIdentity, now + TimeUnit.MINUTES.toNanos(1), false));
        }
        return previous;
    }

    private static void fetch(String key, long requestGeneration) {
        synchronized (RemoteSkins.class) {
            if (generation != requestGeneration || clock.getAsLong() < retryAt) {
                if (generation == requestGeneration && CACHE.containsKey(key)) {
                    Entry entry = CACHE.get(key);
                    CACHE.put(key, new Entry(entry.skin, entry.cubeonPlayer, retryAt, false));
                }
                return;
            }
        }
        Skin skin = null;
        boolean cubeonPlayer = false;
        long ttl = TTL;
        boolean failed = true, answered = false;
        long serverDelay = 0;
        HttpURLConnection profile = null;
        HttpURLConnection texture = null;
        try {
            profile = open(BASE + "/skins/" + key + ".json");
            int status = profile.getResponseCode();
            if (status == 200) {
                byte[] bytes;
                try (var stream = profile.getInputStream()) {
                    bytes = stream.readNBytes(MAX_PROFILE_BYTES + 1);
                }
                if (bytes.length <= MAX_PROFILE_BYTES) {
                    Map<String, Object> root = Json.parseObject(new String(bytes, StandardCharsets.UTF_8));
                    Object texturesValue = root.get("textures");
                    Map<?, ?> textures = texturesValue instanceof Map<?, ?> map ? map : Map.of();
                    cubeonPlayer = key.equalsIgnoreCase(Json.str(root, "username", ""))
                            && (textureId(textures.get("cape")) != null
                            || textureId(textures.get("slim")) != null
                            || textureId(textures.get("default")) != null);
                    if (!cubeonPlayer) throw new IllegalArgumentException("Invalid Cubeon profile");
                    String id = textureId(textures.get("slim"));
                    boolean slim = id != null;
                    if (id == null) id = textureId(textures.get("default"));
                    if (id == null) {
                        failed = false; answered = true;
                    } else {
                        texture = open(BASE + "/skins/textures/" + id);
                        int textureStatus = texture.getResponseCode();
                        if (textureStatus == 200) {
                            byte[] png;
                            try (var stream = texture.getInputStream()) {
                                png = stream.readNBytes(MAX_SKIN_BYTES + 1);
                            }
                            if (png.length <= MAX_SKIN_BYTES && isSkinPng(png)) {
                                skin = new Skin(png, slim, id);
                                failed = false; answered = true;
                            }
                        } else if (textureStatus == 404 || textureStatus == 403) {
                            failed = false; answered = true; ttl = MISSING_TTL;
                        } else serverDelay = retryAfter(texture);
                    }
                }
            } else if (status == 404 || status == 403) {
                failed = false; answered = true; ttl = MISSING_TTL;
            } else serverDelay = retryAfter(profile);
        } catch (Exception ignored) {
            // A failed fallback leaves Minecraft/CSL's current texture intact.
        } finally {
            if (texture != null) texture.disconnect();
            if (profile != null) profile.disconnect();
        }
        synchronized (RemoteSkins.class) {
            if (generation != requestGeneration) return;
            long now = clock.getAsLong();
            if (failed) {
                failures = Math.min(5, failures + 1);
                ttl = Math.max(TimeUnit.SECONDS.toNanos(60L << (failures - 1)), serverDelay);
                retryAt = Math.max(retryAt, now + ttl);
            } else if (answered && now >= retryAt) failures = 0;
            Entry entry = CACHE.get(key);
            if (entry != null)
                CACHE.put(key, new Entry(failed ? entry.skin : skin,
                        cubeonPlayer || (failed && entry.cubeonPlayer), now + ttl, false));
        }
    }

    private static HttpURLConnection open(String url) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) URI.create(url).toURL().openConnection();
        connection.setConnectTimeout(3000);
        connection.setReadTimeout(3000);
        connection.setInstanceFollowRedirects(false);
        return connection;
    }

    private static String textureId(Object value) {
        if (!(value instanceof String text) || !text.matches("[a-f0-9]{64}")) return null;
        return text;
    }

    private static long retryAfter(HttpURLConnection connection) {
        try {
            String value = connection.getHeaderField("Retry-After");
            long seconds;
            try { seconds = Long.parseLong(value); }
            catch (NumberFormatException numeric) {
                seconds = java.time.ZonedDateTime.parse(value,
                        java.time.format.DateTimeFormatter.RFC_1123_DATE_TIME).toEpochSecond()
                        - java.time.Instant.now().getEpochSecond();
            }
            return TimeUnit.SECONDS.toNanos(Math.min(86400, Math.max(0, seconds)));
        } catch (Exception ignored) { return 0; }
    }

    private static boolean isSkinPng(byte[] bytes) {
        if (bytes == null || bytes.length < 24) return false;
        int[] signature = {0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a};
        for (int i = 0; i < signature.length; i++) if ((bytes[i] & 255) != signature[i]) return false;
        int width = readInt(bytes, 16), height = readInt(bytes, 20);
        return width == 64 && (height == 64 || height == 32);
    }

    private static int readInt(byte[] bytes, int offset) {
        return (bytes[offset] & 255) << 24 | (bytes[offset + 1] & 255) << 16
                | (bytes[offset + 2] & 255) << 8 | bytes[offset + 3] & 255;
    }
}
