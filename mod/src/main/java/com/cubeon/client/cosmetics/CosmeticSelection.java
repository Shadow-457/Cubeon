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
 * cosmetic is not worth a lock file. The launcher rewrites it atomically and
 * only when the selection actually changes, so re-reading a tiny file a few
 * times a second is cheap and picks up a change while the game is still
 * running.
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
    private static String lastText;
    private static long lastCheck;
    private static boolean loaded;
    private static volatile String shoulder;
    private static volatile String back;

    private CosmeticSelection() {
    }

    /** Points the reader at one config file and loads it immediately. */
    public static synchronized void bind(Path configFile) {
        file = configFile;
        lastText = null;
        lastCheck = 0L;
        loaded = false;
        shoulder = null;
        back = null;
        refresh();
    }

    /** Re-reads the file if it changed. Safe to call every frame. */
    public static synchronized void refresh() {
        if (file == null) {
            return;
        }
        long now = System.nanoTime();
        if (loaded && now - lastCheck < CHECK_INTERVAL_NANOS) {
            return;
        }
        lastCheck = now;
        String text;
        try {
            text = Files.readString(file, StandardCharsets.UTF_8);
        } catch (IOException | RuntimeException ignored) {
            // Missing file, read-only folder, half-written file: no cosmetics.
            lastText = null;
            loaded = true;
            shoulder = null;
            back = null;
            return;
        }
        if (text.equals(lastText)) {
            loaded = true;
            return;
        }
        lastText = text;
        Map<String, Object> root = Json.parseObject(text);
        shoulder = valid(Json.str(root, "shoulder", null), "shoulder");
        back = valid(Json.str(root, "back", null), "back");
        loaded = true;
    }

    /** The selected id for a slot, or {@code null}. */
    public static String get(String slot) {
        return "shoulder".equals(slot) ? shoulder : "back".equals(slot) ? back : null;
    }

    /** Immutable selection captured before queued rendering. */
    public record Items(String back, String shoulder) {
        public String get(String slot) { return "back".equals(slot) ? back : "shoulder".equals(slot) ? shoulder : null; }
        public static Items parse(Map<String, Object> root) {
            return new Items(valid(Json.str(root, "back", null), "back"),
                    valid(Json.str(root, "shoulder", null), "shoulder"));
        }
    }

    public static synchronized Items snapshot() {
        refresh();
        return new Items(back, shoulder);
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
