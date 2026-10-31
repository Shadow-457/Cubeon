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
        public final float width;
        public final float height;
        public final float depth;
        public final int px;
        public final int uvX;
        public final int uvY;
        public final boolean mirror;
        public final String motion;
        public final float pivotX, pivotY, pivotZ;
        public final int faces;
        public final int feather;

        Box(float x, float y, float z, float width, float height, float depth,
            int px, int uvX, int uvY, boolean mirror, String motion,
            float pivotX, float pivotY, float pivotZ, int faces, int feather) {
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
            this.motion = motion;
            this.pivotX = pivotX;
            this.pivotY = pivotY;
            this.pivotZ = pivotZ;
            this.faces = faces;
            this.feather = feather;
        }
    }

    /** Artist-authored feather centre lines, in unmirrored model space. */
    public static final class Feather {
        public final float x, y, endX, endY, width, curve, curl, tilt;
        Feather(float x, float y, float endX, float endY, float width, float curve, float curl, float tilt) {
            this.x = x; this.y = y; this.endX = endX; this.endY = endY;
            this.width = width; this.curve = curve;
            this.curl = curl; this.tilt = tilt;
        }
    }

    /** Front, back, left, right, top, bottom, in the shared atlas order. */
    public static int faceBit(String name) {
        return switch (name) {
            case "front" -> 1; case "back" -> 2; case "left" -> 4;
            case "right" -> 8; case "top" -> 16; case "bottom" -> 32;
            default -> 0;
        };
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
        public final List<Feather> feathers;
        public final boolean wingFlare;
        public final boolean separateFeathers;
        public final Item flatVariant;

        Item(String id, String slot, String name, String texture,
             int texWidth, int texHeight, List<Box> boxes, List<Feather> feathers,
             boolean wingFlare, boolean separateFeathers, Item flatVariant) {
            this.id = id;
            this.slot = slot;
            this.name = name;
            this.texture = texture;
            this.texWidth = texWidth;
            this.texHeight = texHeight;
            this.boxes = Collections.unmodifiableList(boxes);
            this.feathers = Collections.unmodifiableList(feathers);
            this.wingFlare = wingFlare;
            this.separateFeathers = separateFeathers;
            this.flatVariant = flatVariant;
        }

        /** Resolve once before queued rendering so a setting change cannot mix meshes. */
        public Item forWingDepth(boolean enabled) {
            return !enabled && separateFeathers && flatVariant != null ? flatVariant : this;
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
            return parseItem(raw, true);
        }

        private static Item parseItem(Object raw, boolean allowFlat) {
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
            List<Feather> feathers = new ArrayList<>();
            for (Object guide : Json.list(raw, "feathers")) {
                List<Object> start = Json.list(guide, "start"), end = Json.list(guide, "end");
                float width = (float) Json.num(guide, "width");
                float curve = (float) Json.num(guide, "curve");
                if (start.size() < 2 || end.size() < 2 || width <= 0 || !Float.isFinite(width)
                        || !Float.isFinite(curve) || feathers.size() >= 16) continue;
                float x = (float) number(start.get(0)), y = (float) number(start.get(1));
                float ex = (float) number(end.get(0)), ey = (float) number(end.get(1));
                if (!Float.isFinite(x) || !Float.isFinite(y) || !Float.isFinite(ex)
                        || !Float.isFinite(ey) || Math.hypot(ex - x, ey - y) < 0.1) continue;
                float curl = (float) Json.num(guide, "curl"), tilt = (float) Json.num(guide, "tilt");
                if (!Float.isFinite(curl) || Math.abs(curl) > 8
                        || !Float.isFinite(tilt) || Math.abs(tilt) > .5f) continue;
                feathers.add(new Feather(x, y, ex, ey, width, curve, curl, tilt));
            }
            Item flat = allowFlat ? parseItem(((Map<?, ?>) raw).get("flat"), false) : null;
            if (flat != null && (!id.equals(flat.id) || !slot.equals(flat.slot))) flat = null;
            return new Item(id, slot, Json.str(raw, "name", id), texture,
                    texWidth, texHeight, boxes, feathers, Json.bool(raw, "wing_flare", true),
                    Json.bool(raw, "separate_feathers", false), flat);
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
            float width = (float) number(size.get(0));
            float height = (float) number(size.get(1));
            float depth = (float) number(size.get(2));
            int px = (int) Json.num(raw, "px");
            if (!Float.isFinite(width) || !Float.isFinite(height) || !Float.isFinite(depth)
                    || width <= 0 || height <= 0 || depth <= 0 || px <= 0) {
                return null;
            }
            List<Object> pivot = Json.list(raw, "pivot");
            boolean rigged = pivot.size() >= 3;
            if (rigged) {
                for (int i = 0; i < 3; i++) {
                    rigged &= Float.isFinite((float) number(pivot.get(i)));
                }
            }
            int faces = 63;
            if (((Map<?, ?>) raw).containsKey("faces")) {
                faces = 0;
                for (Object face : Json.list(raw, "faces")) faces |= faceBit(String.valueOf(face));
            }
            double feather = ((Map<?, ?>) raw).containsKey("feather") ? Json.num(raw, "feather") : -1;
            int featherIndex = Double.isFinite(feather) && feather == Math.rint(feather)
                    && feather >= 0 && feather < 16 ? (int) feather : -1;
            return new Box((float) number(origin.get(0)),
                    (float) number(origin.get(1)),
                    (float) number(origin.get(2)),
                    width, height, depth, px,
                    (int) number(uv.get(0)), (int) number(uv.get(1)),
                    Json.bool(raw, "mirror", false),
                    rigged ? Json.str(raw, "motion", "none") : "none",
                    rigged ? (float) number(pivot.get(0)) : 0,
                    rigged ? (float) number(pivot.get(1)) : 0,
                    rigged ? (float) number(pivot.get(2)) : 0, faces, featherIndex);
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
