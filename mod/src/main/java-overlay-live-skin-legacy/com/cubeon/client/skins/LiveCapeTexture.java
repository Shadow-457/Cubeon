package com.cubeon.client.skins;
import net.minecraft.util.Identifier;
import net.minecraft.client.texture.NativeImage;
import net.minecraft.client.texture.NativeImageBackedTexture;
import net.minecraft.client.MinecraftClient;
import org.slf4j.LoggerFactory;

/** One owned GPU texture. A frame change replaces pixels, never the texture registration. */
public final class LiveCapeTexture {
    private static final Identifier ID=Identifier.tryParse("cubeon-client:live_cape");
    private static long uploaded,failed;
    private static int shown=-1;
    private static NativeImageBackedTexture texture;
    private LiveCapeTexture() { }
    private static void clear() {
        if(texture!=null) MinecraftClient.getInstance().getTextureManager().destroyTexture(ID);
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
                    var created=new NativeImageBackedTexture(image);
                    texture=created;
                    image=null; // created owns the image, including on failure
                    MinecraftClient.getInstance().getTextureManager().registerTexture(ID,created);
                } else {
                    texture.setImage(image);
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
