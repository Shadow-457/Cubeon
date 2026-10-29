package com.cubeon.client.hud;

/** Small screen-space bar shared by both Minecraft namespaces. */
public final class EnemyHealthBar {
    public static final double RANGE = 24.0;
    public static final int MAX_BARS = 32;
    public static final int WIDTH = 36;
    public static final int HEIGHT = 4;
    public static final int BACKGROUND = 0xD914181E;

    private EnemyHealthBar() {}

    public static float fraction(float health, float maximum) {
        if (!Float.isFinite(health) || !Float.isFinite(maximum) || maximum <= 0) return 0;
        return Math.max(0, Math.min(1, health / maximum));
    }

    public static int color(float fraction) {
        return fraction > 0.5F ? 0xFF65CD91 : fraction > 0.25F ? 0xFFEBC46A : 0xFFE87979;
    }

    /** Minecraft project methods return NDC, not GUI pixels. Reject behind-camera points. */
    public static boolean onScreen(double x, double y, double z) {
        return Double.isFinite(x) && Double.isFinite(y) && Double.isFinite(z)
                && x >= -1 && x <= 1 && y >= -1 && y <= 1 && z >= -1 && z < 1;
    }

    public static int screenX(double ndc, int width) {
        return (int) Math.round((ndc + 1) * 0.5 * width);
    }

    public static int screenY(double ndc, int height) {
        return (int) Math.round((1 - ndc) * 0.5 * height);
    }
}
