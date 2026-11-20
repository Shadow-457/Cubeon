package com.cubeon.client.cosmetics;

import java.util.Arrays;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.WeakHashMap;

/** Fitted cosmetics trim covered outer texels, never the player's base skin. */
public final class CosmeticSkinCoverage {
    private static final WeakHashMap<CosmeticCatalog.Item, Pixels[]> CACHE = new WeakHashMap<>();
    private record Selection(CosmeticCatalog.Catalog catalog, CosmeticSelection.Items items, boolean slim) { }
    private static final LinkedHashMap<Selection, Pixels> SELECTIONS = new LinkedHashMap<>(128, .75f, true);
    private static final Pixels EMPTY = new Pixels(new long[64], 0);
    private CosmeticSkinCoverage() { }

    /** Immutable 64px atlas mask, also usable with legacy and HD skin sheets. */
    public static final class Pixels {
        private final long[] rows;
        private final int fullLayers;
        private Pixels(long[] rows, int fullLayers) { this.rows = rows; this.fullLayers = fullLayers; }
        public boolean empty() {
            for (long row : rows) if (row != 0) return false;
            return true;
        }
        public boolean covered(int x, int y, int width, int height) {
            if (width < 64 || width % 64 != 0 || (height != width && height != width / 2)) return false;
            int column = x * 64 / width, row = y * 64 / width;
            return column >= 0 && column < 64 && row >= 0 && row < 64 && (rows[row] & 1L << column) != 0;
        }
        @Override public boolean equals(Object value) {
            return value instanceof Pixels other && Arrays.equals(rows, other.rows);
        }
        @Override public int hashCode() { return Arrays.hashCode(rows); }
    }

    public static boolean hidden(CosmeticSelection.Items selected, String part) {
        int bit = switch (part) {
            case "HAT" -> 1; case "JACKET" -> 2;
            case "LEFT_SLEEVE" -> 4; case "RIGHT_SLEEVE" -> 8;
            case "LEFT_PANTS_LEG" -> 16; case "RIGHT_PANTS_LEG" -> 32;
            default -> 0;
        };
        return bit != 0 && (pixels(selected, false).fullLayers & bit) != 0;
    }

    /** Whole-layer fallback is safe only when all six surfaces are enclosed. */
    public static int mask(CosmeticCatalog.Item item) { return pixels(item, false).fullLayers; }

    public static synchronized Pixels pixels(CosmeticSelection.Items selected, boolean slim) {
        var catalog = CosmeticCatalog.get();
        if (selected == null || selected.empty() || catalog == null) return EMPTY;
        var key = new Selection(catalog, selected, slim);
        var found = SELECTIONS.get(key);
        if (found != null) return found;
        var items = new java.util.ArrayList<CosmeticCatalog.Item>();
        for (String slot : List.of("head", "face", "feet", "hand", "waist")) {
            var item = catalog.get(selected.get(slot));
            if (item != null) items.add(item);
        }
        var result = pixels(items, slim);
        SELECTIONS.put(key, result);
        if (SELECTIONS.size() > 128) SELECTIONS.remove(SELECTIONS.keySet().iterator().next());
        return result;
    }

    public static synchronized Pixels pixels(Collection<CosmeticCatalog.Item> items, boolean slim) {
        long[] rows = new long[64];
        for (var item : items) {
            var mask = pixels(item, slim);
            for (int y = 0; y < 64; y++) rows[y] |= mask.rows[y];
        }
        return finish(rows, slim);
    }

    public static synchronized Pixels pixels(CosmeticCatalog.Item item, boolean slim) {
        if (item == null) return EMPTY;
        var cached = CACHE.get(item);
        if (cached == null) {
            if (CACHE.size() >= 256) CACHE.clear();
            cached = new Pixels[2];
            CACHE.put(item, cached);
        }
        int index = slim ? 1 : 0;
        if (cached[index] != null) return cached[index];
        long[] rows = new long[64];
        for (var part : parts(slim)) {
            if (!targets(item.slot, part.name)) continue;
            for (var box : item.boxes) {
                if (box.faces == 0 || ("feet".equals(item.slot)
                        ? !part.name.equals(box.motion) : !"none".equals(box.motion))) continue;
                project(rows, part, box, false, item.slot);
                if (box.mirror) project(rows, part, box, true, item.slot);
            }
        }
        cached[index] = finish(rows, slim);
        return cached[index];
    }

    private static boolean targets(String slot, String part) {
        return switch (slot) {
            case "head", "face" -> "head".equals(part);
            case "feet" -> "left_leg".equals(part) || "right_leg".equals(part);
            case "hand" -> "right_arm".equals(part);
            case "waist" -> "body".equals(part);
            default -> false;
        };
    }

