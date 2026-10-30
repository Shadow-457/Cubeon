package com.cubeon.client.hud.screen;

import net.minecraft.client.gui.DrawContext;
import net.minecraft.util.Identifier;
import com.mojang.blaze3d.systems.RenderSystem;
import java.util.HashMap;
import java.util.Map;

/** Native cached texture quads; no image rasterization or upload on the render thread. */
final class ClientUiDraw {
    private static final Map<String, Identifier> TEXTURES = new HashMap<>();
    private ClientUiDraw() { }
    static void image(DrawContext context, String path, int x, int y, int w, int h, int u, int v,
                      int regionW, int regionH, int textureW, int textureH, int color) {
        if (w <= 0 || h <= 0 || (color >>> 24) == 0) return;
        Identifier texture = TEXTURES.computeIfAbsent(path, value -> Identifier.tryParse("cubeon-client:" + value));
        context.setShaderColor(((color >>> 16) & 255) / 255f, ((color >>> 8) & 255) / 255f,
                (color & 255) / 255f, (color >>> 24) / 255f);
        RenderSystem.enableBlend();
        RenderSystem.defaultBlendFunc();
        try {
            context.drawTexture(texture, x, y, w, h, (float)u, (float)v, regionW, regionH, textureW, textureH);
        } finally {
            RenderSystem.disableBlend();
            context.setShaderColor(1, 1, 1, 1);
        }
    }
}

