package com.cubeon.client.ui;

import com.cubeon.client.Bridge;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;

/** Custom Cubeon artwork and conversation state. Native adapters provide only text input. */
public final class FriendsPanel {
    public static final int SEND = -2, CLOSE = -3, NONE = -1;
    private static final LinkedHashMap<String, String> DRAFTS = new LinkedHashMap<>();
    private static final LinkedHashMap<String, Long> PENDING = new LinkedHashMap<>();
    private final Bridge bridge;
    private String peer = "";
    private long sentId;
    private String draftKey() { return bridge.snapshot().you() + ":" + peer; }
    private int x, y, w, h, rail, friendOffset, scroll, wrappedWidth, transcriptHeight;
    private List<Bridge.ChatMessage> wrappedMessages = List.of();
    private record Bubble(List<String> lines, boolean outgoing, int width, int height, int top) { }
    private final List<Bubble> bubbles = new ArrayList<>();
    private final LinkedHashMap<Bridge.ChatMessage, Bubble> wrapCache = new LinkedHashMap<>();
    private final long opened = System.nanoTime();
    private String localError = "";

    public FriendsPanel(Bridge bridge) { this.bridge = bridge; bridge.start(); bridge.wake(); }
    public void layout(int width, int height) {
        w = Math.min(width - 32, Math.min(660, Math.max(288, Math.round(width * .84f))));
        h = Math.min(height - 24, Math.min(380, Math.max(216, Math.round(height * .84f))));
        x = (width - w) / 2; y = (height - h) / 2; rail = Math.max(88, Math.min(156, w / 4));
    }
    public int inputX() { return x + rail + 16; }
    public int inputY() { return y + h - 37; }
    public int inputWidth() { return w - rail - 72; }
    public String peer() { return peer; }
    public String draft() {
        synchronized (DRAFTS) {
            String key = draftKey();
            Long pending = PENDING.get(key);
            var sent = bridge.chatSent();
            if (pending != null && pending == sent.id()) {
                PENDING.remove(key);
                if (sent.result().ok() && DRAFTS.getOrDefault(key, "").trim().equals(sent.text())) DRAFTS.remove(key);
                if (!sent.result().ok()) localError = sent.result().error();
            } else if (pending != null) sentId = pending;
            return DRAFTS.getOrDefault(key, "");
        }
    }
    public void saveDraft(String text) {
        if (peer.isEmpty()) return;
        synchronized (DRAFTS) {
            if (text.isEmpty()) DRAFTS.remove(draftKey()); else DRAFTS.put(draftKey(), text);
            while (DRAFTS.size() > 32) {
                String oldest = DRAFTS.keySet().iterator().next(); DRAFTS.remove(oldest); PENDING.remove(oldest);
            }
        }
    }
    public boolean ensurePeer() {
        if (peer.isEmpty() && !bridge.snapshot().friends().isEmpty()) { select(0); return true; }
        return false;
    }
    public void select(int index) {
        var friends = bridge.snapshot().friends();
        if (index < 0 || index >= friends.size()) return;
        String next = friends.get(index).name();
        if (next.equals(peer)) return;
        peer = next; scroll = 0; localError = ""; bridge.openChat(peer);
    }
    public void step(int direction) {
        var friends = bridge.snapshot().friends();
        for (int i = 0; i < friends.size(); i++) if (friends.get(i).name().equals(peer)) {
            int next = Math.floorMod(i + direction, friends.size()); select(next);
            friendOffset = Math.max(0, next - Math.max(1, (h - 80) / 36) + 1); return;
        }
        ensurePeer();
    }
    public boolean send(String text) {
        saveDraft(text);
        if (text.isBlank()) return false;
        long id = bridge.sendChat(peer, text);
        if (id == 0) { localError = bridge.chat().sending() ? "Sending…" : "Couldn't send. Keep Cubeon connected and try again."; return false; }
        sentId = id;
        synchronized (DRAFTS) {
            PENDING.put(draftKey(), id);
            while (PENDING.size() > 32) PENDING.remove(PENDING.keySet().iterator().next());
        }
        localError = ""; return true;
    }
    /** Clear this send's unchanged draft only after relay-confirmed shared storage. */
    public boolean completed(String text) {
        var sent = bridge.chatSent();
        if (sentId == 0 || sent.id() != sentId) return false;
        sentId = 0;
        synchronized (DRAFTS) { PENDING.remove(bridge.snapshot().you() + ":" + sent.peer()); }
        if (!sent.result().ok()) { localError = sent.result().error(); return false; }
        if (peer.equals(sent.peer()) && text.trim().equals(sent.text())) { saveDraft(""); return true; }
        synchronized (DRAFTS) {
            if (DRAFTS.getOrDefault(bridge.snapshot().you() + ":" + sent.peer(), "").trim().equals(sent.text())) DRAFTS.remove(bridge.snapshot().you() + ":" + sent.peer());
        }
        return false;
    }
    public void close() { bridge.closeChat(); }
    public int hit(double mx, double my) {
        if (mx >= x + w - 36 && mx < x + w - 12 && my >= y + 12 && my < y + 36) return CLOSE;
        if (mx >= x + w - 44 && mx < x + w - 12 && my >= y + h - 44 && my < y + h - 16) return SEND;
        if (mx >= x + 8 && mx < x + rail - 4 && my >= y + 64 && my < y + 64 + Math.max(1, (h - 80) / 36) * 36) {
            int index = friendOffset + ((int)my - y - 64) / 36;
            return index < bridge.snapshot().friends().size() ? index : NONE;
        }
        return NONE;
    }
    public void scroll(double mx, double amount) {
        if (mx < x + rail) {
            int count = bridge.snapshot().friends().size(), visible = Math.max(1, (h - 80) / 36);
            friendOffset = Math.max(0, Math.min(Math.max(0, count - visible), friendOffset - (int)Math.signum(amount) * 3));
        } else scroll = Math.max(0, Math.min(Math.max(0, transcriptHeight - (h - 144)), scroll + (int)Math.signum(amount) * 36));
    }
    private void avatar(ClientUi.Canvas c, String name, int left, int top, int size, boolean online, float fade) {
        ClientUi.rounded(c, left, top, size, size, 5, ClientUi.alpha(MenuUi.SELECTED, fade));
        String initial = name.isEmpty() ? "?" : name.substring(0, Character.charCount(name.codePointAt(0))).toUpperCase(java.util.Locale.ROOT);
        c.text(initial, left + size / 2, top + (size - 9) / 2, ClientUi.alpha(MenuUi.TEXT, fade));
        ClientUi.rounded(c, left + size - 5, top + size - 5, 6, 6, 3, ClientUi.alpha(online ? 0xFF8DBA83 : MenuUi.FAINT, fade));
    }
    public void render(ClientUi.Canvas canvas, int width, int height, int mx, int my) {
        render(canvas, width, height, mx, my, true);
    }
    public void render(ClientUi.Canvas canvas, int width, int height, int mx, int my, boolean animate) {
        layout(width, height);
        float fade = animate ? Math.min(1, (System.nanoTime() - opened) / 160_000_000f) : 1;
        MenuUi.panel(canvas, x, y, w, h, 10, MenuUi.SURFACE, MenuUi.BORDER_HI, fade);
        MenuUi.mark(canvas, x + 12, y + 16, fade);
        ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate("cubeonclient.friends.chat_title"), rail - 46), x + 40, y + 21, ClientUi.alpha(MenuUi.TEXT, fade));
        MenuUi.button(canvas, x + w - 36, y + 12, 24, 24, "×", hit(mx, my) == CLOSE ? 1 : 0, false, fade);
        canvas.fill(x + rail, y + 12, x + rail + 1, y + h - 12, ClientUi.alpha(MenuUi.BORDER, fade));
        int left = x + rail + 16, bodyWidth = w - rail - 32;
        var view = bridge.chat();
        var selected = bridge.snapshot().friends().stream().filter(friend -> friend.name().equals(peer)).findFirst().orElse(null);
        if (!peer.isEmpty()) {
            avatar(canvas, selected == null ? peer : selected.displayName(), left, y + 16, 24, selected != null && selected.online(), fade);
            ClientUi.left(canvas, ClientUi.fit(canvas, selected == null ? peer : selected.displayName(), bodyWidth - 66), left + 32, y + 17, ClientUi.alpha(MenuUi.TEXT, fade));
        }
        String status = bridge.snapshot().connected()
                ? canvas.translate(selected != null && selected.online() ? "cubeonclient.friends.online_synced" : "cubeonclient.friends.synced")
                : bridge.snapshot().connectionLine();
        ClientUi.left(canvas, ClientUi.fit(canvas, status, bodyWidth - (peer.isEmpty() ? 20 : 34)), left + (peer.isEmpty() ? 0 : 32), y + 32,
                ClientUi.alpha(bridge.snapshot().connected() ? MenuUi.DIM : MenuUi.FAINT, fade));
        canvas.fill(left, y + 52, x + w - 12, y + 53, ClientUi.alpha(MenuUi.BORDER, fade));
        var friends = bridge.snapshot().friends();
        int visible = Math.max(1, (h - 80) / 36);
        friendOffset = Math.max(0, Math.min(friendOffset, Math.max(0, friends.size() - visible)));
        for (int i = friendOffset; i < Math.min(friends.size(), friendOffset + visible); i++) {
            var friend = friends.get(i); int top = y + 64 + (i - friendOffset) * 36;
            boolean active = friend.name().equals(peer);
            MenuUi.panel(canvas, x + 8, top, rail - 12, 32, 0, active ? MenuUi.SELECTED : hit(mx, my) == i ? MenuUi.SURFACE_HI : MenuUi.SURFACE, active ? MenuUi.BORDER_HI : MenuUi.BORDER, fade);
            if (active) ClientUi.rounded(canvas, x + 8, top + 8, 2, 16, 1, ClientUi.alpha(MenuUi.ACCENT, fade));
            avatar(canvas, friend.displayName(), x + 16, top + 6, 20, friend.online(), fade);
            ClientUi.left(canvas, ClientUi.fit(canvas, friend.displayName(), rail - 52), x + 42, top + 5, ClientUi.alpha(MenuUi.TEXT, fade));
            ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate(friend.online() ? "cubeonclient.friends.online" : "cubeonclient.friends.offline"), rail - 52), x + 42, top + 18, ClientUi.alpha(MenuUi.FAINT, fade));
        }
        int top = y + 64, bottom = y + h - 80;
        if (peer.isEmpty()) {
            ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate("cubeonclient.friends.empty"), bodyWidth), left, top + 16, ClientUi.alpha(MenuUi.DIM, fade));
            ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate("cubeonclient.friends.add_hint"), bodyWidth), left, top + 32, ClientUi.alpha(MenuUi.FAINT, fade));
        } else if (view.loading()) {
            for (int i = 0; i < 3 && top + i * 28 + 20 <= bottom; i++) ClientUi.rounded(canvas, left + (i % 2) * 24, top + i * 28, Math.max(16, bodyWidth - 32 - i * 12), 20, 6, ClientUi.alpha(MenuUi.SURFACE_HI, fade));
        } else {
            wrap(canvas, view.peer().equals(peer) ? view.messages() : List.of(), Math.max(16, bodyWidth - 16));
            int viewport = Math.max(1, bottom - top);
            scroll = Math.min(scroll, Math.max(0, transcriptHeight - viewport));
            int offset = Math.max(0, transcriptHeight - viewport) - scroll;
            if (bubbles.isEmpty()) ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate("cubeonclient.friends.say_hello"), bodyWidth), left, top + 12, ClientUi.alpha(MenuUi.FAINT, fade));
            for (Bubble bubble : bubbles) {
                int by = top + bubble.top - offset;
                if (by >= bottom || by + bubble.height <= top) continue;
                int bx = bubble.outgoing ? left + bodyWidth - bubble.width : left;
                int clipTop = Math.max(top, by), clipBottom = Math.min(bottom, by + bubble.height);
                canvas.fill(bx, clipTop, bx + bubble.width, clipBottom, ClientUi.alpha(bubble.outgoing ? MenuUi.SELECTED : MenuUi.SURFACE_HI, fade));
                for (int i = 0; i < bubble.lines.size(); i++) {
                    int lineY = by + 8 + i * 12;
                    if (lineY >= top && lineY + 9 <= bottom) ClientUi.left(canvas, bubble.lines.get(i), bx + 10, lineY, ClientUi.alpha(MenuUi.TEXT, fade));
                }
            }
        }
        String error = localError.isEmpty() ? view.error() : localError;
        String feedback = !error.isEmpty() ? error : view.sending() ? canvas.translate("cubeonclient.friends.confirming") : "";
        if (!feedback.isEmpty()) {
            // Two short lines preserve a useful refusal at the smallest GUI scale.
            List<String> feedbackLines = split(canvas, feedback, bodyWidth);
            for (int i = 0; i < Math.min(2, feedbackLines.size()); i++) ClientUi.left(canvas, feedbackLines.get(i), left, y + h - 76 + i * 11,
                    ClientUi.alpha(error.isEmpty() ? MenuUi.DIM : 0xFFFF9C89, fade));
        }
        MenuUi.panel(canvas, left - 4, y + h - 44, inputWidth() + 8, 28, 6, MenuUi.SURFACE_HI, MenuUi.BORDER_HI, fade);
        boolean ready = !peer.isEmpty() && bridge.snapshot().connected() && !view.sending();
        MenuUi.button(canvas, x + w - 44, y + h - 44, 32, 28, "", ready && hit(mx, my) == SEND ? 1 : 0, false, fade);
        int ax = x + w - 34, ay = y + h - 34, color = ClientUi.alpha(ready ? MenuUi.ACCENT_HI : MenuUi.FAINT, fade);
        // Small custom send arrow, not a Minecraft widget or emoji.
        canvas.fill(ax, ay + 3, ax + 10, ay + 5, color);
        for (int i = 0; i < 4; i++) canvas.fill(ax + 7 + i, ay + i, ax + 8 + i, ay + 8 - i, color);
        ClientUi.left(canvas, ClientUi.fit(canvas, canvas.translate("cubeonclient.friends.keyboard_hint"), bodyWidth), left, y + h - 11, ClientUi.alpha(MenuUi.FAINT, fade));
    }
    private static List<String> split(ClientUi.Canvas canvas, String text, int width) {
        var result = new ArrayList<String>();
        for (String paragraph : text.replace('\r', ' ').replace('§', ' ').split("\n", -1)) {
            int start = 0;
            if (paragraph.isEmpty()) result.add("");
            while (start < paragraph.length()) {
                int end = start, space = -1;
                while (end < paragraph.length()) {
                    int next = end + Character.charCount(paragraph.codePointAt(end));
                    if (canvas.width(paragraph.substring(start, next)) > width) break;
                    if (paragraph.charAt(end) == ' ') space = end;
                    end = next;
                }
                if (end == start) end += Character.charCount(paragraph.codePointAt(start));
                if (end < paragraph.length() && space > start) end = space;
                result.add(paragraph.substring(start, end)); start = end;
                while (start < paragraph.length() && paragraph.charAt(start) == ' ') start++;
            }
        }
        return result;
    }
    private void wrap(ClientUi.Canvas canvas, List<Bridge.ChatMessage> messages, int width) {
        if (width == wrappedWidth && messages.equals(wrappedMessages)) return;
        if (width != wrappedWidth) wrapCache.clear();
        wrappedWidth = width; wrappedMessages = messages; bubbles.clear(); transcriptHeight = 0;
        for (var message : messages) {
            Bubble cached = wrapCache.get(message);
            if (cached == null) {
                List<String> lines = split(canvas, message.text(), Math.max(1, width - 20));
                int widest = 0; for (String line : lines) widest = Math.max(widest, canvas.width(line));
                cached = new Bubble(List.copyOf(lines), "out".equals(message.direction()), Math.min(width, Math.max(32, widest + 20)), lines.size() * 12 + 12, 0);
                wrapCache.put(message, cached);
                while (wrapCache.size() > 200) wrapCache.remove(wrapCache.keySet().iterator().next());
            }
            bubbles.add(new Bubble(cached.lines, cached.outgoing, cached.width, cached.height, transcriptHeight));
            transcriptHeight += cached.height + 8;
        }
        transcriptHeight = Math.max(0, transcriptHeight - 8);
    }
}
