package com.cubeon.client.skins;
import net.minecraft.util.Identifier;
import net.minecraft.client.texture.NativeImage;
import net.minecraft.client.texture.NativeImageBackedTexture;
import net.minecraft.client.MinecraftClient;
import org.slf4j.LoggerFactory;

/** One owned GPU texture, uploaded only after a confirmed skin/model change. */
public final class LiveSkinTexture {
    private static final Identifier ID=Identifier.tryParse("cubeon-client:live_skin");
    private static long uploaded,failed;
    private LiveSkinTexture() { }
    public static Identifier texture() {
        var skin=LiveSkin.get(); if(skin==null||skin.revision()==failed) return null;
        if(uploaded!=skin.revision()) {
            try {
                var image=NativeImage.read(skin.png());
                var texture=new NativeImageBackedTexture(() -> "Cubeon live skin", image);
                MinecraftClient.getInstance().getTextureManager().registerTexture(ID,texture);
                uploaded=skin.revision();
            } catch(Exception error) {
                failed=skin.revision();
                LoggerFactory.getLogger("Cubeon skins").warn("Couldn't upload selected skin",error);
                return null;
            }
        }
        return ID;
    }
}
