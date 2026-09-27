package com.cubeon.client;

import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphicsExtractor;

/**
 * The 26.x half of {@link MenuPaint}.
 *
 * <p>Same two operations, different graphics object: 26.x draws through an
 * extractor and calls {@code text} rather than {@code drawString}. Only opaque
 * fills exist on this era's extractor, which is why the palette is built from
 * fully opaque colours - see {@link MenuPainter} for why that still looks right.
 */
public final class MenuPaintImpl implements MenuPaint {

    private final GuiGraphicsExtractor graphics;

    public MenuPaintImpl(GuiGraphicsExtractor graphics) {
        this.graphics = graphics;
    }

    @Override
    public void fill(int x1, int y1, int x2, int y2, int argb) {
        graphics.fill(x1, y1, x2, y2, argb);
    }

    @Override
    public int text(Font font, String line, int x, int y, int argb, boolean shadow) {
        graphics.text(font, line, x, y, argb, shadow);
        return x + font.width(line);
    }
}
