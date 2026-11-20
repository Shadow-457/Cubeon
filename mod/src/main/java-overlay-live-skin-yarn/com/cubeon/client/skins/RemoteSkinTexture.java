package com.cubeon.client.skins;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.texture.NativeImage;
import net.minecraft.client.texture.NativeImageBackedTexture;
import net.minecraft.util.Identifier;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.Locale;

/** Render-thread upload cache for native peer skins. */
public final class RemoteSkinTexture {
    private record Entry(String id, Identifier texture) { }
    private static final LinkedHashMap<String, Entry> CACHE = new LinkedHashMap<>(128, .75f, true);
    private RemoteSkinTexture() { }
    public static synchronized Identifier texture(String username, RemoteSkins.Skin skin) {
        if (username == null || skin == null) return null;
        String key = username.toLowerCase(Locale.ROOT);
        Entry found = CACHE.get(key);
        if (found != null && found.id.equals(skin.id())) return found.texture;
        Identifier id = Identifier.tryParse("cubeon-client:peer_skin/" + key);
        try {
            var image = NativeImage.read(skin.png());
            MinecraftClient.getInstance().getTextureManager().registerTexture(id, new NativeImageBackedTexture(image));
            CACHE.put(key, new Entry(skin.id(), id));
            trim();
            return id;
        } catch (Exception error) {
            CACHE.put(key, new Entry(skin.id(), null));
            trim();
            LoggerFactory.getLogger("Cubeon skins").warn("Couldn't upload peer skin for {}", username, error);
            return null;
        }
    }
    private static void trim() {
        while (CACHE.size() > 128) CACHE.remove(CACHE.keySet().iterator().next());
    }
}
