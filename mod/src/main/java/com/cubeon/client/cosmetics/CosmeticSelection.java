package com.cubeon.client.cosmetics;

import com.cubeon.client.Json;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

/**
 * Which cosmetics the local player has selected.
 *
 * <p>The launcher owns this file ({@code <game>/config/cubeon-cosmetics.json});
 * the mod only reads it. Writing it from both processes would be a race, and a
 * cosmetic is not worth a lock file. The launcher rewrites it atomically.
 * One daemon reads changes; rendering consumes an immutable snapshot and
 * never waits for filesystem access or JSON parsing.
 *
 * <p>Unknown ids are ignored, not errors: an older mod jar paired with a newer
 * launcher must degrade to "no cosmetic", never to a missing texture or a
 * crash. A malformed or unreadable file means "nothing selected".
 *
 * <p>Minecraft-free: the overlay passes the config path in, which also makes
 * this testable without a game.
 */
public final class CosmeticSelection {

    /** The launcher's file name inside {@code config/}. */
    public static final String FILE_NAME = "cubeon-cosmetics.json";

    private static final long CHECK_INTERVAL_NANOS = 250_000_000L;

    private static Path file;
    private static long lastCheck;
    private static boolean loaded;
    private static boolean pending;
    private static long generation;
    private static final java.util.concurrent.ExecutorService READER =
            java.util.concurrent.Executors.newSingleThreadExecutor(job -> {
                Thread thread = new Thread(job, "cubeon-cosmetic-settings");
                thread.setDaemon(true);
                return thread;
            });
    public static final java.util.List<String> SLOTS = CosmeticCatalog.SLOTS;
    private static volatile Items selected = new Items(null, null);

    private CosmeticSelection() {
    }

    /** Initial binding loads once; later frame-time refreshes never read storage. */
    public static void bind(Path configFile) {
        long requestGeneration;
        synchronized (CosmeticSelection.class) {
            file = configFile;
            lastCheck = System.nanoTime();
            loaded = true;
            requestGeneration = ++generation;
            selected = new Items(null, null);
        }
        read(configFile, requestGeneration);
    }

    /** Safe every frame: enqueue at most one bounded read, then return. */
    public static synchronized void refresh() {
        if (file == null || pending) return;
        long now = System.nanoTime();
        if (loaded && now - lastCheck < CHECK_INTERVAL_NANOS) return;
        lastCheck = now;
        pending = true;
        Path source = file;
        long requestGeneration = generation;
        READER.execute(() -> {
            try { read(source, requestGeneration); }
            finally {
                synchronized (CosmeticSelection.class) { pending = false; }
            }
        });
    }

    private static void read(Path source, long requestGeneration) {
        String text = null;
        if (source != null) {
            try (var stream = Files.newInputStream(source)) {
                byte[] bytes = stream.readNBytes(65_537);
                if (bytes.length <= 65_536) text = new String(bytes, StandardCharsets.UTF_8);
            } catch (IOException | RuntimeException ignored) {
                // Unreadable settings remove decorations without interrupting frames.
            }
        }
        Items next = text == null ? new Items(null, null) : Items.parse(Json.parseObject(text));
        synchronized (CosmeticSelection.class) {
            if (generation != requestGeneration) return;
            selected = next;
            loaded = true;
        }
    }

    /** The selected id for a slot, or {@code null}. */
    public static String get(String slot) {
        return selected.get(slot);
    }

    /** Immutable selection captured before queued rendering. */
    public record Items(String back, String shoulder, String face, String head,
                        String waist, String hand, String trail) {
        public Items(String back, String shoulder) { this(back, shoulder, null, null, null, null, null); }
        public boolean empty() { return back == null && shoulder == null && face == null
                && head == null && waist == null && hand == null && trail == null; }
        public String get(String slot) {
            if (slot == null) return null;
            return switch (slot) {
                case "back" -> back; case "shoulder" -> shoulder; case "face" -> face;
                case "head" -> head; case "waist" -> waist; case "hand" -> hand;
                case "trail" -> trail; default -> null;
            };
        }
        public static Items parse(Map<String, Object> root) {
            return new Items(valid(Json.str(root, "back", null), "back"),
                    valid(Json.str(root, "shoulder", null), "shoulder"),
                    valid(Json.str(root, "face", null), "face"),
                    valid(Json.str(root, "head", null), "head"),
                    valid(Json.str(root, "waist", null), "waist"),
                    valid(Json.str(root, "hand", null), "hand"),
                    valid(Json.str(root, "trail", null), "trail"));
        }
    }

    public static Items snapshot() {
        refresh();
        return selected;
    }

    /** Only rigged wings can play the N action; packs and unknown ids cannot. */
    public static String selectedWing() {
        String id = get("back");
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        CosmeticCatalog.Item item = catalog == null ? null : catalog.get(id);
        if (item != null && item.wingFlare) {
            for (CosmeticCatalog.Box box : item.boxes) {
                if ("wing".equals(box.motion)) return id;
            }
        }
        return null;
    }

    private static String valid(String id, String slot) {
        if (id == null || id.isEmpty()) {
            return null;
        }
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.get();
        if (catalog == null) {
            return null;
        }
        CosmeticCatalog.Item item = catalog.get(id);
        return item != null && slot.equals(item.slot) ? id : null;
    }
}
