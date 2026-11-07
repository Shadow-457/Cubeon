package com.cubeon.client.hud;

/** Name-tag-sized bar shared by both Minecraft namespaces. */
public final class EnemyHealthBar {
    public static final double RANGE = 24.0;
    public static final int MAX_BARS = 32;
    public static final int WIDTH = 36;
    public static final int HEIGHT = 4;
    public static final int NAME_HEIGHT = 9;
    public static final float NAME_WORLD_HEIGHT = 0.225F;
    public static final int BACKGROUND = 0xD914181E;

    private EnemyHealthBar() {}

    @FunctionalInterface
    public interface Fill {
        void draw(float x, float y, float right, float bottom, int color);
    }

    /** Preserve subpixel motion and a visible fill without integer-size jumps. */
    public static void draw(Fill fill, float center, float top, float scale, float fraction) {
        float width = Math.max(2, WIDTH * scale);
        float height = Math.max(1, HEIGHT * scale);
        float x = center - width / 2;
        float inset = Math.max(0, Math.min(scale, (height - 1) / 2));
        fill.draw(x, top, x + width, top + height, BACKGROUND);
        if (fraction > 0) fill.draw(x + inset, top + inset,
                x + inset + (width - 2 * inset) * fraction, top + height - inset, color(fraction));
    }

    public static double lerp(double previous, double current, float delta) {
        return previous + (current - previous) * delta;
    }

    /** NDC depth alone cannot reject behind-camera points with reversed-Z projections. */
    public static boolean inFront(double x, double y, double z, org.joml.Vector3fc forward) {
        double distance = x * forward.x() + y * forward.y() + z * forward.z();
        return Double.isFinite(distance) && distance > 0.05;
    }

    public static float fraction(float health, float maximum) {
        if (!Float.isFinite(health) || !Float.isFinite(maximum) || maximum <= 0) return 0;
        return Math.max(0, Math.min(1, health / maximum));
    }

    public static int color(float fraction) {
        return fraction > 0.5F ? 0xFF83C13D : fraction > 0.25F ? 0xFFEBC46A : 0xFFE87979;
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

    public static float preciseScreenX(double ndc, int width) {
        return (float) ((ndc + 1) * 0.5 * width);
    }

    public static float preciseScreenY(double ndc, int height) {
        return (float) ((1 - ndc) * 0.5 * height);
    }

    /** Keep bar and label proportions together under distance, FOV and GUI scaling. */
    public static float labelScale(double top, double bottom, int screenHeight) {
        return (float) (Math.abs(bottom - top) * 0.5 * screenHeight / NAME_HEIGHT);
    }
}
