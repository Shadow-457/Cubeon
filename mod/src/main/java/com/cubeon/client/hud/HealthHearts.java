package com.cubeon.client.hud;

/** Minecraft-free drawing of one vanilla-style 9x9 heart. */
public final class HealthHearts {
    public static final int HEART_WIDTH = 9;
    public static final int WIDTH = HEART_WIDTH;
    public static final int HEIGHT = 9;
    private static final int BLACK = 0xFF000000;
    private static final int RED = 0xFFFF1313;
    private static final int RED_SHADOW = 0xFFBB1313;
    private static final int HIGHLIGHT = 0xFFFFC8C8;

    // Exact opaque pixels from vanilla's hud/heart/container, full and half
    // sprites, merged vertically where consecutive rows share the same run.
    private static final int[][] CONTAINER_BLACK = {
        {2,0,4,1}, {5,0,7,1}, {1,1,2,2}, {4,1,5,2}, {7,1,8,2},
        {0,2,1,5}, {8,2,9,5}, {1,5,2,6}, {7,5,8,6},
        {2,6,3,7}, {6,6,7,7}, {3,7,4,8}, {5,7,6,8}, {4,8,5,9}
    };
    private static final int[][] FULL_RED = {
        {2,1,4,2}, {5,1,7,2}, {1,2,2,3}, {3,2,8,3},
        {1,3,8,4}, {2,4,7,5}, {3,5,6,6}, {4,6,5,7}
    };
    private static final int[][] FULL_SHADOW = {
        {1,4,2,5}, {7,4,8,5}, {2,5,3,6}, {6,5,7,6},
        {3,6,4,7}, {5,6,6,7}, {4,7,5,8}
    };
    private HealthHearts() {}

    @FunctionalInterface
    public interface Fill {
        void draw(float x, float y, float right, float bottom, int color);
    }

    /** Whole hearts remaining; positive fractional health always remains visible as one. */
    public static int value(float health) {
        if (!Float.isFinite(health) || health <= 0) return 0;
        return Math.min(9999, (int) Math.ceil(health / 2.0F));
    }

    public static void draw(Fill fill, float left, float top, float scale) {
        if (!Float.isFinite(scale) || scale <= 0) return;
        runs(fill, CONTAINER_BLACK, left, top, scale, BLACK);
        runs(fill, FULL_RED, left, top, scale, RED);
        runs(fill, FULL_SHADOW, left, top, scale, RED_SHADOW);
        fill.draw(left + 2 * scale, top + 2 * scale, left + 3 * scale, top + 3 * scale, HIGHLIGHT);
    }

    private static void runs(Fill fill, int[][] runs, float x, float y, float scale, int color) {
        for (int[] run : runs) {
            fill.draw(x + run[0] * scale, y + run[1] * scale,
                    x + run[2] * scale, y + run[3] * scale, color);
        }
    }
}
