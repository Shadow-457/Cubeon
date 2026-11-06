package com.cubeon.client.skins;
import net.minecraft.util.Identifier;
import net.minecraft.client.texture.NativeImage;
import net.minecraft.client.texture.NativeImageBackedTexture;
import net.minecraft.client.MinecraftClient;
import org.slf4j.LoggerFactory;

/** One owned GPU texture, uploaded only after a confirmed cape change. */
public final class LiveCapeTexture {
    private static final Identifier ID=Identifier.tryParse("cubeon-client:live_cape");
    private static long uploaded,failed;
    private LiveCapeTexture() { }
    public static Identifier texture() {
        var skin=LiveCape.get(); if(skin==null||skin.hidden()||skin.revision()==failed) return null;
        if(uploaded!=skin.revision()) {
            try {
                var image=NativeImage.read(skin.png());
                var texture=new NativeImageBackedTexture(() -> "Cubeon live cape", image);
                MinecraftClient.getInstance().getTextureManager().registerTexture(ID,texture);
                uploaded=skin.revision();
            } catch(Exception error) {
                failed=skin.revision();
                LoggerFactory.getLogger("Cubeon capes").warn("Couldn't upload selected cape",error);
                return null;
            }
        }
        return ID;
    }
}
