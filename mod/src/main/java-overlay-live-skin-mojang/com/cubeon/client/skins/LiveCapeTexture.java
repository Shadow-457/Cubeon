package com.cubeon.client.skins;
import net.minecraft.resources.Identifier;
import com.mojang.blaze3d.platform.NativeImage;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.client.Minecraft;
import org.slf4j.LoggerFactory;

/** One owned GPU texture. A frame change replaces pixels, never the texture registration. */
public final class LiveCapeTexture {
    private static final Identifier ID=Identifier.tryParse("cubeon-client:live_cape");
    private static long uploaded,failed;
    private static int shown=-1;
    private static DynamicTexture texture;
    private LiveCapeTexture() { }
    private static void clear() {
        if(texture!=null) Minecraft.getInstance().getTextureManager().release(ID);
        texture=null; uploaded=0; shown=-1;
    }
    public static Identifier texture() {
        var cape=LiveCape.get();
        if(cape==null || cape.hidden()) { clear(); return null; }
        if(cape.revision()==failed) return null;
        int frame=cape.index(System.nanoTime());
        if(uploaded!=cape.revision() || shown!=frame) {
            NativeImage image=null;
            try {
                // A new selection can have different HD dimensions. Allocate
                // again for that change; frame uploads retain the allocation.
                if(uploaded!=cape.revision()) clear();
                image=NativeImage.read(cape.frame(frame));
                if(texture==null) {
                    var created=new DynamicTexture(() -> "Cubeon live cape", image);
                    texture=created;
                    image=null; // created owns the image, including on failure
                    Minecraft.getInstance().getTextureManager().register(ID,created);
                } else {
                    texture.setPixels(image);
                    image=null;
                    texture.upload();
                }
                uploaded=cape.revision(); shown=frame;
            } catch(Exception error) {
                if(image!=null) image.close();
                clear(); failed=cape.revision();
                LoggerFactory.getLogger("Cubeon capes").warn("Couldn't upload selected cape",error);
                return null;
            }
        }
        return ID;
    }
}
