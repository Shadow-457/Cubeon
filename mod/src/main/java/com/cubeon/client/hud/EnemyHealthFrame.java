package com.cubeon.client.hud;

/** Shared frame marker for health renderers that run inside the world queue. */
public final class EnemyHealthFrame {
    private static long frame;
    private static boolean worldLabels;

    private EnemyHealthFrame() {}

    public static void begin() {
        frame++;
    }

    public static long current() {
        return frame;
    }

    public static void enableWorldLabels() {
        worldLabels = true;
    }

    public static boolean usesWorldLabels() {
        return worldLabels;
    }
}
