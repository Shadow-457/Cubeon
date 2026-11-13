package com.cubeon.client.hud;

/** Projected enemy heart-and-number label shared by both Minecraft namespaces. */
public final class EnemyHealthBar {
    public static final double RANGE = 24.0;
    public static final int MAX_BARS = 32;
    public static final int HEART_WIDTH = HealthHearts.HEART_WIDTH;
    public static final int GAP = 2;
    public static final int DIGIT_WIDTH = 6;
    public static final int HEIGHT = HealthHearts.HEIGHT;
    public static final int NAME_HEIGHT = 9;
    public static final float NAME_WORLD_HEIGHT = 0.225F;
    public static final int TOP = NAME_HEIGHT + 2;

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

    /** Test all rotated heart-and-number corners before tracing visibility. */
    public static boolean onScreen(Pose pose, int width, int height, int contentWidth) {
        float halfWidth = contentWidth / 2F;
        float top = TOP;
        float bottom = top + HEIGHT;
        for (float x : new float[]{-halfWidth, halfWidth}) {
            for (float y : new float[]{top, bottom}) {
                float screenX = pose.x(x, y), screenY = pose.y(x, y);
                if (screenX < 0 || screenX > width || screenY < 0 || screenY > height) return false;
            }
        }
        return true;
    }

    public static int heartValue(float health) {
        return HealthHearts.value(health);
    }

    public static int contentWidth(int hearts) {
        return HEART_WIDTH + GAP + Math.max(1, Integer.toString(Math.max(0, hearts)).length()) * DIGIT_WIDTH;
    }

    public static float left(int hearts) {
        return -contentWidth(hearts) / 2F;
    }

    public static float numberX(int hearts) {
        return left(hearts) + HEART_WIDTH + GAP;
    }

    /** One heart follows the same continuous projected plane as the integer label. */
    public static void drawLocal(Fill fill, int hearts) {
        draw(fill, left(hearts), TOP, 1);
    }

    /** Preserve subpixel motion without integer-size jumps. */
    public static void draw(Fill fill, float left, float top, float scale) {
        HealthHearts.draw(fill::draw, left, top, scale);
    }

    public static double lerp(double previous, double current, float delta) {
        return previous + (current - previous) * delta;
    }

    /** NDC depth alone cannot reject behind-camera points with reversed-Z projections. */
    public static boolean inFront(double x, double y, double z, org.joml.Vector3fc forward) {
        double distance = x * forward.x() + y * forward.y() + z * forward.z();
        return Double.isFinite(distance) && distance > 0.05;
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

    /** Keep hearts and label proportions together under distance, FOV and GUI scaling. */
    public static float labelScale(double top, double bottom, int screenHeight) {
        return (float) (Math.abs(bottom - top) * 0.5 * screenHeight / NAME_HEIGHT);
    }
}
