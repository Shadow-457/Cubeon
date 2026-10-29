package com.cubeon.client.emotes;

import java.util.ArrayList;
import java.util.List;

/** Shared wheel drawing and hit testing; the eight screens only adapt native APIs. */
public final class EmoteWheel {
    public interface Canvas {
        void fill(int x0, int y0, int x1, int y1, int color);
        void text(String text, int centerX, int y, int color);
        String translate(String key);
    }
    public static final int STOP = -1, NONE = -2, TOGGLE = -3;
    private record Span(int x, int y, int end, int kind) { }
    private final List<Span> spans = new ArrayList<>();
    private final float[] glow = new float[6];
    private int cx, cy, radius, selection = NONE;
    private double lastX = Double.NaN, lastY = Double.NaN;
    private final long opened = System.nanoTime();
    private long lastFrame = opened;

    public void layout(int width, int height) {
        cx = width / 2; cy = height / 2 - 5;
        int next = Math.max(24, Math.min(116, Math.min((width - 24) / 2, (height - 92) / 2)));
        if (radius == next) return;
        radius = next; spans.clear();
        // Cache circle rasterization once per size. Each row is a handful of
        // runs; there is no per-frame pixel rasterization or texture upload.
        for (int y = -radius; y <= radius; y++) {
            int start = -radius, previous = kind(start, y);
            for (int x = start + 1; x <= radius + 1; x++) {
                int current = x > radius ? NONE : kind(x, y);
                if (current != previous) {
                    if (previous != NONE) spans.add(new Span(start, y, x, previous));
                    start = x; previous = current;
                }
            }
        }
    }
    private int sector(double x, double y) {
        double angle = Math.atan2(y, x) + Math.PI / 2 + Math.PI / 6;
        return (int)Math.floor((angle + Math.PI * 2) % (Math.PI * 2) / (Math.PI / 3));
    }
    private int kind(double x, double y) {
        double distance = Math.hypot(x, y);
        if (distance > radius) return NONE;
        if (distance < radius * .37) return 6;
        if (distance < radius * .40) return 7;
        int slot = sector(x, y);
        if (distance > radius - 2) return slot + 8;
        double angle = Math.atan2(y, x) + Math.PI / 2;
        double edge = Math.abs(Math.sin(angle - (slot * Math.PI / 3 - Math.PI / 6))) * distance;
        double other = Math.abs(Math.sin(angle - (slot * Math.PI / 3 + Math.PI / 6))) * distance;
        return Math.min(edge, other) < 1.1 ? 7 : slot;
    }
    public int hit(double x, double y) {
        double distance = Math.hypot(x - cx, y - cy);
        if (distance < radius * .37) return STOP;
        if (distance <= radius && distance >= radius * .40) return sector(x - cx, y - cy);
        if (x >= cx - 74 && x <= cx + 74 && y >= cy + radius + 17 && y < cy + radius + 33) return TOGGLE;
        return NONE;
    }
    public int selection() { return selection; }
    public void focus(int slot) { selection = slot >= 0 && slot < 6 ? slot : STOP; }
    public void step(int direction) { focus(selection < 0 ? 0 : Math.floorMod(selection + direction, 6)); }
    public void render(Canvas canvas, int width, int height, int mouseX, int mouseY,
                       boolean enabled, boolean synced) {
        layout(width, height);
        if (mouseX != lastX || mouseY != lastY) {
            selection = hit(mouseX, mouseY); lastX = mouseX; lastY = mouseY;
        }
        long now = System.nanoTime();
        float dt = Math.min(.1f, (now - lastFrame) / 1_000_000_000f); lastFrame = now;
        float fade = Math.min(1, (now - opened) / 140_000_000f);
        float ease = 1 - (float)Math.exp(-dt * 18);
        for (int i = 0; i < glow.length; i++) glow[i] += ((selection == i && enabled ? 1 : 0) - glow[i]) * ease;
        for (Span span : spans) {
            int kind = span.kind();
            int color;
            if (kind < 6) color = mix(kind % 2 == 0 ? 0xED1B2432 : 0xED202B3A, 0xF14A3929, glow[kind]);
            else if (kind == 6) color = selection == STOP ? 0xF12D3644 : 0xF1151C28;
            else if (kind == 7) color = 0xF1323E50;
            else color = mix(0xF13B495B, 0xFFFFC77D, glow[kind - 8]);
            canvas.fill(cx + span.x(), cy + span.y(), cx + span.end(), cy + span.y() + 1, alpha(color, fade));
        }
        canvas.text(canvas.translate("cubeonclient.menu.emotes"), cx, cy - radius - 22, alpha(0xFFF3F5FA, fade));
        for (int i = 0; i < 6; i++) {
            double angle = i * Math.PI / 3 - Math.PI / 2;
            int x = cx + (int)Math.round(Math.cos(angle) * radius * .72);
            int y = cy + (int)Math.round(Math.sin(angle) * radius * .72);
            int color = alpha(enabled ? mix(0xFFB8C6D8, 0xFFFFCD8D, glow[i]) : 0xFF647083, fade);
            icon(canvas, x, y - 7, radius / 116f, i, color);
            canvas.text(canvas.translate("cubeonclient.emote." + EmoteState.NAMES[i]), x, y + 12, color);
        }
        // The dead zone never chooses an emote. Clicking the center stops one.
        int centerColor = alpha(0xFFE0E6F0, fade);
        canvas.fill(cx - 3, cy - 16, cx + 3, cy - 10, alpha(0xFFFFC77D, fade));
        canvas.text(canvas.translate(selection >= 0 ? "cubeonclient.emote." + EmoteState.NAMES[selection]
                : "cubeonclient.emotes.stop"), cx, cy - 2, centerColor);
        canvas.text(canvas.translate(enabled ? "cubeonclient.emotes.choose" : "cubeonclient.state.off"),
                cx, cy + 12, alpha(0xFF8F9FB4, fade));
        canvas.text(canvas.translate(synced ? "cubeonclient.emotes.synced" : "cubeonclient.emotes.local"),
                cx, cy + radius + 4, alpha(synced ? 0xFF96C7B0 : 0xFF98A6BA, fade));
        boolean toggleHover = selection == TOGGLE;
        canvas.fill(cx - 74, cy + radius + 17, cx + 74, cy + radius + 33,
                alpha(toggleHover ? 0xE83B4759 : 0xC8232E3E, fade));
        canvas.text(canvas.translate(enabled ? "cubeonclient.emotes.enabled" : "cubeonclient.emotes.disabled"),
                cx, cy + radius + 21, alpha(toggleHover ? 0xFFFFC77D : 0xFFB5C2D5, fade));
        canvas.text(canvas.translate("cubeonclient.emotes.wheel_hint"), cx, height - 12, alpha(0xFF8997AC, fade));
    }
    private static int alpha(int color, float opacity) {
        return (color & 0xFFFFFF) | (Math.round((color >>> 24) * opacity) << 24);
    }
    private static int mix(int from, int to, float t) {
        int result = 0;
        for (int shift = 0; shift < 32; shift += 8) result |= Math.round(((from >>> shift) & 255) * (1 - t) + ((to >>> shift) & 255) * t) << shift;
        return result;
    }
    private static void line(Canvas canvas, int cx, int cy, float scale, int x0, int y0, int x1, int y1, int color) {
        int steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0));
        int size = Math.max(1, Math.round(scale * 2));
        for (int i = 0; i <= steps; i++) {
            float t = steps == 0 ? 0 : (float)i / steps;
            int x = cx + Math.round((x0 + (x1 - x0) * t) * scale);
            int y = cy + Math.round((y0 + (y1 - y0) * t) * scale);
            canvas.fill(x, y, x + size, y + size, color);
        }
    }
    private static void icon(Canvas canvas, int x, int y, float scale, int emote, int color) {
        int headX = emote == 2 ? 3 : 0, headY = emote == 2 ? -5 : -10;
        int h = Math.max(3, Math.round(scale * 5));
        canvas.fill(x + Math.round((headX - 2) * scale), y + Math.round((headY - 2) * scale),
                x + Math.round((headX - 2) * scale) + h, y + Math.round((headY - 2) * scale) + h, color);
        line(canvas, x, y, scale, headX, headY + 5, 0, 5, color);
        line(canvas, x, y, scale, 0, 5, -5, 13, color);
        line(canvas, x, y, scale, 0, 5, 5, 13, color);
        int[][] arms = {{-4,-3,-10,-12,4,-3,8,5}, {-4,-3,-11,-7,4,-3,10,-11},
                {-2,0,-8,4,4,0,10,4}, {-4,-3,-8,5,4,-3,4,-10},
                {-4,-3,-11,-5,4,-3,11,-5}, {-4,-3,-8,5,4,-3,14,-3}};
        int[] a = arms[emote];
        line(canvas, x, y, scale, a[0], a[1], a[2], a[3], color);
        line(canvas, x, y, scale, a[4], a[5], a[6], a[7], color);
    }
}
