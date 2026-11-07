package com.cubeon.client.skins;

import com.cubeon.client.cosmetics.CosmeticCatalog;
import com.cubeon.client.cosmetics.CosmeticGeometry;
import java.util.List;
import javax.imageio.ImageIO;

/** Bundled geometry/textures decoded on the wardrobe worker, never while drawing. */
public final class CosmeticPreview {
    public record Model(String id, String slot, List<CosmeticGeometry.Quad> quads,
                        int[] pixels, int width, int height, boolean wings) {}
    private CosmeticPreview() {}
    public static Model load(String id) throws Exception {
        var catalog=CosmeticCatalog.get();
        var item=catalog==null?null:catalog.get(id);
        if(item==null) return null; // Older jars safely omit newer catalogue items.
        try(var stream=CosmeticPreview.class.getResourceAsStream(
                "/assets/cubeon-client/textures/cosmetics/"+item.texture)) {
            if(stream==null) return null;
            var image=ImageIO.read(stream);
            if(image==null || image.getWidth()!=item.texWidth || image.getHeight()!=item.texHeight
                    || (long)item.texWidth*item.texHeight>4_194_304) return null;
            return new Model(id,item.slot,CosmeticGeometry.quads(item,catalog.anchorX(item.slot)),
                    image.getRGB(0,0,item.texWidth,item.texHeight,null,0,item.texWidth),item.texWidth,item.texHeight,
                    "back".equals(item.slot)&&item.boxes.stream().anyMatch(box->"wing".equals(box.motion)));
        }
    }
}
