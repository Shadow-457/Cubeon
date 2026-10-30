package com.cubeon.client.hud.screen;

import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.resources.Identifier;
import net.minecraft.client.renderer.RenderPipelines;
import java.util.HashMap;
import java.util.Map;

/** Native cached texture quads; no image rasterization or upload on the render thread. */
final class ClientUiDraw {
    private static final Map<String, Identifier> TEXTURES = new HashMap<>();
    private ClientUiDraw() { }
    static void image(GuiGraphicsExtractor context, String path, int x, int y, int w, int h, int u, int v,
                      int regionW, int regionH, int textureW, int textureH, int color) {
        if (w <= 0 || h <= 0 || (color >>> 24) == 0) return;
        Identifier texture = TEXTURES.computeIfAbsent(path, value -> Identifier.fromNamespaceAndPath("cubeon-client", value));
        context.blit(RenderPipelines.GUI_TEXTURED, texture, x, y, (float)u, (float)v,
                w, h, regionW, regionH, textureW, textureH, color);
    }
}

