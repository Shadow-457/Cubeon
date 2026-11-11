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

    /** Projected label plane: camera effects can rotate or shear both GUI axes. */
    public record Pose(float originX, float originY, float rightX, float rightY,
                       float downX, float downY) {
        public float scale() { return (float) Math.hypot(downX, downY); }
        public float x(float x, float y) { return originX + rightX * x + downX * y; }
        public float y(float x, float y) { return originY + rightY * x + downY * y; }
        public boolean valid() {
            return Float.isFinite(originX) && Float.isFinite(originY)
                    && Float.isFinite(rightX) && Float.isFinite(rightY)
                    && Float.isFinite(downX) && Float.isFinite(downY)
                    && scale() > 0 && rightX * downY - rightY * downX > 0;
        }
    }

    public static Pose pose(double x, double y, double rightX, double rightY,
                            double bottomX, double bottomY, int width, int height) {
        return new Pose(preciseScreenX(x, width), preciseScreenY(y, height),
                (float) ((rightX - x) * width / (2 * NAME_HEIGHT)),
                (float) ((y - rightY) * height / (2 * NAME_HEIGHT)),
                (float) ((bottomX - x) * width / (2 * NAME_HEIGHT)),
                (float) ((y - bottomY) * height / (2 * NAME_HEIGHT)));
    }

    /** Test all rotated bar corners before tracing visibility rays. */
    public static boolean onScreen(Pose pose, int width, int height) {
        float scale = pose.scale();
        float halfWidth = Math.max(WIDTH, 2 / scale) / 2;
        float top = NAME_HEIGHT + 2;
        float bottom = top + Math.max(HEIGHT, 1 / scale);
        for (float x : new float[]{-halfWidth, halfWidth}) {
            for (float y : new float[]{top, bottom}) {
                float screenX = pose.x(x, y), screenY = pose.y(x, y);
                if (screenX < 0 || screenX > width || screenY < 0 || screenY > height) return false;
            }
        }
        return true;
    }

    /** Draw in label units, retaining the minimum GUI-pixel thickness at a distance. */
    public static void drawLocal(Fill fill, float scale, float fraction) {
        draw((x, y, right, bottom, color) ->
                        fill.draw(x / scale, y / scale, right / scale, bottom / scale, color),
                0, (NAME_HEIGHT + 2) * scale, scale, fraction);
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
