package com.cubeon.client;

import net.minecraft.client.gui.Font;

/**
 * The two drawing primitives the mod menu needs, in a form that works on both
 * Minecraft eras.
 *
 * <p>1.20-1.21 draws a screen with {@code Screen.render(GuiGraphics, ...)}; 26.x
 * replaced that with {@code Screen.extractRenderState(GuiGraphicsExtractor,
 * ...)}, and the two graphics objects share no type. The FIRST build of this
 * menu dodged that whole problem by using only vanilla Button/EditBox widgets -
 * which compiled everywhere and looked like a Minecraft options screen rather
 * than a mod menu.
 *
 * <p>So it is done properly. The menu paints its own panel, and only these two
 * calls differ per bracket (each {@code java-overlay-<key>} has a
 * {@code MenuPaint} that adapts its own graphics type). Everything above this -
 * layout, colours, rounded corners, hover highlighting - is shared, because
 * {@link MenuPainter} builds every shape out of plain rectangles.
 */
public interface MenuPaint {

    /** Fills a rectangle, top-left to bottom-right, opaque. */
    void fill(int x1, int y1, int x2, int y2, int argb);

    /** Draws a left-aligned string; returns the x it would end at. */
    int text(Font font, String line, int x, int y, int argb, boolean shadow);
}