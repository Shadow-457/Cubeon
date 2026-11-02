package com.cubeon.client.hud.screen;

import net.minecraft.client.gui.DrawContext;
import net.minecraft.util.Identifier;
import net.minecraft.client.gl.RenderPipelines;
import java.util.HashMap;
import java.util.Map;

/** Native cached texture quads; no image rasterization or upload on the render thread. */
public final class ClientUiDraw {
    private static final Map<String, Identifier> TEXTURES = new HashMap<>();
    public static net.minecraft.client.texture.Sprite effectIcon(net.minecraft.util.Identifier id) { return net.minecraft.client.MinecraftClient.getInstance().getGuiAtlasManager().getSprite(id.withPrefixedPath("mob_effect/")); }
    private ClientUiDraw() { }
    static void image(DrawContext context, String path, int x, int y, int w, int h, int u, int v,
                      int regionW, int regionH, int textureW, int textureH, int color) {
        if (w <= 0 || h <= 0 || (color >>> 24) == 0) return;
        Identifier texture = TEXTURES.computeIfAbsent(path, value -> Identifier.tryParse("cubeon-client:" + value));
        context.drawTexture(RenderPipelines.GUI_TEXTURED, texture, x, y, (float)u, (float)v,
                w, h, regionW, regionH, textureW, textureH, color);
    }
    public static void effect(DrawContext context, net.minecraft.client.texture.Sprite sprite, int x, int y) { context.drawSpriteStretched(net.minecraft.client.gl.RenderPipelines.GUI_TEXTURED, sprite, x, y, 10, 10); }
}
