package com.cubeon.client;

import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.network.chat.Component;

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

    /**
     * Draws text through a {@link java.util.FormattedCharSequence}, never a
     * String, and that is not a style choice - it is a
     * {@code NoSuchMethodError} that cost three reports. The game log said it
     * outright:
     *
     * <pre>
     * NoSuchMethodError: int GuiGraphics.drawString(Font, String, int, int, int, boolean)
     *   at MenuPaintImpl.text(MenuPaintImpl.java:22)
     * </pre>
     *
     * <p>1.21 REMOVED the {@code String} overload of drawString. The
     * FormattedCharSequence one is the overload that survives, and 1.20.1 has
     * it as well - so this is the only spelling that works across the whole
     * 1.20-1.21 bracket. Checked with javap in 1.20.1; confirmed by the
     * NoSuchMethodError for the String form in 1.21.
     */
    @Override
    public int text(Font font, String line, int x, int y, int argb, boolean shadow) {
        return graphics.drawString(font,
                Component.literal(line).getVisualOrderText(), x, y, argb, shadow);
    }
}
