package com.cubeon.client.cosmetics;

import java.util.WeakHashMap;

/** Hide only outer skin parts intersecting a fitted cosmetic; keep base skin. */
public final class CosmeticSkinCoverage {
    private static final WeakHashMap<CosmeticCatalog.Item, Integer> CACHE = new WeakHashMap<>();
    private CosmeticSkinCoverage() { }

    public static boolean hidden(CosmeticSelection.Items selected, String part) {
        if (selected == null) return false;
        int bit = switch (part) {
            case "HAT" -> 1; case "JACKET" -> 2;
            case "LEFT_SLEEVE" -> 4; case "RIGHT_SLEEVE" -> 8;
            case "LEFT_PANTS_LEG" -> 16; case "RIGHT_PANTS_LEG" -> 32;
            default -> 0;
        };
        if (bit == 0) return false;
        var catalog = CosmeticCatalog.get();
        if (catalog == null) return false;
        for (String slot : CosmeticSelection.SLOTS) {
            var item = catalog.get(selected.get(slot));
            if (item != null && (mask(item) & bit) != 0) return true;
        }
        return false;
    }

    public static synchronized int mask(CosmeticCatalog.Item item) {
        Integer cached = CACHE.get(item);
        if (cached != null) return cached;
        int mask = 0;
        if ("head".equals(item.slot) || "face".equals(item.slot)) {
            for (var box : item.boxes) {
                if (box.x < 4.75f && box.x + box.width > -4.75f
                        && box.y < .75f && box.y + box.height > -8.75f
                        && box.z < 4.75f && box.z + box.depth > -4.75f) { mask |= 1; break; }
            }
        } else if ("feet".equals(item.slot)) mask = 16 | 32;
        else if ("hand".equals(item.slot)) mask = 8;
        else if ("waist".equals(item.slot)) mask = 2;
        if (CACHE.size() >= 256) CACHE.clear();
        CACHE.put(item, mask);
        return mask;
    }
}
