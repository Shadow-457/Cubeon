package com.cubeon.client.cosmetics;

import com.cubeon.client.Json;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The cosmetic catalogue bundled inside the mod jar.
 *
 * <p>This is the SAME file the launcher's 3D preview reads
 * ({@code assets/cosmetics/catalog.json}); {@code tools/gen_cosmetics.py} writes
 * both copies from one generator so a wing's geometry and its art cannot drift
 * between the preview and the game. The mod reads its copy from the classpath,
 * not from the launcher's install folder: a mod jar is self-contained, and a
 * player who installs an older jar should lose a cosmetic, never crash on a
 * missing file.
 *
 * <p>Minecraft-free on purpose. It lives in {@code src/main/java}, the tree
 * shared by every bracket, and {@code tools/test_cosmetics.py} compiles it with
 * a plain JDK to check the geometry against the Python preview.
 */
public final class CosmeticCatalog {

    /** Resource path inside the mod jar. */
    public static final String RESOURCE =
            "/assets/cubeon-client/cosmetics/catalog.json";

    /** One textured cuboid, in Minecraft model space (+x left, +y down, -z front). */
    public static final class Box {
        public final float x;
        public final float y;
        public final float z;
        public final int width;
        public final int height;
        public final int depth;
        public final int px;
        public final int uvX;
        public final int uvY;
        public final boolean mirror;

        Box(float x, float y, float z, int width, int height, int depth,
            int px, int uvX, int uvY, boolean mirror) {
            this.x = x;
            this.y = y;
            this.z = z;
            this.width = width;
            this.height = height;
            this.depth = depth;
            this.px = px;
            this.uvX = uvX;
            this.uvY = uvY;
            this.mirror = mirror;
        }
    }

    /** One catalogue entry. {@code texture} is a file name, not a resource id. */
    public static final class Item {
        public final String id;
        public final String slot;
        public final String name;
        public final String texture;
        public final int texWidth;
        public final int texHeight;
        public final List<Box> boxes;

        Item(String id, String slot, String name, String texture,
             int texWidth, int texHeight, List<Box> boxes) {
            this.id = id;
            this.slot = slot;
            this.name = name;
            this.texture = texture;
            this.texWidth = texWidth;
            this.texHeight = texHeight;
            this.boxes = Collections.unmodifiableList(boxes);
        }
    }

    /** A parsed catalogue. Immutable after construction. */
    public static final class Catalog {
        private final Map<String, Item> items;
        private final Map<String, Float> anchors;

        Catalog(Map<String, Item> items, Map<String, Float> anchors) {
            this.items = Collections.unmodifiableMap(items);
            this.anchors = Collections.unmodifiableMap(anchors);
        }

        public Item get(String id) {
            return id == null ? null : items.get(id);
        }

        public List<Item> items() {
            return new ArrayList<>(items.values());
        }

        /** The x mirror axis for a slot, or 0 when the catalogue is malformed. */
        public float anchorX(String slot) {
            Float value = anchors.get(slot);
            return value == null ? 0.0f : value;
        }

        /** Parses the catalogue text. Malformed entries are skipped, never fatal. */
        public static Catalog parse(String text) {
            Map<String, Object> root = Json.parseObject(text);
            Map<String, Float> anchors = new LinkedHashMap<>();
            Object anchorObject = root.get("anchors");
            if (anchorObject instanceof Map<?, ?> map) {
                for (Map.Entry<?, ?> entry : map.entrySet()) {
                    Object value = entry.getValue();
                    if (value instanceof List<?> list && !list.isEmpty()) {
                        anchors.put(String.valueOf(entry.getKey()),
                                (float) number(list.get(0)));
                    }
                }
            }
            Map<String, Item> items = new LinkedHashMap<>();
            for (Object raw : Json.list(root, "items")) {
                Item item = parseItem(raw);
                if (item != null && !items.containsKey(item.id)) {
                    items.put(item.id, item);
                }
            }
            return new Catalog(items, anchors);
        }

        private static Item parseItem(Object raw) {
            if (!(raw instanceof Map<?, ?>)) {
                return null;
            }
            String id = Json.str(raw, "id", "");
            String slot = Json.str(raw, "slot", "");
            String texture = Json.str(raw, "texture", "");
            int texWidth = (int) Json.num(raw, "tex_w");
            int texHeight = (int) Json.num(raw, "tex_h");
            if (id.isEmpty() || texture.isEmpty() || texWidth <= 0 || texHeight <= 0) {
                return null;
            }
            if (!"shoulder".equals(slot) && !"back".equals(slot)) {
                return null;
            }
            List<Box> boxes = new ArrayList<>();
            for (Object boxRaw : Json.list(raw, "boxes")) {
                Box box = parseBox(boxRaw);
                if (box != null) {
                    boxes.add(box);
                }
            }
            if (boxes.isEmpty()) {
                return null;
            }
            return new Item(id, slot, Json.str(raw, "name", id), texture,
                    texWidth, texHeight, boxes);
        }

        private static Box parseBox(Object raw) {
            if (!(raw instanceof Map<?, ?>)) {
                return null;
            }
            List<Object> origin = Json.list(raw, "origin");
            List<Object> size = Json.list(raw, "size");
            List<Object> uv = Json.list(raw, "uv");
            if (origin.size() < 3 || size.size() < 3 || uv.size() < 2) {
                return null;
            }
            int width = (int) number(size.get(0));
            int height = (int) number(size.get(1));
            int depth = (int) number(size.get(2));
            int px = (int) Json.num(raw, "px");
            if (width <= 0 || height <= 0 || depth <= 0 || px <= 0) {
                return null;
            }
            return new Box((float) number(origin.get(0)),
                    (float) number(origin.get(1)),
                    (float) number(origin.get(2)),
                    width, height, depth, px,
                    (int) number(uv.get(0)), (int) number(uv.get(1)),
                    Json.bool(raw, "mirror", false));
        }

        private static double number(Object value) {
            if (value instanceof Number number) {
                return number.doubleValue();
            }
            return 0.0;
        }
    }

    private static volatile Catalog catalog;

    private CosmeticCatalog() {
    }

    /** The bundled catalogue, or {@code null} if the jar has none. */
    public static Catalog get() {
        Catalog loaded = catalog;
        if (loaded != null) {
            return loaded;
        }
        synchronized (CosmeticCatalog.class) {
            if (catalog == null) {
                catalog = load();
            }
            return catalog;
        }
    }

    /** Drops the cached catalogue. Used by tests; the game never changes it. */
    public static synchronized void invalidate() {
        catalog = null;
    }

    private static Catalog load() {
        try (InputStream stream = CosmeticCatalog.class.getResourceAsStream(RESOURCE)) {
            if (stream == null) {
                return null;
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int read;
            while ((read = stream.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
            return Catalog.parse(new String(out.toByteArray(), StandardCharsets.UTF_8));
        } catch (IOException | RuntimeException ignored) {
            // A broken bundled catalogue must cost cosmetics, never the game.
            return null;
        }
    }
}
