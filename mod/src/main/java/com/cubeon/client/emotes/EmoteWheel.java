package com.cubeon.client.emotes;

import com.cubeon.client.ui.ClientUi;

import java.util.ArrayList;
import java.util.List;
import java.util.Arrays;

/** Shared wheel drawing and hit testing; the eight screens only adapt native APIs. */
public final class EmoteWheel {
    public interface Canvas extends ClientUi.Canvas { }
    public static final int STOP = -1, NONE = -2, TOGGLE = -3, EDIT = -4, DONE = -5;
    private static final int CENTER = 8, GUTTER = 9, RIM = 10;
    private static final int TEXT=0xFFF5F5F5,DIM=0xFFC5C5C5,FAINT=0xFF939393,
            GLASS=0x66343434,GLASS_HI=0xA0787878,BORDER=0x608A8A8A,BORDER_HI=0xB8CCCCCC;
    private record Span(int x, int y, int end, int kind) { }
    private final List<Span> spans = new ArrayList<>();
    private final float[] glow = new float[EmoteFavorites.MAX];
    private int cx, cy, radius, selection = NONE, cachedSlots, cellWidth, rowHeight;
    private String[] favorites;
    private boolean editing;
    private long noticeUntil;
    private String notice = "";
    private double lastX = Double.NaN, lastY = Double.NaN;
    private final long opened = System.nanoTime();
    private long lastFrame = opened;

