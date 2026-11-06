package com.cubeon.client.skins;
import net.minecraft.resources.Identifier;
import com.mojang.blaze3d.platform.NativeImage;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.client.Minecraft;
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
                var texture=new DynamicTexture(() -> "Cubeon live skin", image);
                Minecraft.getInstance().getTextureManager().register(ID,texture);
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
