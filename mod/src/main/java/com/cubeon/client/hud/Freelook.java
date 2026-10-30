package com.cubeon.client.hud;

/** Camera-only orbit state. No entity angles, packets, or vanilla options are changed here. */
public final class Freelook {
    public static final Freelook INSTANCE = new Freelook();
    public static final double DEFAULT_DISTANCE = 4, MIN_DISTANCE = 1, MAX_DISTANCE = 12;
    private boolean active, blocked;
    private Object owner, world;
    private int previousView;
    private float yaw, pitch;
    private double targetDistance = DEFAULT_DISTANCE, distance = DEFAULT_DISTANCE;
    private long lastNanos;

    /** Returns the perspective to use: 0 first person, 1 rear, 2 front. */
    public int update(boolean held, boolean eligible, Object player, Object level,
                      float playerYaw, float playerPitch, int view) {
        if (!held) blocked = false;
        if (active && (!held || !eligible || player != owner || level != world || view != 1)) {
            active = false;
            owner = world = null;
            blocked = held;
            // A manual F5 change wins. Otherwise put back the saved perspective.
            return view == 1 ? previousView : view;
        }
        if (!eligible && held) blocked = true;
        if (!active && held && eligible && !blocked && player != null && level != null) {
            previousView = view;
            owner = player;
            world = level;
            yaw = wrap(playerYaw + (view == 2 ? 180 : 0));
            pitch = clampPitch(view == 2 ? -playerPitch : playerPitch);
            active = true;
            distance = targetDistance;
            lastNanos = System.nanoTime();
        }
        return active ? 1 : view;
    }

    public boolean active() { return active; }
    public float yaw() { return yaw; }
    public float pitch() { return pitch; }

    /** Vanilla has already applied sensitivity and inversion; it turns 0.15 degrees/unit. */
    public boolean look(double dx, double dy) {
        if (!active) return false;
        if (Double.isFinite(dx)) yaw = wrap(yaw + dx * .15);
        if (Double.isFinite(dy)) pitch = clampPitch(pitch + dy * .15);
        return true;
    }

    /** Scroll up brings the camera closer. Return false for an unused wheel event. */
    public boolean scroll(double notches) {
        if (!active || !Double.isFinite(notches) || notches == 0) return false;
        targetDistance = Math.max(MIN_DISTANCE,
                Math.min(MAX_DISTANCE, targetDistance * Math.pow(1.2, -notches)));
        return true;
    }

    public double distance() {
        long now = System.nanoTime();
        double seconds = lastNanos == 0 ? 0 : Math.max(0, (now - lastNanos) / 1e9);
        lastNanos = now;
        return easeDistance(seconds);
    }

    /** Continuous-time easing, also usable by the deterministic regression harness. */
    double easeDistance(double seconds) {
        if (Double.isFinite(seconds) && seconds > 0)
            distance += (targetDistance - distance) * (1 - Math.exp(-seconds / .1));
        return distance;
    }

    private static float wrap(double degrees) {
        if (!Double.isFinite(degrees)) return 0;
        return (float) (((degrees + 180) % 360 + 360) % 360 - 180);
    }
    private static float clampPitch(double degrees) {
        return Double.isFinite(degrees) ? (float) Math.max(-90, Math.min(90, degrees)) : 0;
    }
}
