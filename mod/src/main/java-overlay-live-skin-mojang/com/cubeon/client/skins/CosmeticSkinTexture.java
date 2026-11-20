package com.cubeon.client.skins;

import com.cubeon.client.cosmetics.CosmeticSelection;
import com.cubeon.client.cosmetics.CosmeticSkinCoverage;
import net.minecraft.client.Minecraft;
import com.mojang.blaze3d.platform.NativeImage;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.resources.Identifier;
import java.util.LinkedHashMap;
import org.slf4j.LoggerFactory;

/** Bounded display copies; changing identifiers makes 3D skin meshes rebuild. */
public final class CosmeticSkinTexture {
    private record Entry(Identifier source, Object sourceTexture, NativeImage image,
                         CosmeticSkinCoverage.Pixels mask, Identifier output, long retry, long pixels) { }
    private static final LinkedHashMap<Object, Entry> CACHE = new LinkedHashMap<>(128, .75f, true);
    private static Object world;
    private static long serial, pixels;
    private CosmeticSkinTexture() { }

    public static Identifier texture(Identifier source, Object player, CosmeticSelection.Items selected, boolean slim) {
        var client = Minecraft.getInstance();
        if (client == null || source == null) return source;
        if (world != client.level) { clear(); world = client.level; }
        var mask = CosmeticSkinCoverage.pixels(selected, slim);
        if (mask.empty()) { discard(player); return source; }
        var textures = client.getTextureManager();
        var original = textures.getTexture(source);
        NativeImage image = original instanceof DynamicTexture dynamic ? dynamic.getPixels() : null;
        if (image == null && CosmeticSkinCoverage.retainedImage(original) instanceof NativeImage retained) image = retained;
        var found = CACHE.get(player);
        if (found != null && source.equals(found.source) && original == found.sourceTexture
                && image == found.image && mask.equals(found.mask)
                && (found.output != null || System.nanoTime() < found.retry))
            return found.output == null ? source : found.output;
        discard(player);
        boolean owned = false;
        NativeImage borrowed = image;
        NativeImage copy = null;
        try {
            if (image == null) {
                var resource = client.getResourceManager().getResource(source);
                if (resource.isPresent()) {
                    try (var input = resource.get().open()) { image = NativeImage.read(input); owned = true; }
                }
            }
            if (image == null || image.getWidth() < 64 || image.getWidth() > 2048 || image.getWidth() % 64 != 0
                    || (image.getHeight() != image.getWidth() && image.getHeight() != image.getWidth()/2)) {
                remember(player, new Entry(source, original, borrowed, mask, null, System.nanoTime()+1_000_000_000L, 0));
                return source;
            }
            int width = image.getWidth(), height = image.getHeight();
            copy = new NativeImage(image.format(), width, height, false);
            copy.copyFrom(image);
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++)
                if (mask.covered(x, y, width, height)) copy.fillRect(x, y, 1, 1, 0);
            Identifier id = Identifier.tryParse("cubeon-client:covered_skin/"+Long.toUnsignedString(++serial));
            textures.register(id, new DynamicTexture(() -> "Cubeon covered skin", copy));
            copy = null; // The registered texture owns the image from here.
            remember(player, new Entry(source, original, borrowed, mask, id, 0, (long)width*height));
            return id;
        } catch (Exception error) {
            remember(player, new Entry(source, original, borrowed, mask, null, Long.MAX_VALUE, 0));
            LoggerFactory.getLogger("Cubeon skins").warn("Couldn't trim skin beneath cosmetics", error);
            return source;
        } finally {
            if (copy != null) copy.close();
            if (owned && image != null) image.close();
        }
    }

    private static void remember(Object player, Entry entry) {
        CACHE.put(player, entry); pixels += entry.pixels;
        while (CACHE.size() > 128 || pixels > 16_777_216) discard(CACHE.keySet().iterator().next());
    }
    private static void discard(Object player) {
        var removed = CACHE.remove(player);
        if (removed == null) return;
        pixels -= removed.pixels;
        if (removed.output != null) Minecraft.getInstance().getTextureManager().release(removed.output);
    }
    private static void clear() {
        while (!CACHE.isEmpty()) discard(CACHE.keySet().iterator().next());
    }
}
