package com.cubeon.client.skins;

import com.mojang.blaze3d.platform.NativeImage;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.resources.Identifier;
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
            Minecraft.getInstance().getTextureManager().register(id,
                    new DynamicTexture(() -> "Cubeon peer skin", image));
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
