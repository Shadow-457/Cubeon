package com.cubeon.client.cosmetics;

import java.io.InputStream;
import javax.imageio.ImageIO;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;

/** Render-only elytra replacement. Never changes equipment or flight physics. */
public final class CosmeticElytra {
    private static final ThreadLocal<Pass> PASS = ThreadLocal.withInitial(Pass::new);
    private static final Map<CosmeticCatalog.Item, Boolean> ART = new IdentityHashMap<>();
    private CosmeticElytra() { }

    private static final class Pass {
        Object player;
        boolean wingsDrawn;
    }

    /** Start even for hidden/empty selections so a previous player cannot hide elytra. */
    public static void begin(Object player) {
        Pass pass = PASS.get();
        pass.player = player;
        pass.wingsDrawn = false;
    }

    /** Call only after the matching wing mesh was emitted or queued successfully. */
    public static void drawn(CosmeticCatalog.Item item) {
        if (ready(item)) PASS.get().wingsDrawn = true;
    }

    /** Vanilla's wing layer consumes this once, including when no elytra is equipped. */
    public static boolean consume(Object player) {
        Pass pass = PASS.get();
        boolean replace = pass.player == player && pass.wingsDrawn;
        pass.player = null;
        pass.wingsDrawn = false;
        return replace;
    }

    /** Missing art, non-wing backs and empty meshes must preserve vanilla equipment. */
    public static boolean ready(CosmeticCatalog.Item item) {
        if (item == null) return false;
        return ART.computeIfAbsent(item, CosmeticElytra::hasArtwork);
    }

    private static boolean hasArtwork(CosmeticCatalog.Item item) {
        if (!"back".equals(item.slot)
                || item.boxes.stream().noneMatch(box -> "wing".equals(box.motion))
                || CosmeticGeometry.quads(item, 0).isEmpty()) return false;
        try (InputStream stream = CosmeticElytra.class.getResourceAsStream(
                "/assets/cubeon-client/textures/cosmetics/" + item.texture)) {
            if (stream == null) return false;
            var image = ImageIO.read(stream);
            if (image == null || image.getWidth() != item.texWidth
                    || image.getHeight() != item.texHeight) return false;
            for (int y = 0; y < image.getHeight(); y++) {
                for (int x = 0; x < image.getWidth(); x++) {
                    if ((image.getRGB(x, y) >>> 24) != 0) return true;
                }
            }
            return false;
        } catch (Exception ignored) {
            return false;
        }
    }

    /** Put cosmetics immediately before vanilla wings, so cancellation follows a real draw. */
    @SuppressWarnings({"rawtypes", "unchecked"})
    public static boolean order(List<?> layers, Object cosmetics, Class<?> vanillaWings) {
        int own = layers.indexOf(cosmetics), wings = -1;
        for (int i = 0; i < layers.size(); i++) {
            if (vanillaWings.isInstance(layers.get(i))) { wings = i; break; }
        }
        if (own < 0 || wings < 0) return false;
        if (own > wings) {
            List writable = layers;
            writable.remove(own);
            writable.add(wings, cosmetics);
        }
        return true;
    }
}