    private record Part(String name, int bit, int u, int v, float x, float y, float z, int w, int h, int d) {
        float origin(int axis) { return axis == 0 ? x : axis == 1 ? y : z; }
        int size(int axis) { return axis == 0 ? w : axis == 1 ? h : d; }
        Surface[] surfaces() {
            return new Surface[] {
                new Surface(u+d, v+d, w, h, 2, -1, 0, 1, 1, 1),
                new Surface(u+2*d+w, v+d, w, h, 2, 1, 0, -1, 1, 1),
                new Surface(u, v+d, d, h, 0, -1, 2, -1, 1, 1),
                new Surface(u+d+w, v+d, d, h, 0, 1, 2, 1, 1, 1),
                new Surface(u+d, v, w, d, 1, -1, 0, 1, 2, -1),
                new Surface(u+d+w, v, w, d, 1, 1, 0, 1, 2, 1)
            };
        }
    }
    private record Surface(int u, int v, int w, int h, int axis, int sign,
                           int across, int acrossSign, int down, int downSign) { }
    private static Part[] parts(boolean slim) {
        int arm = slim ? 3 : 4;
        return new Part[] {
            new Part("head", 1, 32, 0, -4, -8, -4, 8, 8, 8),
            new Part("body", 2, 16, 32, -4, 0, -2, 8, 12, 4),
            new Part("right_arm", 8, 40, 32, -4-arm, 0, -2, arm, 12, 4),
            new Part("left_arm", 4, 48, 48, 4, 0, -2, arm, 12, 4),
            new Part("right_leg", 32, 0, 32, -4, 12, -2, 4, 12, 4),
            new Part("left_leg", 16, 0, 48, 0, 12, -2, 4, 12, 4)
        };
    }

    private static void project(long[] rows, Part part, CosmeticCatalog.Box box, boolean mirror, String slot) {
        float[] low = {box.x, box.y, box.z}, high = {box.x+box.width, box.y+box.height, box.z+box.depth};
        if (mirror) {
            float anchor = "hand".equals(slot) ? -5 : 0;
            low[0] = 2*anchor-high[0]; high[0] = 2*anchor-box.x;
        }
        for (var face : part.surfaces()) {
            float plane = part.origin(face.axis) + (face.sign > 0 ? part.size(face.axis) : 0);
            // The one-unit band catches raised skin beneath fitted shells;
            // floating ornaments and boxes inside the base do not trim skin.
            boolean nearby = face.sign < 0
                    ? low[face.axis] < plane+.00001f && high[face.axis] > plane-1
                    : high[face.axis] > plane-.00001f && low[face.axis] < plane+1;
            if (!nearby) continue;
            for (int y = 0; y < face.h; y++) {
                float top = part.origin(face.down) + (face.downSign > 0 ? y : part.size(face.down)-y-1);
                if (high[face.down] <= top+.00001f || low[face.down] >= top+1-.00001f) continue;
                for (int x = 0; x < face.w; x++) {
                    float left = part.origin(face.across) + (face.acrossSign > 0 ? x : part.size(face.across)-x-1);
                    if (high[face.across] > left+.00001f && low[face.across] < left+1-.00001f)
                        rows[face.v+y] |= 1L << (face.u+x);
                }
            }
        }
    }

    private static Pixels finish(long[] rows, boolean slim) {
        int full = 0;
        for (var part : parts(slim)) {
            boolean enclosed = true;
            for (var face : part.surfaces()) {
                long expected = ((1L << face.w)-1) << face.u;
                for (int y = face.v; y < face.v+face.h; y++)
                    enclosed &= (rows[y] & expected) == expected;
            }
            if (enclosed) full |= part.bit;
        }
        return new Pixels(rows, full);
    }

    /** Optional retained-image API supplied by 3D Skin Layers for HTTP skins. */
    public static Object retainedImage(Object texture) { return ImageAccess.get(texture); }
    private static final class ImageAccess {
        private static final java.lang.reflect.Method GET = getter();
        private static java.lang.reflect.Method getter() {
            try {
                return Class.forName("dev.tr7zw.skinlayers.accessor.HttpTextureAccessor", false,
                        CosmeticSkinCoverage.class.getClassLoader()).getMethod("getImage");
            } catch (ReflectiveOperationException | LinkageError ignored) { return null; }
        }
        static Object get(Object texture) {
            if (GET == null || !GET.getDeclaringClass().isInstance(texture)) return null;
            try { return GET.invoke(texture); }
            catch (ReflectiveOperationException | RuntimeException ignored) { return null; }
        }
    }
}
