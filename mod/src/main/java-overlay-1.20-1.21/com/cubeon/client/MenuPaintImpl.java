package com.cubeon.client;

import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphics;

/** The 1.20-1.21 half of {@link MenuPaint}. */
public final class MenuPaintImpl implements MenuPaint {

    private final GuiGraphics graphics;

    public MenuPaintImpl(GuiGraphics graphics) {
        this.graphics = graphics;
    }

    @Override
    public void fill(int x1, int y1, int x2, int y2, int argb) {
        graphics.fill(x1, y1, x2, y2, argb);
    }

    @Override
    public int text(Font font, String line, int x, int y, int argb, boolean shadow) {
        return graphics.drawString(font, line, x, y, argb, shadow);
    }
}
