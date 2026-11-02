package com.cubeon.client.hud.screen;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.network.chat.Component;

import com.cubeon.client.ui.ClientUi;

/** Native renderer over Cubeon's bounded live-toast queue. */
public final class FriendsToastRenderer {
    private FriendsToastRenderer() { }
    public static void render(GuiGraphicsExtractor graphics, net.minecraft.client.Minecraft client, int w, int h) {
        com.cubeon.client.ui.ClientToasts.render(canvas(graphics, client), w, h);
    }
    private static ClientUi.Canvas canvas(GuiGraphicsExtractor graphics, net.minecraft.client.Minecraft client) { return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) { graphics.fill(x0, y0, x1, y1, color); }
            public boolean textures() { return true; }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int regionW, int regionH, int textureW, int textureH, int color) {
                ClientUiDraw.image(graphics, path, x, y, w, h, u, v, regionW, regionH, textureW, textureH, color);
            }
            public void text(String value, int x, int y, int color) {
                var label = ClientUiFont.text(value);
                graphics.text(client.font, label, x - client.font.width(label) / 2, y, color, false);
            }
            public int width(String value) { return client.font.width(ClientUiFont.text(value)); }
            public String translate(String key) { return Component.translatable(key).getString(); }
        }; }
}
