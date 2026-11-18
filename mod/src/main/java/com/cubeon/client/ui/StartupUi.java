package com.cubeon.client.ui;

import java.awt.image.BufferedImage;
import java.io.InputStream;
import java.io.IOException;
import java.util.ArrayList;
import javax.imageio.ImageIO;

/** Boot artwork uses classloader bytes and solid quads, before resource packs are ready. */
public final class StartupUi {
    public static final int BACKGROUND = 0xFF0A0D0B;
    private static final int[][] LOGO = loadLogo();
    private StartupUi() { }

    @FunctionalInterface
    public interface Canvas {
        void fill(int left, int top, int right, int bottom, int color);
    }

    private static int[][] loadLogo() {
        try (InputStream stream = StartupUi.class.getResourceAsStream(
                "/assets/cubeon-client/textures/gui/startup-logo.png")) {
            if (stream == null) return new int[0][];
            BufferedImage image = ImageIO.read(stream);
            if (image == null || image.getWidth() != 32 || image.getHeight() != 32) return new int[0][];
            ArrayList<int[]> runs = new ArrayList<>();
            for (int y = 0; y < 32; y++) {
                for (int x = 0; x < 32;) {
                    int color = image.getRGB(x, y), end = x + 1;
                    while (end < 32 && image.getRGB(end, y) == color) end++;
                    if ((color >>> 24) != 0) runs.add(new int[]{x, y, end, color});
                    x = end;
                }
            }
            return runs.toArray(new int[0][]);
        } catch (IOException error) {
            return new int[0][];
        }
    }

    /** Match vanilla's one-second hold and one-second fade; no extra loading delay. */
    public static float opacity(long now, long finishedAt) {
        return finishedAt < 0 ? 1 : Math.max(0, Math.min(1, 2 - (now - finishedAt) / 1000f));
    }

    public static void draw(Canvas canvas, int width, int height, float progress, float opacity) {
        if (width < 32 || height < 48 || opacity <= 0) return;
        int logoSize = Math.min(64, Math.min(width / 3, height / 3));
        int left = (width - logoSize) / 2, top = (height - logoSize) / 2 - 12;
        for (int[] run : LOGO) {
            int alpha = Math.round((run[3] >>> 24) * opacity);
            canvas.fill(left + run[0] * logoSize / 32, top + run[1] * logoSize / 32,
                    left + run[2] * logoSize / 32, top + (run[1] + 1) * logoSize / 32,
                    (run[3] & 0xFFFFFF) | (alpha << 24));
        }
        int barWidth = Math.min(168, width - 32), x = (width - barWidth) / 2;
        int y = top + logoSize + 22;
        int alpha = Math.round(255 * opacity) << 24;
        canvas.fill(x, y, x + barWidth, y + 4, alpha | 0x293029);
        float value = Float.isFinite(progress) ? Math.max(0, Math.min(1, progress)) : 0;
        int filled = Math.round(barWidth * value);
        if (filled > 0) canvas.fill(x, y, x + filled, y + 4, alpha | 0x6FAF3C);
    }
}
