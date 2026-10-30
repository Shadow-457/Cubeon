package com.cubeon.client.ui;

import java.util.Arrays;

/** Shared card layout, drawing and keyboard/pointer selection for all eight native screens. */
public final class HudMenu {
    public static final int EMOTES = 15, HEALTH = 16, ANIMATIONS = 17, RESET = 18, DONE = 19, NONE = -1;
    public interface Settings {
        boolean visible(int overlay);
        float scale(int overlay);
        boolean health();
        boolean animations();
    }
    public record Rect(int x, int y, int w, int h) {
        public boolean contains(double px, double py) { return px >= x && px < x + w && py >= y && py < y + h; }
    }
    private static final String[] LABELS = {"fps", "keys", "armor", "ping", "cps"};
    private final Rect[] controls = new Rect[20];
    private final Rect[] cards = new Rect[6];
    private final float[] glow = new float[20];
    private int width, height, x, y, panelWidth, panelHeight, selection = NONE;
    private double lastX = Double.NaN, lastY = Double.NaN;
    private final long opened = System.nanoTime();
    private long lastFrame = opened;
    public void layout(int w, int h) {
        if (w == width && h == height) return;
        width = w; height = h; panelWidth = Math.min(480, w - 24); panelHeight = Math.min(304, h - 16);
        x = (w - panelWidth) / 2; y = (h - panelHeight) / 2;
        boolean compact = panelHeight < 272;
        int header = compact ? 36 : 52, gap = compact ? 4 : 8;
        int utility = compact ? 22 : 28, footer = compact ? 28 : 34;
        int tileHeight = (panelHeight - header - utility - footer - 4 * gap - 12) / 3;
        int tileWidth = (panelWidth - 24 - gap) / 2;
        for (int i = 0; i < cards.length; i++) {
            int left = x + 12 + i % 2 * (tileWidth + gap), top = y + header + i / 2 * (tileHeight + gap);
            cards[i] = new Rect(left, top, tileWidth, tileHeight);
            if (i == 5) { controls[EMOTES] = cards[i]; continue; }
            int buttonHeight = compact ? 14 : 18, buttonTop = top + tileHeight - buttonHeight - 4;
            int buttonWidth = (tileWidth - 22) / 2;
            controls[i * 3] = new Rect(left, top, tileWidth, buttonTop - top);
            controls[i * 3 + 1] = new Rect(left + 8, buttonTop, buttonWidth, buttonHeight);
            controls[i * 3 + 2] = new Rect(left + 14 + buttonWidth, buttonTop, buttonWidth, buttonHeight);
        }
        int bottom = y + header + tileHeight * 3 + gap * 3;
        controls[HEALTH] = new Rect(x + 12, bottom, tileWidth, utility);
        controls[ANIMATIONS] = new Rect(x + 12 + tileWidth + gap, bottom, tileWidth, utility);
        controls[RESET] = new Rect(x + 12, bottom + utility + gap, tileWidth, footer);
        controls[DONE] = new Rect(x + 12 + tileWidth + gap, bottom + utility + gap, tileWidth, footer);
        Arrays.fill(glow, 0);
    }
    public Rect control(int action) { return controls[action]; }
    public int hit(double px, double py) {
        for (int i = 0; i < controls.length; i++) if (controls[i] != null && controls[i].contains(px, py)) return i;
        return NONE;
    }
    public int selection() { return selection; }
    public void step(int direction) { selection = selection < 0 ? 0 : Math.floorMod(selection + direction, controls.length); }
    public void render(ClientUi.Canvas canvas, int w, int h, int mouseX, int mouseY, Settings settings) {
        layout(w, h);
        if (lastX != mouseX || lastY != mouseY) { selection = hit(mouseX, mouseY); lastX = mouseX; lastY = mouseY; }
        long now = System.nanoTime();
        float ease = 1 - (float)Math.exp(-Math.min(.1f, (now - lastFrame) / 1e9f) * 18); lastFrame = now;
        float fade = Math.min(1, (now - opened) / 140_000_000f);
        for (int i = 0; i < glow.length; i++) glow[i] += ((selection == i ? 1 : 0) - glow[i]) * ease;
        ClientUi.rounded(canvas, x + 2, y + 3, panelWidth, panelHeight, 12, ClientUi.alpha(0x50000000, fade));
        ClientUi.panel(canvas, x, y, panelWidth, panelHeight, 12, ClientUi.SURFACE, ClientUi.BORDER_HI, fade);
        ClientUi.mark(canvas, x + 12, y + 10, fade);
        ClientUi.left(canvas, canvas.translate("cubeonclient.menu.title"), x + 38, y + 12, ClientUi.alpha(ClientUi.TEXT, fade));
        if (panelHeight >= 272)
            ClientUi.left(canvas, canvas.translate("cubeonclient.hud.subtitle"), x + 38, y + 29, ClientUi.alpha(ClientUi.DIM, fade));
        for (int i = 0; i < cards.length; i++) {
            Rect card = cards[i];
            float hover = i == 5 ? glow[EMOTES] : Math.max(glow[i * 3], Math.max(glow[i * 3 + 1], glow[i * 3 + 2]));
            ClientUi.panel(canvas, card.x, card.y, card.w, card.h, 7, ClientUi.SURFACE_HI,
                    ClientUi.mix(ClientUi.BORDER, ClientUi.ACCENT, hover), fade);
            String label = canvas.translate("cubeonclient.hud." + (i == 5 ? "emotes" : LABELS[i]));
            ClientUi.left(canvas, ClientUi.fit(canvas, label, card.w - (i == 5 ? 16 : 48)), card.x + 8,
                    card.y + 6, ClientUi.alpha(ClientUi.TEXT, fade));
            if (i == 5) {
                canvas.text(ClientUi.fit(canvas, canvas.translate("cubeonclient.hud.open_wheel"), card.w - 18),
                        card.x + card.w / 2, card.y + card.h - 15, ClientUi.alpha(ClientUi.ACCENT_HI, fade));
                continue;
            }
            ClientUi.toggle(canvas, card.x + card.w - 32, card.y + 5, settings.visible(i), fade);
            action(canvas, i * 3 + 1, canvas.translate("cubeonclient.menu.move"), false, fade);
            action(canvas, i * 3 + 2, Math.round(settings.scale(i) * 100) + "%", false, fade);
        }
        utility(canvas, HEALTH, "cubeonclient.hud.health", settings.health(), fade);
        utility(canvas, ANIMATIONS, "cubeonclient.hud.animations", settings.animations(), fade);
        action(canvas, RESET, canvas.translate("cubeonclient.hud.reset"), false, fade);
        action(canvas, DONE, canvas.translate("cubeonclient.emotes.done"), true, fade);
        String hint = selection == RESET ? "cubeonclient.hud.reset_hint"
                : selection >= 0 && selection < EMOTES && selection % 3 == 2 ? "cubeonclient.hud.size_hint"
                : "cubeonclient.hud.keyboard_hint";
        canvas.text(ClientUi.fit(canvas, canvas.translate(hint), panelWidth - 24), x + panelWidth / 2,
                y + panelHeight - 11, ClientUi.alpha(ClientUi.DIM, fade));
    }
    private void action(ClientUi.Canvas canvas, int id, String text, boolean primary, float fade) {
        Rect rect = controls[id];
        ClientUi.button(canvas, rect.x, rect.y, rect.w, rect.h, text, glow[id], primary, fade);
    }
    private void utility(ClientUi.Canvas canvas, int id, String key, boolean value, float fade) {
        Rect rect = controls[id];
        ClientUi.panel(canvas, rect.x, rect.y, rect.w, rect.h, 6, ClientUi.SURFACE_HI,
                ClientUi.mix(ClientUi.BORDER, ClientUi.ACCENT, glow[id]), fade);
        ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate(key), rect.w - 44), rect.x + 8,
                rect.y + (rect.h - 9) / 2, ClientUi.alpha(ClientUi.DIM, fade));
        ClientUi.toggle(canvas, rect.x + rect.w - 32, rect.y + (rect.h - 12) / 2, value, fade);
    }
}
