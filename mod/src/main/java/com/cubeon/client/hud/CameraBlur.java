package com.cubeon.client.hud;

/** Camera blur measured in seconds, never a blend with last frame's image. */
public final class CameraBlur {
    public static final CameraBlur INSTANCE = new CameraBlur();
    public static final double EXPOSURE_SECONDS = .008;
    private long previousTime;
    private long motionTime;
    // A 125 Hz mouse can leave eight milliseconds between changed samples.
    private static final double IDLE_SECONDS = .012;
    private double previousYaw, previousPitch, previousFov;
    private Object scene;
    private double velocityX, velocityY;
    private float x, y;

    public void reset() {
        previousTime = motionTime = 0; scene = null; velocityX = velocityY = 0; x = y = 0;
    }
    public float x() { return x; }
    public float y() { return y; }
    public boolean moving() { return x * x + y * y > .0000000025f; }

    /** Updates normalized UV exposure; callers supply the rendered camera. */
    public void update(long now, double yaw, double pitch, double fov, double aspect,
                       Object world, boolean enabled) {
        update(now, yaw, pitch, fov, aspect, world, enabled, 1);
    }

    public void update(long now, double yaw, double pitch, double fov, double aspect,
                       Object world, boolean enabled, double intensity) {
        intensity = Double.isFinite(intensity) ? Math.max(.25, Math.min(2, intensity)) : 1;
        if (!enabled || world == null || !Double.isFinite(yaw) || !Double.isFinite(pitch)
                || !Double.isFinite(fov) || !Double.isFinite(aspect) || aspect <= 0) {
            reset(); return;
        }
        double dt = (now - previousTime) / 1e9;
        double sampleDt = (now - motionTime) / 1e9;
        double turn = wrap(yaw - previousYaw), tilt = pitch - previousPitch;
        boolean cut = previousTime == 0 || world != scene || dt <= 0 || dt > .15
                // Rate limits also use seconds; per-frame angle limits change at low FPS.
                || Math.abs(turn) / sampleDt > 6000 || Math.abs(tilt) / sampleDt > 6000
                || Math.abs(fov - previousFov) / dt > 1200;
        previousTime = now; previousYaw = yaw; previousPitch = pitch;
        previousFov = fov; scene = world;
        if (cut) { motionTime = now; velocityX = velocityY = 0; x = y = 0; return; }
        if (Math.abs(turn) + Math.abs(tilt) < 1e-7) {
            // Repeated camera samples are normal when FPS exceeds mouse polling.
            // Hold only the exposure vector, never an old image, until input idles.
            if (sampleDt >= IDLE_SECONDS) { velocityX = velocityY = 0; x = y = 0; }
            return;
        }
        motionTime = now;
        // After an idle pause, the first delta belongs to the current frame.
        if (velocityX == 0 && velocityY == 0 && sampleDt > IDLE_SECONDS) sampleDt = dt;
        double scale = 2 * Math.tan(Math.toRadians(Math.max(10, Math.min(170, fov))) / 2);
        double vx = Math.toRadians(turn) / (sampleDt * scale * aspect);
        double vy = -Math.toRadians(tilt) / (sampleDt * scale);
        // Time-based smoothing tames float camera quantization at high FPS.
        double weight = -Math.expm1(-sampleDt / .024);
        velocityX += (vx - velocityX) * weight;
        velocityY += (vy - velocityY) * weight;
        double bx = velocityX * EXPOSURE_SECONDS * intensity, by = velocityY * EXPOSURE_SECONDS * intensity;
        double length = Math.hypot(bx, by);
        double maximum = .06 * intensity;
        double limit = length > maximum ? maximum / length : 1;
        x = (float)(bx * limit); y = (float)(by * limit);
    }
    private static double wrap(double angle) {
        return angle - 360 * Math.floor((angle + 180) / 360);
    }
}
