package com.cubeon.client.ui;

/** Compact charcoal controls shared by the in-game menus. */
public final class MenuUi {
    public static final int SURFACE = 0xFF12161B, SURFACE_HI = 0xFF1A2027,
            SELECTED = 0xFF24321D, BORDER = 0xFF303943, BORDER_HI = 0xFF537A2B,
            TEXT = 0xFFE6EDF3, DIM = 0xFFA8B3C0, FAINT = 0xFF798696,
            ACCENT = 0xFF83C13D, ACCENT_HI = 0xFFA6D065, ON_ACCENT = 0xFF15210D;

    private MenuUi() { }

    public static void panel(ClientUi.Canvas canvas, int x, int y, int w, int h, int radius,
                             int fill, int border, float fade) {
        if (w <= 0 || h <= 0) return;
        // Filled panels use matching rounded silhouettes. Transparent calls are outlines only.
        if ((fill >>> 24) == 0) {
            int rim = ClientUi.alpha(border, fade);
            int r = Math.max(0, Math.min(6, Math.min(radius, Math.min(w, h) / 2)));
            canvas.fill(x + r, y, x + w - r, y + 1, rim);
            canvas.fill(x + r, y + h - 1, x + w - r, y + h, rim);
            canvas.fill(x, y + r, x + 1, y + h - r, rim);
            canvas.fill(x + w - 1, y + r, x + w, y + h - r, rim);
            if (canvas.textures() && r > 0) {
                for (int dy = 0; dy < 2; dy++) for (int dx = 0; dx < 2; dx++)
                    canvas.image("textures/ui/rounded-rims.png", x + dx * (w - r), y + dy * (h - r), r, r,
                            (r - 1) * 128 + dx * 64, dy * 64, 64, 64, 2048, 128, rim);
            } else for (int row = 0; row < r; row++) {
                double dy = r - row - .5;
                int inset = (int)Math.ceil(r - Math.sqrt(r * r - dy * dy));
                int inner = row == 0 ? w / 2 : Math.max(inset + 1,
                        1 + (int)Math.ceil(r - 1 - Math.sqrt((r - 1) * (r - 1) - dy * dy)));
                for (int cy : new int[]{y + row, y + h - row - 1}) {
                    canvas.fill(x + inset, cy, x + inner, cy + 1, rim);
                    canvas.fill(x + w - inner, cy, x + w - inset, cy + 1, rim);
                }
            }
            return;
        }
        int r = Math.max(0, Math.min(6, Math.min(radius, Math.min(w, h) / 2)));
        ClientUi.rounded(canvas, x, y, w, h, r, ClientUi.alpha(border, fade));
        if (w > 2 && h > 2)
            ClientUi.rounded(canvas, x + 1, y + 1, w - 2, h - 2, Math.max(0, r - 1), ClientUi.alpha(fill, fade));
    }

    public static void button(ClientUi.Canvas canvas, int x, int y, int w, int h, String label,
                              float hover, boolean primary, float fade) {
        int fill = ClientUi.mix(primary ? SELECTED : SURFACE_HI, SELECTED, hover);
        panel(canvas, x, y, w, h, Math.min(6, h / 2), fill,
                primary ? BORDER_HI : ClientUi.mix(BORDER, BORDER_HI, hover), fade);
        canvas.text(ClientUi.fit(canvas, label, w - 12), x + w / 2, y + (h - 9) / 2,
                ClientUi.alpha(primary ? TEXT : ClientUi.mix(DIM, TEXT, hover), fade));
    }

    public static void toggle(ClientUi.Canvas canvas, int x, int y, boolean on, float fade) {
        toggle(canvas, x, y, on ? 1 : 0, fade);
    }

    public static void toggle(ClientUi.Canvas canvas, int x, int y, float position, float fade) {
        ClientUi.rounded(canvas, x, y, 24, 12, 6,
                ClientUi.alpha(ClientUi.mix(BORDER, ACCENT, position), fade));
        ClientUi.rounded(canvas, x + 2 + Math.round(position * 12), y + 2, 8, 8, 4,
                ClientUi.alpha(TEXT, fade));
    }

    /** Only drawing moves; callers use the same offset for their hit targets. */
    public static ClientUi.Canvas transform(ClientUi.Canvas canvas, int dy, float opacity) {
        if (dy == 0 && opacity == 1) return canvas;
        return new ClientUi.Canvas() {
            public void fill(int x0, int y0, int x1, int y1, int color) {
                canvas.fill(x0, y0 + dy, x1, y1 + dy, ClientUi.alpha(color, opacity));
            }
            public void text(String value, int x, int y, int color) {
                canvas.text(value, x, y + dy, ClientUi.alpha(color, opacity));
            }
            public void textScaled(String value, int x, int y, int color, float scale) {
                canvas.textScaled(value, x, y + dy, ClientUi.alpha(color, opacity), scale);
            }
            public int width(String value) { return canvas.width(value); }
            public String translate(String key) { return canvas.translate(key); }
            public boolean textures() { return canvas.textures(); }
            public void image(String path, int x, int y, int w, int h, int u, int v,
                              int rw, int rh, int tw, int th, int color) {
                canvas.image(path, x, y + dy, w, h, u, v, rw, rh, tw, th,
                        ClientUi.alpha(color, opacity));
            }
        };
    }

    public static void mark(ClientUi.Canvas canvas, int x, int y, float fade) {
        if (canvas.textures()) {
            canvas.image("icon.png", x, y, 20, 20, 0, 0, 128, 128, 128, 128, ClientUi.alpha(0xFFFFFFFF, fade));
        } else {
            canvas.fill(x + 4, y + 4, x + 16, y + 16, ClientUi.alpha(0xFF83C13D, fade));
        }
    }
}
