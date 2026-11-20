package com.cubeon.forge;

import com.cubeon.client.emotes.EmoteWheel;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.Gui;
import net.minecraft.client.renderer.GlStateManager;
import net.minecraft.client.renderer.Tessellator;
import net.minecraft.client.renderer.WorldRenderer;
import net.minecraft.client.renderer.vertex.DefaultVertexFormats;
import net.minecraft.util.ResourceLocation;
import org.lwjgl.opengl.GL11;

/**
 * 1.8.9 drawing backend for the shared Cubeon screens, matching the Fabric adapters:
 * same quads, same colour channels, same texture regions.
 */
final class ForgeCanvas implements EmoteWheel.Canvas {
    private static final int GL_QUADS = 7;

    @Override public void fill(int x0, int y0, int x1, int y1, int color) {
        Gui.drawRect(x0, y0, x1, y1, color);
    }

    @Override public boolean textures() { return true; }

    @Override public void image(String path, int x, int y, int w, int h, int u, int v,
                                int regionW, int regionH, int textureW, int textureH, int color) {
        if (w <= 0 || h <= 0 || (color >>> 24) == 0 || textureW <= 0 || textureH <= 0) return;
        Minecraft.getMinecraft().getTextureManager().bindTexture(new ResourceLocation("cubeon-client", path));
        // Pixel artwork: never smooth the Cubeon icons or rim masks.
        GL11.glTexParameteri(GL11.GL_TEXTURE_2D, GL11.GL_TEXTURE_MIN_FILTER, GL11.GL_NEAREST);
        GL11.glTexParameteri(GL11.GL_TEXTURE_2D, GL11.GL_TEXTURE_MAG_FILTER, GL11.GL_NEAREST);
        GlStateManager.color(((color >> 16) & 255) / 255.0F, ((color >> 8) & 255) / 255.0F,
                (color & 255) / 255.0F, ((color >>> 24) & 255) / 255.0F);
        GlStateManager.enableBlend();
        GlStateManager.tryBlendFuncSeparate(770, 771, 1, 0);
        float u0 = u / (float) textureW, u1 = (u + regionW) / (float) textureW;
        float v0 = v / (float) textureH, v1 = (v + regionH) / (float) textureH;
        Tessellator tessellator = Tessellator.getInstance();
        WorldRenderer renderer = tessellator.getWorldRenderer();
        renderer.begin(GL_QUADS, DefaultVertexFormats.POSITION_TEX);
        renderer.pos(x, y + h, 0).tex(u0, v1).endVertex();
        renderer.pos(x + w, y + h, 0).tex(u1, v1).endVertex();
        renderer.pos(x + w, y, 0).tex(u1, v0).endVertex();
        renderer.pos(x, y, 0).tex(u0, v0).endVertex();
        tessellator.draw();
        GlStateManager.color(1.0F, 1.0F, 1.0F, 1.0F);
        GlStateManager.disableBlend();
    }

    @Override public void text(String value, int x, int y, int color) {
        Minecraft.getMinecraft().fontRendererObj.drawString(value,
                x - Minecraft.getMinecraft().fontRendererObj.getStringWidth(value) / 2, y, color);
    }

    @Override public int width(String value) { return Minecraft.getMinecraft().fontRendererObj.getStringWidth(value); }

    @Override public String translate(String key) { return Lang8.translate(key); }
}
