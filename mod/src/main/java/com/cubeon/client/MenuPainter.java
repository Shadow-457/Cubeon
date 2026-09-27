package com.cubeon.client;

import java.util.List;

import net.minecraft.client.gui.Font;

/**
 * Draws the mod menu's look: a dark panel, red active tab, and a grid of
 * cards with a green "Enabled" bar.
 *
 * <p>Separate from {@link ModuleMenuScreen} on purpose. The screen owns the
 * logic - which modules are visible, what is selected, where the layout sits -
 * and this owns the pixels. Splitting them means the layout maths can be read
 * (and the colours changed) without touching behaviour, and it is why the
 * whole look lives in one place instead of being smeared across
 * {@code setX}/{@code setY} calls on vanilla widgets.
 *
 * <p>Every shape here is built from {@link MenuPaint#fill}, so nothing in this
 * file is version-specific. That is the whole reason the menu can look the same
 * on 1.20.1 and 26.x while their screen pipelines differ completely.
 */
public final class MenuPainter {

    // ---- palette ---------------------------------------------------------
    // Taken from the reference design, not from Minecraft's theme - painting
    // instead of using stock widgets is the entire point. Opaque on purpose:
    // 26.x's extractor has no alpha fill, so a translucent panel would render
    // correctly on one bracket and as a solid block on the other.

    public static final int PAGE_DIM = 0xFF070809;
    public static final int PANEL = 0xFF0F1216;
    public static final int PANEL_EDGE = 0xFF23272E;
    public static final int HEADER_BG = 0xFF16191E;
    public static final int TAB_ON = 0xFFE8453C;
    public static final int TAB_OFF = 0xFF1D212A;
    public static final int TEXT = 0xFFE6E9ED;
    public static final int TEXT_DIM = 0xFF8A929C;
    public static final int TEXT_FAINT = 0xFF6B727C;
    public static final int CARD = 0xFF181C22;
    public static final int CARD_HOVER = 0xFF212832;
    public static final int CARD_EDGE = 0xFF2A303A;
    public static final int ON_BAR = 0xFF15301B;
    public static final int ON_TEXT = 0xFF57CC77;
    public static final int OFF_BAR = 0xFF1A1E24;
    public static final int OFF_TEXT = 0xFF6B727C;
    public static final int SEARCH_BG = 0xFF13161B;
    public static final int CLOSE = 0xFFE8453C;

    /** Corner radius. Small on purpose: at menu scale a bigger radius costs a
     *  lot of fills for very little visible gain. */
    public static final int R = 3;

    private MenuPainter() {
    }

    /** A rounded rectangle, built from axis-aligned fills. */
    public static void roundRect(MenuPaint p, int x, int y, int w, int h, int rgb) {
        int x2 = x + w;
        int y2 = y + h;
        p.fill(x + R, y, x2 - R, y2, rgb);
        p.fill(x, y + R, x2, y2 - R, rgb);
        // Corner bevels: stepped bars, which read as a curve at this radius
        // and cost a handful of fills instead of a texture.
        for (int i = 0; i < R; i++) {
            int inset = i + 1;
            p.fill(x + inset, y + i, x + R + 1, y + i + 1, rgb);
            p.fill(x2 - R - 1, y + i, x2 - inset, y + i + 1, rgb);
            p.fill(x + inset, y2 - i - 1, x + R + 1, y2 - i, rgb);
            p.fill(x2 - R - 1, y2 - i - 1, x2 - inset, y2 - i, rgb);
        }
    }

    /** A 1px border, so a card reads as a card rather than a smudge. */
    public static void outline(MenuPaint p, int x, int y, int w, int h, int rgb) {
        p.fill(x, y, x + w, y + 1, rgb);
        p.fill(x, y + h - 1, x + w, y + h, rgb);
        p.fill(x, y, x + 1, y + h, rgb);
        p.fill(x + w - 1, y, x + w, y + h, rgb);
    }

    /** Shortens a string to fit, adding an ellipsis. Cards are a fixed width. */
    public static String clip(Font font, String text, int maxWidth) {
        if (font.width(text) <= maxWidth) {
            return text;
        }
        String cut = text;
        while (cut.length() > 1 && font.width(cut + "...") > maxWidth) {
            cut = cut.substring(0, cut.length() - 1);
        }
        return cut + "...";
    }
}
