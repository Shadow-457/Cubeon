package com.cubeon.client.ui;

/** Cubeon's black/green palette and small, Minecraft-free drawing primitives. */
public final class ClientUi {
    public static final int BACKDROP = 0xA0050505, SURFACE = 0xF80B0D0A,
            SURFACE_HI = 0xFF131711, BORDER = 0xFF242B1E, BORDER_HI = 0xFF39422F,
            TEXT = 0xFFDDF6D5, DIM = 0xFF9DB394, FAINT = 0xFF68755F,
            ACCENT = 0xFF46BA34, ACCENT_HI = 0xFF5FD24B,
            SELECTED = 0xFF142710, ON_ACCENT = 0xFF04120A;
    public interface Canvas {
        void fill(int x0, int y0, int x1, int y1, int color);
        void text(String value, int centerX, int y, int color);
        String translate(String key);
        default int width(String value) { return value.length() * 5; }
        default boolean textures() { return false; }
        default void image(String path, int x, int y, int w, int h, int u, int v,
                           int regionW, int regionH, int textureW, int textureH, int color) { }
    }
    private ClientUi() { }
    public static int alpha(int color, float opacity) {
        return (color & 0xFFFFFF) | (Math.round((color >>> 24) * opacity) << 24);
    }
    public static int mix(int from, int to, float amount) {
        int result = 0;
        for (int shift = 0; shift < 32; shift += 8)
            result |= Math.round(((from >>> shift) & 255) * (1 - amount)
                    + ((to >>> shift) & 255) * amount) << shift;
        return result;
    }
    public static void rounded(Canvas canvas, int x, int y, int w, int h, int radius, int color) {
        if (w <= 0 || h <= 0) return;
        int r = Math.max(0, Math.min(radius, Math.min(w, h) / 2));
        if (canvas.textures() && r > 0) {
            // High resolution corner masks keep edges smooth at the physical display scale.
            canvas.fill(x + r, y, x + w - r, y + h, color);
            canvas.fill(x, y + r, x + r, y + h - r, color);
            canvas.fill(x + w - r, y + r, x + w, y + h - r, color);
            for (int dy = 0; dy < 2; dy++) for (int dx = 0; dx < 2; dx++)
                canvas.image("textures/ui/rounded.png", x + dx * (w - r), y + dy * (h - r), r, r,
                        dx * 64, dy * 64, 64, 64, 128, 128, color);
            return;
        }
        canvas.fill(x, y + r, x + w, y + h - r, color);
        for (int row = 0; row < r; row++) {
            double dy = r - row - .5;
            int inset = (int)Math.ceil(r - Math.sqrt(r * r - dy * dy));
            canvas.fill(x + inset, y + row, x + w - inset, y + row + 1, color);
            canvas.fill(x + inset, y + h - row - 1, x + w - inset, y + h - row, color);
        }
    }
    public static void panel(Canvas canvas, int x, int y, int w, int h, int radius,
                             int fill, int border, float fade) {
        rounded(canvas, x, y, w, h, radius, alpha(border, fade));
        rounded(canvas, x + 1, y + 1, w - 2, h - 2, radius - 1, alpha(fill, fade));
    }
    public static String fit(Canvas canvas, String value, int width) {
        if (canvas.width(value) <= width) return value;
        int end = value.length();
        while (end > 0 && canvas.width(value.substring(0, end) + "…") > width) end--;
        return end == 0 ? "" : value.substring(0, end) + "…";
    }
    public static void left(Canvas canvas, String value, int x, int y, int color) {
        canvas.text(value, x + canvas.width(value) / 2, y, color);
    }
    public static void button(Canvas canvas, int x, int y, int w, int h, String label,
                              float hover, boolean primary, float fade) {
        int fill = primary ? mix(ACCENT, ACCENT_HI, hover) : mix(SURFACE_HI, SELECTED, hover);
        panel(canvas, x, y, w, h, Math.min(6, h / 2), fill,
                primary ? fill : mix(BORDER, ACCENT, hover), fade);
        canvas.text(fit(canvas, label, w - 12), x + w / 2, y + (h - 9) / 2,
                alpha(primary ? ON_ACCENT : mix(DIM, TEXT, hover), fade));
    }
    public static void toggle(Canvas canvas, int x, int y, boolean on, float fade) {
        rounded(canvas, x, y, 24, 12, 6, alpha(on ? ACCENT : BORDER_HI, fade));
        rounded(canvas, x + (on ? 14 : 2), y + 2, 8, 8, 4,
                alpha(on ? ON_ACCENT : DIM, fade));
    }
    public static void mark(Canvas canvas, int x, int y, float fade) {
        if (canvas.textures()) {
            canvas.image("textures/ui/icons.png", x, y, 18, 18, 1280, 0, 128, 128, 1408, 128,
                    alpha(0xFFFFFFFF, fade));
            return;
        }
        rounded(canvas, x, y, 18, 18, 5, alpha(SELECTED, fade));
        canvas.fill(x + 5, y + 5, x + 13, y + 7, alpha(ACCENT_HI, fade));
        canvas.fill(x + 5, y + 7, x + 7, y + 11, alpha(ACCENT_HI, fade));
        canvas.fill(x + 5, y + 11, x + 13, y + 13, alpha(ACCENT_HI, fade));
    }
}