    public EmoteWheel() { this(null); }
    public EmoteWheel(String[] names) { favorites = EmoteFavorites.normalize(names); }
    public String[] favorites() { return favorites.clone(); }
    public int slots() { return favorites.length; }
    public int choices() { return editing ? EmoteState.NAMES.length : slots(); }
    public int emote(int slot) { return slot >= 0 && slot < slots() ? EmoteState.id(favorites[slot]) : STOP; }
    public boolean editing() { return editing; }
    public void edit(boolean value) {
        editing = value; selection = NONE; noticeUntil = 0; lastX = lastY = Double.NaN;
    }
    public boolean favorite(int emote) {
        return emote >= 0 && emote < EmoteState.NAMES.length
                && Arrays.asList(favorites).contains(EmoteState.NAMES[emote]);
    }
    /** Editing changes config only; it never starts a pose or sends a message. */
    public boolean toggleFavorite(int emote) {
        if (emote < 0 || emote >= EmoteState.NAMES.length) return false;
        List<String> names = new ArrayList<>(Arrays.asList(favorites));
        String name = EmoteState.NAMES[emote];
        if (names.contains(name)) {
            if (names.size() == 1) return notice("cubeonclient.emotes.keep_one");
            names.remove(name);
        } else {
            if (names.size() == EmoteFavorites.MAX) return notice("cubeonclient.emotes.full");
            names.add(name);
        }
        favorites = names.toArray(String[]::new); noticeUntil = 0;
        return true;
    }
    private boolean notice(String key) { notice = key; noticeUntil = System.nanoTime()+2_000_000_000L; return false; }
    private double stepAngle() { return Math.PI*2/slots(); }
    private int libraryTop() { return cy-rowHeight*5/2; }
    private int centerWidth() {
        double inner=radius*.36;
        return Math.max(28,Math.min(72,2*(int)Math.sqrt(Math.max(0,inner*inner-400))-4));
    }
    private boolean centerButton(double x,double y,int top) {
        return x>=cx-centerWidth()/2 && x<cx+(centerWidth()+1)/2 && y>=cy+top && y<cy+top+12;
    }
    public void layout(int width, int height) {
        cx = width / 2; cy = height / 2 - 5;
        cellWidth = Math.min(148, (width-32)/2); rowHeight = Math.min(32, (height-94)/5);
        int next = Math.max(24, Math.min(116, Math.min((width - 24) / 2, (height - 92) / 2)));
        if (radius == next && cachedSlots == slots()) return;
        radius = next; cachedSlots = slots(); spans.clear(); Arrays.fill(glow, 0);
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
        double angle = Math.atan2(y, x) + Math.PI / 2 + stepAngle() / 2;
        return (int)Math.floor((angle + Math.PI * 2) % (Math.PI * 2) / stepAngle());
    }
    private int kind(double x, double y) {
        double distance = Math.hypot(x, y);
        if (distance > radius) return NONE;
        if (distance < radius * .37) return CENTER;
        if (distance < radius * .40) return GUTTER;
        int slot = sector(x, y);
        if (distance > radius - 2) return slot + RIM;
        double angle = Math.atan2(y, x) + Math.PI / 2;
        if (slots() == 1) return slot;
        double within = (angle + stepAngle()/2 + Math.PI*2) % stepAngle();
        return Math.min(within, stepAngle()-within)*distance < 1.1 ? GUTTER : slot;
    }
    public int hit(double x, double y) {
        if (editing) {
            for (int i=0; i<EmoteState.NAMES.length; i++) {
                int left = cx-cellWidth+(i%2)*cellWidth, top = libraryTop()+(i/2)*rowHeight;
                if (x >= left+3 && x < left+cellWidth-3 && y >= top+2 && y < top+rowHeight-2) return i;
            }
            int bottom = libraryTop()+rowHeight*5+20;
            return x >= cx-65 && x <= cx+65 && y >= bottom && y < bottom+20 ? DONE : NONE;
        }
        if(centerButton(x,y,-20)) return TOGGLE;
        if(centerButton(x,y,8)) return EDIT;
        double distance = Math.hypot(x - cx, y - cy);
        if (distance < radius * .37) return STOP;
        if (distance <= radius && distance >= radius * .40) return sector(x - cx, y - cy);
        return NONE;
    }
    public int selection() { return selection; }
    public void focus(int slot) { selection = slot >= 0 && slot < choices() ? slot : STOP; }
    public void step(int direction) { focus(selection < 0 ? 0 : Math.floorMod(selection + direction, choices())); }
    public void render(Canvas canvas, int width, int height, int mouseX, int mouseY,
                       boolean enabled, boolean synced) {
        render(canvas, width, height, mouseX, mouseY, enabled, synced, true);
    }
    public void render(Canvas canvas, int width, int height, int mouseX, int mouseY,
                       boolean enabled, boolean synced, boolean animate) {
        layout(width, height);
        if (mouseX != lastX || mouseY != lastY) {
            selection = hit(mouseX, mouseY); lastX = mouseX; lastY = mouseY;
        }
        long now = System.nanoTime();
        float dt = Math.min(.1f, (now - lastFrame) / 1_000_000_000f); lastFrame = now;
        float fade = animate ? Math.min(1, (now - opened) / 140_000_000f) : 1;
        if (editing) { library(canvas, fade, now); return; }
        float ease = animate ? 1 - (float)Math.exp(-dt * 18) : 1;
        for (int i = 0; i < slots(); i++) glow[i] += ((selection == i && enabled ? 1 : 0) - glow[i]) * ease;
        if (canvas.textures()) {
            int cell = 512;
            for (int tile = 0; tile < 2 * slots() + 2; tile++) {
                int kind = tile < slots() ? tile : tile == slots() ? CENTER
                        : tile == slots() + 1 ? GUTTER : RIM + tile - slots() - 2;
                canvas.image("textures/ui/wheel-" + slots() + ".png", cx - radius, cy - radius,
                        radius * 2, radius * 2, tile % 4 * cell, tile / 4 * cell, cell, cell,
                        cell * 4, cell * 5, color(kind, enabled, fade));
            }
        } else for (Span span : spans) {
            int kind = span.kind();
            canvas.fill(cx + span.x(), cy + span.y(), cx + span.end(), cy + span.y() + 1, color(kind, enabled, fade));
        }
        // A soft reflection along the top edge gives the translucent surface
        // a glass rim; the native screen supplies background frost where supported.
        for(int row=3;row<=5;row++) {
            int dx=(int)Math.sqrt(radius*radius-(radius-row)*(radius-row));
            canvas.fill(cx-dx+2,cy-radius+row,cx+dx-2,cy-radius+row+1,alpha(0x18FFFFFF,fade));
        }
        canvas.text(canvas.translate("cubeonclient.menu.emotes"), cx, cy - radius - 22, alpha(TEXT, fade));
        for (int i = 0; i < slots(); i++) {
            double angle = i * stepAngle() - Math.PI / 2;
            int x = cx + (int)Math.round(Math.cos(angle) * radius * .72);
            int y = cy + (int)Math.round(Math.sin(angle) * radius * .72);
            int color = alpha(enabled ? mix(DIM, TEXT, glow[i]) : FAINT, fade);
            icon(canvas, x, y - 7, radius / 116f, emote(i), color);
            canvas.text(Integer.toString(i+1), x, y + 12, color);
        }
        // The dead zone never chooses an emote. Clicking the center stops one.
        canvas.text(ClientUi.fit(canvas,canvas.translate(selection >= 0 ? "cubeonclient.emote." + favorites[selection]
                : "cubeonclient.emotes.stop"),(int)(radius*.74)-6), cx, cy - 3, alpha(TEXT, fade));
        int centerWidth=centerWidth();
        button(canvas,cx-centerWidth/2,cy-20,centerWidth,12,TOGGLE,
                enabled?"cubeonclient.state.on":"cubeonclient.state.off",fade);
        button(canvas,cx-centerWidth/2,cy+8,centerWidth,12,EDIT,
                centerWidth<60?"cubeonclient.emotes.edit_short":"cubeonclient.emotes.edit",fade);
    }
    private void library(Canvas canvas, float fade, long now) {
        int top = libraryTop();
        canvas.text(canvas.translate("cubeonclient.emotes.edit"), cx, top-27, alpha(TEXT, fade));
        canvas.text(favorites.length+" / "+EmoteFavorites.MAX, cx, top-13, alpha(DIM, fade));
        for (int i=0; i<EmoteState.NAMES.length; i++) {
            int left = cx-cellWidth+(i%2)*cellWidth, y = top+(i/2)*rowHeight;
            boolean chosen = favorite(i), hover = selection == i;
            ClientUi.panel(canvas, left+3, y+2, cellWidth-6, rowHeight-4, 5,
                    hover ? GLASS_HI : GLASS,
                    chosen ? BORDER_HI : hover ? BORDER_HI : BORDER, fade);
            icon(canvas, left+18, y+rowHeight/2, .5f, i, alpha(chosen ? TEXT : DIM, fade));
            canvas.text(canvas.translate("cubeonclient.emote."+EmoteState.NAMES[i]),
                    left+cellWidth/2+8, y+rowHeight/2-4, alpha(chosen ? TEXT : DIM, fade));
        }
        canvas.text(canvas.translate(now < noticeUntil ? notice : "cubeonclient.emotes.favorites_hint"),
                cx, top+rowHeight*5+6, alpha(now < noticeUntil ? TEXT : DIM, fade));
        button(canvas, cx-65, top+rowHeight*5+20, 130, 20, DONE, "cubeonclient.emotes.done", fade);
    }
    private int color(int kind, boolean enabled, float fade) {
        int color;
        if (kind < CENTER) color = mix(kind % 2 == 0 ? GLASS : 0x70444444, GLASS_HI, glow[kind]);
        else if (kind == CENTER) color = selection == STOP ? 0x80606060 : 0x70252525;
        else if (kind == GUTTER) color = BORDER;
        else color = mix(BORDER, BORDER_HI, glow[kind - RIM]);
        return alpha(color, fade);
    }
    private void button(Canvas canvas, int x, int y, int width, int height, int target, String key, float fade) {
        boolean hover=selection==target;
        ClientUi.panel(canvas,x,y,width,height,Math.min(5,height/2),hover?GLASS_HI:GLASS,
                hover?BORDER_HI:BORDER,fade);
        canvas.text(ClientUi.fit(canvas,canvas.translate(key),width-8),x+width/2,y+(height-9)/2,
                alpha(hover?TEXT:DIM,fade));
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
    private static final int[][] ARMS = {{-4,-3,-10,-12,4,-3,8,5}, {-4,-3,-11,-7,4,-3,10,-11},
                {-2,0,-8,4,4,0,10,4}, {-4,-3,-8,5,4,-3,4,-10},
                {-4,-3,-11,-5,4,-3,11,-5}, {-4,-3,-8,5,4,-3,14,-3},
                {-4,-3,0,-1,4,-3,0,-1}, {-4,-3,1,-7,4,-3,2,3},
                {-4,-3,-7,6,4,-3,7,6}, {-4,-3,-8,-14,4,-3,8,-14}};
    private static void icon(Canvas canvas, int x, int y, float scale, int emote, int color) {
        if (canvas.textures()) {
            int size = Math.max(14, Math.round(scale * 40));
            canvas.image("textures/ui/icons.png", x - size / 2, y - size / 2, size, size,
                    emote * 128, 0, 128, 128, 1408, 128, color);
            return;
        }
        int headX = emote == 2 ? 3 : 0, headY = emote == 2 ? -5 : -10;
        int h = Math.max(3, Math.round(scale * 5));
        canvas.fill(x + Math.round((headX - 2) * scale), y + Math.round((headY - 2) * scale),
                x + Math.round((headX - 2) * scale) + h, y + Math.round((headY - 2) * scale) + h, color);
        line(canvas, x, y, scale, headX, headY + 5, 0, 5, color);
        line(canvas, x, y, scale, 0, 5, -5, emote == 8 ? 7 : 13, color);
        if (emote == 8) {
            line(canvas, x, y, scale, -5, 7, -10, 7, color);
            line(canvas, x, y, scale, 5, 7, 10, 7, color);
        }
        line(canvas, x, y, scale, 0, 5, 5, emote == 8 ? 7 : 13, color);
        int[] a = ARMS[emote];
        line(canvas, x, y, scale, a[0], a[1], a[2], a[3], color);
        line(canvas, x, y, scale, a[4], a[5], a[6], a[7], color);
    }
}
