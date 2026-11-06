package com.cubeon.client.hud;

/** Short two-frame exposure for Motion blur+, with clean scene cuts. */
public final class TemporalBlur {
    public static final TemporalBlur INSTANCE = new TemporalBlur();
    private long time;
    private Object world;
    private double yaw, pitch, fov, aspect;
    private float weight;
    public float weight() { return weight; }
    public void reset() { time = 0; world = null; weight = 0; }
    public void update(long now, double newYaw, double newPitch, double newFov, double newAspect,
                       Object newWorld, boolean enabled, double strength) {
        if (!enabled || newWorld == null || !Double.isFinite(newYaw) || !Double.isFinite(newPitch)
                || !Double.isFinite(newFov) || !Double.isFinite(newAspect) || newAspect <= 0) {
            reset(); return;
        }
        double dt = (now - time) / 1e9;
        double turn = newYaw - yaw;
        turn -= 360 * Math.floor((turn + 180) / 360);
        boolean cut = time == 0 || world != newWorld || dt <= 0 || dt > .15
                || Math.abs(turn) > 45 || Math.abs(newPitch - pitch) > 45
                || Math.abs(newFov - fov) > 8 || Math.abs(newAspect - aspect) > .05;
        strength = Double.isFinite(strength) ? Math.max(.25, Math.min(2, strength)) : 1;
        // History contains only the previous raw scene, never accumulated output.
        // Keep the current frame dominant and fade old samples at low FPS.
        weight = cut ? 0 : (float)Math.min(Math.min(.45, .3 * strength), Math.exp(-dt / (.008 * strength)));
        time = now; world = newWorld; yaw = newYaw; pitch = newPitch; fov = newFov; aspect = newAspect;
    }
}
