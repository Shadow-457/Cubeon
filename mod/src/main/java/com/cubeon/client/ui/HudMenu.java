package com.cubeon.client.ui;

import java.util.Arrays;

/** Shared card layout, drawing and keyboard/pointer selection for all eight native screens. */
public final class HudMenu {
    public static final int EMOTES = 15, HEALTH = 16, ANIMATIONS = 17, WING_DEPTH = 18, OTHER_COSMETICS = 19, RESET = 20, DONE = 21, NONE = -1;
    public interface Settings {
        boolean visible(int overlay);
        float scale(int overlay);
        boolean health();
        boolean animations();
        boolean wingDepth();
        boolean otherCosmetics();
    }
    public record Rect(int x, int y, int w, int h) {
        public boolean contains(double px, double py) { return px >= x && px < x + w && py >= y && py < y + h; }
    }
    private static final String[] LABELS = {"fps", "keys", "armor", "ping", "cps"};
    private final Rect[] controls = new Rect[DONE + 1];
    private final Rect[] cards = new Rect[5];
    private final float[] glow = new float[DONE + 1];
    private int width, height, x, y, panelWidth, panelHeight, selection = NONE;
    private boolean compact;
    private int rightX, rightWidth, contentTop;
    private double lastX = Double.NaN, lastY = Double.NaN;
    private final long opened = System.nanoTime();
    private long lastFrame = opened;
    public void layout(int w, int h) {
        if (w == width && h == height) return;
        width = w; height = h; panelWidth = Math.min(600, w - 24); panelHeight = Math.min(352, h - 16);
        x = (w - panelWidth) / 2; y = (h - panelHeight) / 2;
        compact = panelWidth < 496 || panelHeight < 304;
        int gap = compact ? 2 : 6;
        contentTop = y + (compact ? 30 : 68);
        int leftWidth = compact ? panelWidth - 24 : (panelWidth - 42) * 3 / 5;
        int rowHeight = compact ? (panelHeight - 136) / 5 : 34;
        for (int i = 0; i < cards.length; i++) {
            int top = contentTop + i * (rowHeight + gap), left = x + 12;
            cards[i] = new Rect(left, top, leftWidth, rowHeight);
            int buttonWidth = compact ? 42 : 48, buttonHeight = compact ? 14 : 22;
            int buttonTop = top + (rowHeight - buttonHeight) / 2;
            controls[i * 3] = new Rect(left, top, leftWidth - 2 * buttonWidth - 12, rowHeight);
            controls[i * 3 + 1] = new Rect(left + leftWidth - 2 * buttonWidth - 8, buttonTop, buttonWidth, buttonHeight);
            controls[i * 3 + 2] = new Rect(left + leftWidth - buttonWidth - 4, buttonTop, buttonWidth, buttonHeight);
        }
        rightX = x + 24 + leftWidth; rightWidth = panelWidth - leftWidth - 36;
        if (compact) {
            int bottom = contentTop + 5 * (rowHeight + gap) + 2;
            int cell = (panelWidth - 28) / 3;
            int[] ids = {EMOTES, HEALTH, ANIMATIONS, WING_DEPTH, OTHER_COSMETICS};
            for (int i = 0; i < ids.length; i++)
                controls[ids[i]] = new Rect(x + 12 + (i % 3) * (cell + 2), bottom + (i / 3) * 22, cell, 20);
        } else {
            controls[ANIMATIONS] = new Rect(rightX, contentTop, rightWidth, 34);
            controls[WING_DEPTH] = new Rect(rightX, contentTop + 40, rightWidth, 34);
            controls[OTHER_COSMETICS] = new Rect(rightX, contentTop + 80, rightWidth, 34);
            controls[HEALTH] = new Rect(rightX, contentTop + 148, rightWidth, 26);
            controls[EMOTES] = new Rect(rightX, contentTop + 180, rightWidth, 26);
        }
        int footerY = y + panelHeight - 44;
        int footerWidth = (panelWidth - 30) / 2;
        controls[RESET] = new Rect(x + 12, footerY, footerWidth, 24);
        controls[DONE] = new Rect(x + 18 + footerWidth, footerY, footerWidth, 24);
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
        if (panelHeight >= 304)
            ClientUi.left(canvas, canvas.translate("cubeonclient.hud.subtitle"), x + 38, y + 29, ClientUi.alpha(ClientUi.DIM, fade));
        if (!compact) {
            ClientUi.left(canvas, canvas.translate("cubeonclient.hud.section_overlays"), x + 12, y + 51, ClientUi.alpha(ClientUi.FAINT, fade));
            ClientUi.left(canvas, canvas.translate("cubeonclient.hud.section_cosmetics"), rightX, y + 51, ClientUi.alpha(ClientUi.FAINT, fade));
            ClientUi.left(canvas, canvas.translate("cubeonclient.hud.section_tools"), rightX, contentTop + 130, ClientUi.alpha(ClientUi.FAINT, fade));
        }
        for (int i = 0; i < cards.length; i++) {
            Rect card = cards[i], toggle = controls[i * 3];
            float hover = Math.max(glow[i * 3], Math.max(glow[i * 3 + 1], glow[i * 3 + 2]));
            ClientUi.panel(canvas, card.x, card.y, card.w, card.h, 6, ClientUi.SURFACE_HI,
                    ClientUi.mix(ClientUi.BORDER, ClientUi.ACCENT, hover), fade);
            ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate("cubeonclient.hud." + LABELS[i]), toggle.w - 44),
                    card.x + 8, card.y + (card.h - 9) / 2, ClientUi.alpha(ClientUi.TEXT, fade));
            ClientUi.toggle(canvas, toggle.x + toggle.w - 28, card.y + (card.h - 12) / 2, settings.visible(i), fade);
            action(canvas, i * 3 + 1, canvas.translate("cubeonclient.menu.move"), false, fade);
            action(canvas, i * 3 + 2, Math.round(settings.scale(i) * 100) + "%", false, fade);
        }
        utility(canvas, HEALTH, "cubeonclient.hud.health", settings.health(), fade);
        utility(canvas, ANIMATIONS, "cubeonclient.hud.animations", settings.animations(), fade);
        utility(canvas, WING_DEPTH, "cubeonclient.hud.wing_depth", settings.wingDepth(), fade);
        utility(canvas, OTHER_COSMETICS, "cubeonclient.hud.other_cosmetics", settings.otherCosmetics(), fade);
        action(canvas, EMOTES, canvas.translate("cubeonclient.hud.emotes"), false, fade);
        action(canvas, RESET, canvas.translate("cubeonclient.hud.reset"), false, fade);
        action(canvas, DONE, canvas.translate("cubeonclient.emotes.done"), true, fade);
        String hint = selection == RESET ? "cubeonclient.hud.reset_hint"
                : selection == WING_DEPTH ? "cubeonclient.hud.wing_depth_hint"
                : selection == OTHER_COSMETICS ? "cubeonclient.hud.other_cosmetics_hint"
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
        String labelKey = compact ? key + "_compact" : key;
        ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate(labelKey), rect.w - 38), rect.x + 8,
                rect.y + (rect.h - 9) / 2, ClientUi.alpha(ClientUi.DIM, fade));
        ClientUi.toggle(canvas, rect.x + rect.w - 32, rect.y + (rect.h - 12) / 2, value, fade);
    }
}
