package com.cubeon.client.skins;

import com.cubeon.client.Json;

import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.io.ByteArrayOutputStream;
import java.awt.image.BufferedImage;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;

/**
 * Bounded native fallback: Cubeon, TLauncher, Ely.by, then Mojang.
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
    private enum Source { CUBEON, TLAUNCHER, ELYBY, MOJANG }
    private static final long[] retryAt = new long[Source.values().length];
    private static final int[] failures = new int[Source.values().length];
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
        Skin skin = null;
        boolean cubeonPlayer = false;
        boolean failed = false;
        for (Source source : Source.values()) {
            int index = source.ordinal();
            synchronized (RemoteSkins.class) {
                if (generation != requestGeneration) return;
                if (clock.getAsLong() < retryAt[index]) {
                    failed = true;
                    if (source == Source.CUBEON) {
                        Entry previous = CACHE.get(key);
                        cubeonPlayer = previous != null && previous.cubeonPlayer;
                    }
                    continue;
                }
            }
            try {
                if (source == Source.CUBEON) {
                    Map<String, Object> root = object(BASE + "/skins/" + key + ".json");
                    if (root != null) {
                        Map<?, ?> textures = map(root.get("textures"));
                        cubeonPlayer = key.equalsIgnoreCase(Json.str(root, "username", ""))
                                && (textureId(textures.get("cape")) != null
                                || textureId(textures.get("slim")) != null
                                || textureId(textures.get("default")) != null);
                        if (!cubeonPlayer) throw new IllegalArgumentException("Invalid Cubeon profile");
                        String id = textureId(textures.get("slim"));
                        boolean slim = id != null;
                        if (id == null) id = textureId(textures.get("default"));
                        if (id != null) skin = download(BASE + "/skins/textures/" + id, slim);
                    }
                } else if (source == Source.MOJANG) {
                    Map<String, Object> account = object("https://api.mojang.com/users/profiles/minecraft/" + key);
                    if (account != null) {
                        String id = Json.str(account, "id", "");
                        if (!id.matches("[a-fA-F0-9]{32}") || !key.equalsIgnoreCase(Json.str(account, "name", "")))
                            throw new IllegalArgumentException("Invalid Mojang account");
                        Map<String, Object> profile = object("https://sessionserver.mojang.com/session/minecraft/profile/" + id);
                        if (profile != null) {
                            if (!id.equalsIgnoreCase(Json.str(profile, "id", "")))
                                throw new IllegalArgumentException("Mojang UUID mismatch");
                            Object properties = profile.get("properties");
                            if (properties instanceof java.util.List<?> list) for (Object item : list) {
                                Map<?, ?> property = map(item);
                                if (!"textures".equals(property.get("name"))) continue;
                                Object value = property.get("value");
                                if (!(value instanceof String encoded) || encoded.length() > MAX_PROFILE_BYTES)
                                    throw new IllegalArgumentException("Invalid Mojang textures");
                                Map<String, Object> decoded = Json.parseObject(new String(Base64.getDecoder().decode(encoded), StandardCharsets.UTF_8));
                                skin = texture(map(decoded.get("textures")));
                                break;
                            }
                        }
                    }
                } else {
                    String root = source == Source.TLAUNCHER
                            ? "https://auth.tlauncher.org/skin/profile/texture/login/"
                            : "https://skinsystem.ely.by/textures/";
                    Map<String, Object> profile = object(root + key);
                    if (profile != null) skin = texture(profile);
                }
                synchronized (RemoteSkins.class) { failures[index] = 0; }
            } catch (Exception error) {
                failed = true;
                synchronized (RemoteSkins.class) {
                    failures[index] = Math.min(5, failures[index] + 1);
                    long delay = TimeUnit.SECONDS.toNanos(60L << (failures[index] - 1));
                    if (error instanceof Unavailable unavailable) delay = Math.max(delay, unavailable.delay);
                    retryAt[index] = Math.max(retryAt[index], clock.getAsLong() + delay);
                    if (source == Source.CUBEON) {
                        Entry previous = CACHE.get(key);
                        cubeonPlayer |= previous != null && previous.cubeonPlayer;
                    }
                }
            }
            if (skin != null) break;
        }
        synchronized (RemoteSkins.class) {
            if (generation != requestGeneration) return;
            long now = clock.getAsLong();
            long ttl = failed && skin == null ? TimeUnit.MINUTES.toNanos(1)
                    : skin != null || cubeonPlayer ? TTL : MISSING_TTL;
            Entry entry = CACHE.get(key);
            if (entry != null)
                CACHE.put(key, new Entry(skin == null && failed ? entry.skin : skin,
                        cubeonPlayer, now + ttl, false));
        }
    }

    private static Map<?, ?> map(Object value) { return value instanceof Map<?, ?> result ? result : Map.of(); }

    private static Map<String, Object> object(String url) throws Exception {
        byte[] bytes = request(url, MAX_PROFILE_BYTES);
        if (bytes == null) return null;
        Object value = Json.parse(new String(bytes, StandardCharsets.UTF_8));
        if (!(value instanceof Map<?, ?>)) throw new IllegalArgumentException("Invalid skin profile");
        return Json.parseObject(new String(bytes, StandardCharsets.UTF_8));
    }

    private static Skin texture(Map<?, ?> textures) throws Exception {
        Map<?, ?> skin = map(textures.get("SKIN"));
        Object value = skin.get("url");
        if (value == null) return null;
        if (!(value instanceof String url)) throw new IllegalArgumentException("Invalid skin URL");
        URI uri = URI.create(url);
        if (uri.getHost() == null || uri.getUserInfo() != null
                || !("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme())))
            throw new IllegalArgumentException("Invalid skin URL");
        // These services publish HTTP texture URLs too; their texture hosts
        // support HTTPS, so no plaintext fetch is needed for the native path.
        if ("http".equalsIgnoreCase(uri.getScheme())) url = "https" + url.substring(4);
        return download(url, "slim".equals(map(skin.get("metadata")).get("model")));
    }

    private static Skin download(String url, boolean slim) throws Exception {
        byte[] png = request(url, MAX_SKIN_BYTES);
        if (png == null) return null;
        if (!isSkinPng(png)) throw new IllegalArgumentException("Invalid skin PNG");
        boolean legacy = readInt(png, 20) == 32;
        png = normalize(png);
        String id = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(png));
        return new Skin(png, slim && !legacy, id);
    }

    private static final class Unavailable extends Exception {
        private static final long serialVersionUID = 1L;
        private final long delay;
        private Unavailable(long delay) { this.delay = delay; }
    }

    private static byte[] request(String url, int limit) throws Exception {
        HttpURLConnection connection = open(url);
        try {
            int status = connection.getResponseCode();
            if (status == 204 || status == 404 || status == 403) return null;
            if (status != 200) throw new Unavailable(retryAfter(connection));
            try (var stream = connection.getInputStream()) {
                byte[] bytes = stream.readNBytes(limit + 1);
                if (bytes.length > limit) throw new IllegalArgumentException("Skin response is too large");
                return bytes;
            }
        } finally { connection.disconnect(); }
    }

    /** Vanilla's legacy limb mirror and opaque base layers, decoded off-thread. */
    private static byte[] normalize(byte[] png) throws Exception {
        BufferedImage original = CapeFrames.decodePng(png, true);
        BufferedImage image = new BufferedImage(64, 64, BufferedImage.TYPE_INT_ARGB);
        image.setRGB(0, 0, 64, original.getHeight(), original.getRGB(0, 0, 64, original.getHeight(), null, 0, 64), 0, 64);
        if (original.getHeight() == 32) {
            int[][] copies = {{4,16,20,48,4,4},{8,16,24,48,4,4},{0,20,24,52,4,12},
                    {4,20,20,52,4,12},{8,20,16,52,4,12},{12,20,28,52,4,12},
                    {44,16,36,48,4,4},{48,16,40,48,4,4},{40,20,40,52,4,12},
                    {44,20,36,52,4,12},{48,20,32,52,4,12},{52,20,44,52,4,12}};
            for (int[] r : copies) for (int y=0;y<r[5];y++) for (int x=0;x<r[4];x++)
                image.setRGB(r[2]+x,r[3]+y,original.getRGB(r[0]+r[4]-1-x,r[1]+y));
            boolean opaque = true;
            for (int y=0;y<32;y++) for (int x=32;x<64;x++) if ((image.getRGB(x,y) >>> 24) < 128) opaque = false;
            if (opaque) for (int y=0;y<32;y++) for (int x=32;x<64;x++) image.setRGB(x,y,image.getRGB(x,y)&0xffffff);
        }
        for (int[] r : new int[][]{{0,0,32,16},{0,16,64,32},{16,48,48,64}})
            for (int y=r[1];y<r[3];y++) for (int x=r[0];x<r[2];x++) image.setRGB(x,y,image.getRGB(x,y)|0xff000000);
        var bytes = new ByteArrayOutputStream();
        javax.imageio.ImageIO.write(image, "PNG", bytes);
        return bytes.toByteArray();
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
