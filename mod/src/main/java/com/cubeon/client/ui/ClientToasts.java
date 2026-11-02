package com.cubeon.client.ui;

import com.cubeon.client.Bridge;
import java.util.ArrayDeque;

/** Six live notices at most; no worker, image downloads or historical replay. */
public final class ClientToasts {
    private record Notice(String text, boolean error, long born) { }
    private static final ArrayDeque<Notice> queue = new ArrayDeque<>();
    private ClientToasts() { }
    public static synchronized void accept(Bridge.Toast toast) {
        if (toast == null || toast.text() == null || toast.text().isBlank()) return;
        long now = System.nanoTime();
        String text = toast.text().substring(0, Math.min(512, toast.text().length())).replace('\n', ' ');
        for (var notice : queue) if (notice.text().equals(text) && now - notice.born() < 3_000_000_000L) return;
        while (queue.size() >= 6) queue.removeFirst();
        queue.addLast(new Notice(text, toast.error(), now));
    }
    public static synchronized void render(ClientUi.Canvas canvas, int width, int height) {
        long now = System.nanoTime();
        queue.removeIf(notice -> now - notice.born() > 5_000_000_000L);
        if (queue.isEmpty()) return;
        int w = Math.min(250, width - 16), rows = Math.min(3, (height - 16) / 46), i = 0;
        for (var notice : queue) {
            if (i >= rows) break;
            float age = (now - notice.born()) / 1e9f;
            float fade = Math.min(1, Math.min(age / .18f, (5 - age) / .25f));
            int x = width - w - 8, y = 8 + i++ * 46;
            ClientUi.panel(canvas, x, y, w, 40, 7, ClientUi.SURFACE, ClientUi.BORDER_HI, fade);
            ClientUi.mark(canvas, x + 8, y + 10, fade);
            ClientUi.left(canvas, "Cubeon", x + 34, y + 6, ClientUi.alpha(notice.error() ? 0xFFFF9C89 : ClientUi.ACCENT_HI, fade));
            ClientUi.left(canvas, ClientUi.fit(canvas, notice.text(), w - 42), x + 34, y + 21, ClientUi.alpha(ClientUi.TEXT, fade));
        }
    }
    public static synchronized void clear() { queue.clear(); }
}
